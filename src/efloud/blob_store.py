from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from efloud.repository_models import ContentId, ContentRef


class BlobStore(Protocol):
    def put_path(self, path: Path, *, media_type: str | None = None) -> ContentRef: ...

    def put_bytes(self, data: bytes, *, media_type: str | None = None) -> ContentRef: ...

    def path_for(self, content_id: ContentId) -> Path: ...

    def open(self, content_id: ContentId) -> BinaryIO: ...

    def verify(self, content_id: ContentId) -> bool: ...


@dataclass(frozen=True, slots=True)
class FilesystemBlobStore:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest_path(path: Path) -> tuple[str, int]:
        hasher = hashlib.sha256()
        size = 0
        with path.open("rb") as fin:
            while chunk := fin.read(1024 * 1024):
                hasher.update(chunk)
                size += len(chunk)
        return hasher.hexdigest(), size

    @staticmethod
    def _digest_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _digest_from_content_id(content_id: ContentId) -> str:
        text = str(content_id)
        prefix = "sha256:"
        if not text.startswith(prefix):
            msg = f"Unsupported content identifier: {text!r}"
            raise ValueError(msg)
        digest = text.removeprefix(prefix)
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            msg = f"Invalid SHA-256 content identifier: {text!r}"
            raise ValueError(msg)
        return digest

    def path_for(self, content_id: ContentId) -> Path:
        digest = self._digest_from_content_id(content_id)
        return self.root / "sha256" / digest[:2] / digest

    def _content_ref(
        self,
        *,
        digest: str,
        byte_size: int,
        media_type: str | None,
    ) -> ContentRef:
        content_id = ContentId(f"sha256:{digest}")
        path = self.path_for(content_id)
        storage_key = path.relative_to(self.root).as_posix()
        return ContentRef(
            content_id=content_id,
            byte_size=byte_size,
            storage_key=storage_key,
            media_type=media_type,
        )

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        os.close(fd)
        tmp_path: Path | None = Path(tmp_name)
        try:
            with source.open("rb") as fin, tmp_path.open("wb") as fout:
                shutil.copyfileobj(fin, fout, length=1024 * 1024)
                fout.flush()
                os.fsync(fout.fileno())
            try:
                os.link(tmp_path, destination)
            except FileExistsError:
                pass
            except OSError:
                if not destination.exists():
                    os.replace(tmp_path, destination)
                    tmp_path = None
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()

    @staticmethod
    def _atomic_write(data: bytes, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        tmp_path: Path | None = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fout:
                fout.write(data)
                fout.flush()
                os.fsync(fout.fileno())
            try:
                os.link(tmp_path, destination)
            except FileExistsError:
                pass
            except OSError:
                if not destination.exists():
                    os.replace(tmp_path, destination)
                    tmp_path = None
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()

    def put_path(self, path: Path, *, media_type: str | None = None) -> ContentRef:
        source = path.resolve(strict=True)
        if not source.is_file():
            msg = f"Blob input must be a regular file: {source}"
            raise ValueError(msg)
        digest, byte_size = self._digest_path(source)
        ref = self._content_ref(digest=digest, byte_size=byte_size, media_type=media_type)
        destination = self.path_for(ref.content_id)
        if not destination.exists():
            self._atomic_copy(source, destination)
        return ref

    def put_bytes(self, data: bytes, *, media_type: str | None = None) -> ContentRef:
        digest = self._digest_bytes(data)
        ref = self._content_ref(digest=digest, byte_size=len(data), media_type=media_type)
        destination = self.path_for(ref.content_id)
        if not destination.exists():
            self._atomic_write(data, destination)
        return ref

    def open(self, content_id: ContentId) -> BinaryIO:
        return self.path_for(content_id).open("rb")

    def verify(self, content_id: ContentId) -> bool:
        path = self.path_for(content_id)
        if not path.is_file():
            return False
        digest, _ = self._digest_path(path)
        return f"sha256:{digest}" == str(content_id)


__all__ = [
    "BlobStore",
    "FilesystemBlobStore",
]
