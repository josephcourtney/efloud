"""Safe, non-mutating filesystem handoff from RepositoryView."""

from __future__ import annotations

import ctypes
import fcntl
import os
import shutil
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from efloud.dataset_export import MANIFEST_FILENAME, DetachedDatasetManifest, safe_export_path

if TYPE_CHECKING:
    from typing import BinaryIO

    from efloud.repository_view import RepositoryView

type ExportStrategy = Literal["auto", "reflink", "copy", "symlink"]


@dataclass(frozen=True, slots=True)
class ExportPlan:
    destination: Path
    manifest: DetachedDatasetManifest
    strategy: ExportStrategy


def _validate_paths(manifest: DetachedDatasetManifest) -> None:
    paths = {MANIFEST_FILENAME.casefold(), ".content"}
    for member in manifest.members:
        path = unicodedata.normalize("NFC", safe_export_path(member.path)).casefold()
        if any(path == other or path.startswith(other + "/") or other.startswith(path + "/") for other in paths):
            msg = f"Export path collision: {member.path}"
            raise ValueError(msg)
        paths.add(path)


def _clone(stream: BinaryIO, destination: Path) -> None:
    """Attempt native CoW from the read capability's open descriptor."""
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        clone = libc.fclonefileat
        clone.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        clone.restype = ctypes.c_int
        if clone(stream.fileno(), -2, os.fsencode(destination), 0) != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))
    elif sys.platform.startswith("linux"):
        with destination.open("xb") as output:
            fcntl.ioctl(output.fileno(), 0x40049409, stream.fileno())
    else:
        msg = "Native reflink is unavailable on this platform"
        raise OSError(msg)


def _publish_directory(staging: Path, destination: Path) -> None:
    """Atomically publish without ever replacing or exposing an existing tree."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(staging), os.fsencode(destination), 4)
    elif sys.platform.startswith("linux"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1)
    else:
        msg = "Atomic exclusive directory publication is unavailable on this platform"
        raise OSError(msg)
    if result != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), destination)


def _flush_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    directories = [path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()]
    for directory in [*sorted(directories, reverse=True), root]:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class DatasetMaterializer:
    """Consume only semantic read operations; publish independent content copies."""

    def __init__(self, repository: RepositoryView) -> None:
        self.repository = repository

    def plan(
        self, manifest: DetachedDatasetManifest, destination: Path, *, strategy: ExportStrategy = "auto"
    ) -> ExportPlan:
        manifest.validate()
        _validate_paths(manifest)
        for member in manifest.members:
            if not self.repository.contains_content(member.content_id):
                msg = f"Export content is unavailable: {member.content_id}"
                raise FileNotFoundError(msg)
        if strategy not in {"auto", "reflink", "copy", "symlink"}:
            raise ValueError(strategy)
        target = destination.absolute()
        if target.resolve().is_relative_to(self.repository.root.resolve()):
            msg = "Export destination must be outside the repository"
            raise ValueError(msg)
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        if not target.parent.is_dir():
            raise FileNotFoundError(target.parent)
        return ExportPlan(target, manifest, strategy)

    def export(
        self,
        manifest: DetachedDatasetManifest,
        destination: Path,
        *,
        strategy: ExportStrategy = "auto",
        dry_run: bool = False,
    ) -> ExportPlan:
        plan = self.plan(manifest, destination, strategy=strategy)
        if dry_run:
            return plan
        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=plan.destination.parent))
        try:
            self._populate(plan, staging)
            if not manifest.verify(staging):
                msg = "Export content failed detached verification"
                raise ValueError(msg)
            (staging / MANIFEST_FILENAME).write_bytes(manifest.to_bytes())
            _flush_tree(staging)
            _publish_directory(staging, plan.destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return plan

    def _populate(self, plan: ExportPlan, staging: Path) -> None:
        for member in plan.manifest.members:
            target = staging / member.path
            target.parent.mkdir(parents=True, exist_ok=True)
            if plan.strategy == "symlink":
                private = staging / ".content" / member.content_id.removeprefix("sha256:")
                private.parent.mkdir(exist_ok=True)
                if not private.exists():
                    self._copy(member.content_id, private, "copy")
                target.symlink_to(os.path.relpath(private, target.parent))
            else:
                self._copy(member.content_id, target, plan.strategy)

    def _copy(self, content_id: str, target: Path, strategy: ExportStrategy) -> None:
        with self.repository.open_content(content_id) as stream:
            if strategy in {"auto", "reflink"}:
                try:
                    _clone(stream, target)
                except (OSError, AttributeError):
                    target.unlink(missing_ok=True)
                    if strategy == "reflink":
                        raise
                else:
                    return
            with target.open("xb") as output:
                shutil.copyfileobj(stream, output)
                output.flush()
                os.fsync(output.fileno())


__all__ = ["DatasetMaterializer", "ExportPlan", "ExportStrategy"]
