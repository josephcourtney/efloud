from __future__ import annotations

import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] - argv-only subprocesses are the git/git-annex integration boundary.
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.content.protocol import AnnexKey

if TYPE_CHECKING:
    from typing import BinaryIO

_DEFAULT_BACKEND = "SHA256"
_GIT_IDENTITY_NAME = "Efloud"
_GIT_IDENTITY_EMAIL = "efloud@localhost.invalid"


class GitAnnexError(RuntimeError):
    """Base failure for the internal Git/git-annex command boundary."""


class GitAnnexUnavailableError(GitAnnexError):
    """Git or git-annex is not available to the current process."""


class GitAnnexCommandError(GitAnnexError):
    """A Git or git-annex subprocess returned a non-zero exit status."""

    def __init__(self, command: tuple[str, ...], returncode: int, stderr: str) -> None:
        """Capture stable command diagnostics without exposing shell execution."""
        detail = stderr.strip() or "command failed without stderr"
        super().__init__(f"Command failed ({returncode}): {' '.join(command)}: {detail}")
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


def _run(
    root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    if not root.is_dir():
        msg = f"Git working directory does not exist: {root}"
        raise GitAnnexError(msg)
    git = shutil.which("git")
    if git is None:
        msg = "git is not available on PATH"
        raise GitAnnexUnavailableError(msg)
    command = (git, *args)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - no shell; argv is passed directly to Git.
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        if args[:2] == ("annex", "version") or "not a git command" in completed.stderr:
            msg = "git-annex is not available through git"
            raise GitAnnexUnavailableError(msg)
        raise GitAnnexCommandError(command, completed.returncode, completed.stderr)
    return completed


def _require_regular_file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        msg = f"Content input must be a regular file: {resolved}"
        raise ValueError(msg)
    return resolved


@dataclass(frozen=True, slots=True)
class GitAnnexContentStore:
    """Content custody backed directly by one Git/git-annex repository."""

    root: Path
    backend: str = _DEFAULT_BACKEND

    def __post_init__(self) -> None:
        """Normalize the repository root and reject an empty backend."""
        object.__setattr__(self, "root", self.root.resolve())
        if not self.backend:
            msg = "git-annex backend must not be empty"
            raise ValueError(msg)

    @classmethod
    def initialize(
        cls,
        root: Path,
        *,
        description: str = "efloud",
        backend: str = _DEFAULT_BACKEND,
    ) -> GitAnnexContentStore:
        """Create Git/git-annex state with a cryptographic content-only backend."""
        resolved = root.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        _run(resolved, "init", "--quiet")
        _run(resolved, "config", "user.name", _GIT_IDENTITY_NAME)
        _run(resolved, "config", "user.email", _GIT_IDENTITY_EMAIL)
        _run(resolved, "config", "annex.backend", backend)
        _run(resolved, "config", "annex.securehashesonly", "true")
        _run(resolved, "annex", "init", description)
        return cls(resolved, backend=backend)

    def check_available(self) -> None:
        """Fail explicitly if the repository cannot execute git-annex."""
        _run(self.root, "annex", "version")

    def calculate_key(self, path: Path) -> AnnexKey:
        """Calculate the configured annex key without ingesting bytes."""
        source = _require_regular_file(path)
        completed = _run(
            self.root,
            "annex",
            "calckey",
            f"--backend={self.backend}",
            source.as_posix(),
        )
        value = completed.stdout.strip()
        if not value:
            msg = "git-annex calckey returned an empty key"
            raise GitAnnexError(msg)
        return AnnexKey(value)

    def ingest_path(self, path: Path) -> AnnexKey:
        """Copy caller-owned bytes into git-annex without a persistent second store."""
        source = _require_regular_file(path)
        key = self.calculate_key(source)
        if self.has_content(key):
            return key
        fd, tmp_name = tempfile.mkstemp(prefix=".efloud-annex-", dir=self.root)
        os.close(fd)
        staged = Path(tmp_name)
        try:
            shutil.copyfile(source, staged)
            _run(self.root, "annex", "setkey", str(key), staged.as_posix())
        finally:
            staged.unlink(missing_ok=True)
        if not self.has_content(key):
            msg = f"git-annex did not retain ingested content for {key}"
            raise GitAnnexError(msg)
        return key

    def ingest_bytes(self, data: bytes) -> AnnexKey:
        """Write transient bytes once, then transfer their custody to git-annex."""
        fd, tmp_name = tempfile.mkstemp(prefix=".efloud-annex-", dir=self.root)
        staged = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            key = self.calculate_key(staged)
            if self.has_content(key):
                return key
            _run(self.root, "annex", "setkey", str(key), staged.as_posix())
            if not self.has_content(key):
                msg = f"git-annex did not retain ingested content for {key}"
                raise GitAnnexError(msg)
            return key
        finally:
            staged.unlink(missing_ok=True)

    def _content_location(self, key: AnnexKey) -> Path | None:
        completed = _run(self.root, "annex", "contentlocation", str(key), check=False)
        if completed.returncode != 0:
            return None
        value = completed.stdout.strip()
        if not value:
            return None
        location = Path(value)
        return location if location.is_absolute() else self.root / location

    def has_content(self, key: AnnexKey) -> bool:
        """Return whether the key's content is physically present in this annex."""
        location = self._content_location(key)
        return location is not None and location.is_file()

    def open(self, key: AnnexKey) -> BinaryIO:
        """Open locally present content without exposing its annex object path."""
        location = self._content_location(key)
        if location is None or not location.is_file():
            raise FileNotFoundError(str(key))
        return location.open("rb")

    def verify(self, key: AnnexKey) -> bool:
        """Delegate byte-integrity verification to a full git-annex fsck."""
        if not self.has_content(key):
            return False
        completed = _run(
            self.root,
            "annex",
            "fsck",
            f"--key={key}",
            "--numcopies=1",
            "--json",
            "--json-error-messages",
            check=False,
        )
        return completed.returncode == 0


__all__ = [
    "GitAnnexCommandError",
    "GitAnnexContentStore",
    "GitAnnexError",
    "GitAnnexUnavailableError",
]
