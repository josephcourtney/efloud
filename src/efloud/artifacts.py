from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping


class SupportsArtifactPath(Protocol):
    path: str | None


def sha256_hex(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fin:
        while chunk := fin.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_gzip(path: Path) -> bool:
    try:
        with gzip.open(path, "rb") as fin:
            fin.read(1)
    except OSError:
        return False
    return True


def canonical_path(path: str) -> str:
    try:
        return str(Path(path).resolve(strict=False))
    except OSError:
        return str(Path(path))


def build_path_index[TArtifact: SupportsArtifactPath](
    *record_maps: Mapping[str, tuple[TArtifact, ...]],
) -> dict[str, tuple[TArtifact, ...]]:
    accumulator: dict[str, list[TArtifact]] = {}
    for records in record_maps:
        for statuses in records.values():
            for status in statuses:
                if not status.path:
                    continue
                key = canonical_path(status.path)
                accumulator.setdefault(key, []).append(status)
    return {path: tuple(entries) for path, entries in accumulator.items()}


__all__ = [
    "SupportsArtifactPath",
    "build_path_index",
    "canonical_path",
    "sha256_hex",
    "verify_gzip",
]
