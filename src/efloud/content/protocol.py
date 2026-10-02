from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

    from efloud.repository_models import ContentRef


@dataclass(frozen=True, slots=True)
class AnnexKey:
    """Opaque git-annex content key used only at the infrastructure boundary."""

    value: str

    def __post_init__(self) -> None:
        """Reject keys that cannot be passed as one command argument."""
        if not self.value or "\n" in self.value or "\r" in self.value:
            msg = "git-annex keys must be non-empty single-line strings"
            raise ValueError(msg)

    def __str__(self) -> str:
        """Return the git-annex key text."""
        return self.value


class ContentReader(Protocol):
    """Read-only content-custody port."""

    def has_content(self, key: AnnexKey) -> bool: ...

    def open(self, key: AnnexKey) -> BinaryIO: ...

    def verify(self, key: AnnexKey) -> bool: ...

    def content_ref(self, key: AnnexKey, *, media_type: str | None = None) -> ContentRef: ...

    def present_keys(self) -> tuple[AnnexKey, ...]: ...

    def custody_mtime(self, key: AnnexKey) -> float: ...


class ContentStore(ContentReader, Protocol):
    """Narrow content-custody port; semantic identity remains outside the store."""

    def ingest_path(self, path: Path) -> AnnexKey: ...

    def ingest_bytes(self, data: bytes) -> AnnexKey: ...

    def ingest_url(self, url: str) -> AnnexKey: ...

    def content_ref(self, key: AnnexKey, *, media_type: str | None = None) -> ContentRef: ...

    def has_content(self, key: AnnexKey) -> bool: ...

    def open(self, key: AnnexKey) -> BinaryIO: ...

    def verify(self, key: AnnexKey) -> bool: ...

    def present_keys(self) -> tuple[AnnexKey, ...]: ...

    def drop_key(self, key: AnnexKey) -> None: ...

    def register_url(self, key: AnnexKey, url: str) -> None: ...

    def get(self, key: AnnexKey) -> None: ...

    def custody_mtime(self, key: AnnexKey) -> float: ...


__all__ = ["AnnexKey", "ContentReader", "ContentStore"]
