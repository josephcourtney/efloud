from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from efloud.repository_models import ContentId, ContentRef

CHUNK_SIZE = 1024 * 1024
SHA256_HEX_LENGTH = 64


class BlobStore(Protocol):
    """Semantic immutable-content store independent of physical storage layout.

    A successful put must make the returned content immediately readable and may
    safely be repeated for the same bytes. Metadata is committed only after that
    guarantee, so a later metadata failure may leave an unreachable blob but not
    a committed reference to unavailable content.
    """

    def put_path(self, path: Path, *, media_type: str | None = None) -> ContentRef: ...

    def put_bytes(self, data: bytes, *, media_type: str | None = None) -> ContentRef: ...

    def open(self, content_id: ContentId) -> BinaryIO: ...

    def contains(self, content_id: ContentId) -> bool: ...

    def verify(self, content_id: ContentId) -> bool: ...

    def delete(self, content_id: ContentId) -> None: ...


@dataclass(frozen=True, slots=True)
class FilesystemBlobStore:
    root: Path

    def __post_init__(self) -> None:
        """Ensure the blob-store root exists."""
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest_path(path: Path) -> tuple[str, int]:
        hasher = hashlib.sha256()
        size = 0
        with path.open("rb") as fin:
            while chunk := fin.read(CHUNK_SIZE):
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
        if len(digest) != SHA256_HEX_LENGTH or any(ch not in "0123456789abcdef" for ch in digest):
            msg = f"Invalid SHA-256 content identifier: {text!r}"
            raise ValueError(msg)
        return digest

    def path_for(self, content_id: ContentId) -> Path:
        """Return the local CAS path for callers that explicitly require this backend capability."""
        digest = self._digest_from_content_id(content_id)
        return self.root / "sha256" / digest[:2] / digest

    @staticmethod
    def _content_ref(
        *,
        digest: str,
        byte_size: int,
        media_type: str | None,
    ) -> ContentRef:
        return ContentRef(
            content_id=ContentId(f"sha256:{digest}"),
            byte_size=byte_size,
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
                shutil.copyfileobj(fin, fout, length=CHUNK_SIZE)
                fout.flush()
                os.fsync(fout.fileno())
            try:
                os.link(tmp_path, destination)
            except FileExistsError:
                pass
            except OSError:
                if not destination.exists():
                    Path(tmp_path).replace(destination)
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
                    Path(tmp_path).replace(destination)
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

    def contains(self, content_id: ContentId) -> bool:
        return self.path_for(content_id).is_file()

    def verify(self, content_id: ContentId) -> bool:
        path = self.path_for(content_id)
        if not path.is_file():
            return False
        digest, _ = self._digest_path(path)
        return f"sha256:{digest}" == str(content_id)

    def delete(self, content_id: ContentId) -> None:
        self.path_for(content_id).unlink(missing_ok=True)


__all__ = [
    "BlobStore",
    "FilesystemBlobStore",
]
