from __future__ import annotations

import hashlib
import io
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from efloud.content.protocol import AnnexKey
from efloud.repository_models import ContentId, ContentRef
from efloud.tree.protocol import GitCommitId, GitTreeEntry, GitTreeId, TreeBlob

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
        msg = f"MemoryContentStore does not perform network acquisition: {url}"
        raise AssertionError(msg)

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
        if key not in self._content:
            raise FileNotFoundError(str(key))

    def custody_mtime(self, key: AnnexKey) -> float:
        try:
            return self._created_at[key]
        except KeyError as exc:
            raise FileNotFoundError(str(key)) from exc


@dataclass(slots=True)
class MemoryTreeStore:
    """Fast tree/history double for tests that do not exercise Git object storage."""

    _blobs: dict[str, bytes] = field(default_factory=dict)
    _trees: dict[str, tuple[GitTreeEntry, ...]] = field(default_factory=dict)
    _commits: dict[str, str] = field(default_factory=dict)

    def write_tree(self, entries: tuple[TreeBlob, ...]) -> GitTreeId:
        listed: list[GitTreeEntry] = []
        digest = hashlib.sha256()
        for entry in entries:
            object_id = hashlib.sha256(entry.data).hexdigest()
            self._blobs[object_id] = bytes(entry.data)
            listed.append(GitTreeEntry(entry.relative_path, entry.mode, "blob", object_id))
            digest.update(entry.relative_path.encode())
            digest.update(b"\0")
            digest.update(entry.mode.encode())
            digest.update(b"\0")
            digest.update(object_id.encode())
            digest.update(b"\0")
        tree_id = GitTreeId(digest.hexdigest())
        self._trees[str(tree_id)] = tuple(listed)
        return tree_id

    def list_tree(self, treeish: GitTreeId | GitCommitId | str) -> tuple[GitTreeEntry, ...]:
        key = str(treeish)
        tree_id = self._commits.get(key, key)
        return self._trees[tree_id]

    def read_blob(self, object_id: str) -> bytes:
        return self._blobs[object_id]

    def commit_tree(self, tree: GitTreeId, *, ref: str, message: str) -> GitCommitId:
        digest = hashlib.sha256(f"{tree}\0{ref}\0{message}".encode()).hexdigest()
        commit = GitCommitId(digest)
        self._commits[str(commit)] = str(tree)
        return commit
