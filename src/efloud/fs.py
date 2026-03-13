from __future__ import annotations

import contextlib
import gzip
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def atomic_write_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(dest.parent), delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
    tmp_path.replace(dest)


def atomic_write_text(dest: Path, text: str) -> None:
    atomic_write_bytes(dest, text.encode("utf-8"))


def safe_json_dump(obj: object) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def read_gz_json(path: Path) -> object:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def ensure_root_dirs(root: Path, dirs: Mapping[str, str]) -> dict[str, Path]:
    resolved = root.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    path_map: dict[str, Path] = {"root": resolved}
    for key, subdir in dirs.items():
        path = resolved / subdir
        path.mkdir(parents=True, exist_ok=True)
        path_map[key] = path
    return path_map


def delete_http_cache_files(cache_root: Path) -> list[str]:
    removed: list[str] = []
    for path in cache_root.glob("*.sqlite"):
        with contextlib.suppress(OSError):
            path.unlink()
            removed.append(str(path))
    return removed


def prune_orphan_mirrors(mirrors_root: Path, keep_dirs: Iterable[Path]) -> list[str]:
    removed: list[str] = []
    if not mirrors_root.exists():
        return removed
    keep_set = set(keep_dirs)
    for child in mirrors_root.iterdir():
        if not child.is_dir():
            continue
        if child in keep_set:
            continue
        with contextlib.suppress(OSError):
            shutil.rmtree(child)
            removed.append(str(child))
    return removed


def read_text_maybe_gzip(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8", errors="replace")
