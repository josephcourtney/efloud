from __future__ import annotations

import hashlib
import io
import time
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from efloud.content.protocol import AnnexKey
from efloud.repository_models import ContentId, ContentRef

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO


@dataclass(slots=True)
class MemoryContentStore:
    """Fast content-custody double for tests that do not exercise git-annex."""

    _content: dict[AnnexKey, bytes] = field(default_factory=dict)
    _created_at: dict[AnnexKey, float] = field(default_factory=dict)
    _urls: dict[AnnexKey, str] = field(default_factory=dict)

    @staticmethod
    def _key(data: bytes) -> AnnexKey:
        digest = hashlib.sha256(data).hexdigest()
        return AnnexKey(f"memory:{digest}")

    def ingest_path(self, path: Path) -> AnnexKey:
        return self.ingest_bytes(path.read_bytes())

    def ingest_bytes(self, data: bytes) -> AnnexKey:
        payload = bytes(data)
        key = self._key(payload)
        self._content.setdefault(key, payload)
        self._created_at.setdefault(key, time.time())
        return key

    def ingest_url(self, url: str) -> AnnexKey:
        with urllib.request.urlopen(url) as response:  # noqa: S310 - test double accepts fixture URLs
            payload = response.read()
        key = self.ingest_bytes(payload)
        self._urls[key] = url
        return key

    def content_ref(self, key: AnnexKey, *, media_type: str | None = None) -> ContentRef:
        data = self._content[key]
        digest = hashlib.sha256(data).hexdigest()
        return ContentRef(
            content_id=ContentId(f"sha256:{digest}"),
            byte_size=len(data),
            custody_key=str(key),
            media_type=media_type,
        )

    def has_content(self, key: AnnexKey) -> bool:
        return key in self._content

    def open(self, key: AnnexKey) -> BinaryIO:
        try:
            return io.BytesIO(self._content[key])
        except KeyError as exc:
            raise FileNotFoundError(str(key)) from exc

    def verify(self, key: AnnexKey) -> bool:
        data = self._content.get(key)
        return data is not None and self._key(data) == key

    def present_keys(self) -> tuple[AnnexKey, ...]:
        return tuple(sorted(self._content, key=str))

    def drop_key(self, key: AnnexKey) -> None:
        self._content.pop(key, None)
        self._created_at.pop(key, None)

    def register_url(self, key: AnnexKey, url: str) -> None:
        self._urls[key] = url

    def get(self, key: AnnexKey) -> None:
        if key in self._content:
            return
        url = self._urls.get(key)
        if url is None:
            raise FileNotFoundError(str(key))
        with urllib.request.urlopen(url) as response:  # noqa: S310 - test double accepts fixture URLs
            payload = response.read()
        if self._key(payload) != key:
            msg = f"Reacquired bytes do not match {key}"
            raise ValueError(msg)
        self._content[key] = payload
        self._created_at[key] = time.time()

    def custody_mtime(self, key: AnnexKey) -> float:
        try:
            return self._created_at[key]
        except KeyError as exc:
            raise FileNotFoundError(str(key)) from exc
