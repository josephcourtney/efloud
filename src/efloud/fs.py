from __future__ import annotations

import gzip
import json
import os
import tempfile
from pathlib import Path


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
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def read_text_maybe_gzip(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return path.read_text(encoding="utf-8", errors="replace")
