from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING

import pytest

from efloud.datasets import DatasetDefinition, Latest
from efloud.repository import Repository
from efloud.repository_models import ContentId, ContentRef, SourceId

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.medium]


class MemoryBlobStore:
    """Minimal pathless blob store used to enforce the generic repository contract."""

    def __init__(self) -> None:
        self._data: dict[ContentId, bytes] = {}

    @staticmethod
    def _content_id(data: bytes) -> ContentId:
        return ContentId(f"sha256:{hashlib.sha256(data).hexdigest()}")

    def put_path(self, path: Path, *, media_type: str | None = None) -> ContentRef:
        return self.put_bytes(path.read_bytes(), media_type=media_type)

    def put_bytes(self, data: bytes, *, media_type: str | None = None) -> ContentRef:
        content_id = self._content_id(data)
        self._data.setdefault(content_id, bytes(data))
        return ContentRef(content_id, len(data), media_type=media_type)

    def open(self, content_id: ContentId) -> BinaryIO:
        try:
            data = self._data[content_id]
        except KeyError:
            raise FileNotFoundError(str(content_id)) from None
        return io.BytesIO(data)

    def contains(self, content_id: ContentId) -> bool:
        return content_id in self._data

    def verify(self, content_id: ContentId) -> bool:
        data = self._data.get(content_id)
        return data is not None and self._content_id(data) == content_id

    def delete(self, content_id: ContentId) -> bool:
        return self._data.pop(content_id, None) is not None


def _run(repo: Repository):
    source = repo.register_source(SourceId("memory-source"), {"kind": "memory"})
    run = repo.start_run(source_ids=(source,), started_at=100.0)
    operation = repo.start_operation(
        run_id=run,
        source_id=source,
        kind="fetch",
        subject="memory",
        started_at=100.0,
    )
    return source, run, operation


def test_content_ref_storage_location_is_not_semantic() -> None:
    content_id = ContentId("sha256:" + "a" * 64)
    first = ContentRef(content_id, 7, storage_key="backend-one/object", media_type="application/test")
    second = ContentRef(content_id, 7, storage_key="backend-two/object", media_type="application/test")

    assert first == second
    assert first.to_dict() == second.to_dict() == {
        "content_id": str(content_id),
        "byte_size": 7,
        "media_type": "application/test",
    }
    assert "storage_key" not in first.to_dict()


def test_repository_and_dataset_work_with_pathless_blob_store(tmp_path: Path) -> None:
    blob_store = MemoryBlobStore()
    assert not hasattr(blob_store, "path_for")

    with Repository(tmp_path, blob_store=blob_store) as repo:
        source, run, operation = _run(repo)
        observation = repo.ingest_bytes(
            "artifact:memory",
            b"payload",
            run_id=run,
            operation_id=operation,
            source_id=source,
            observed_at=101.0,
            media_type="application/octet-stream",
        )
        assert blob_store.contains(observation.content_id)
        assert repo.verify_content(observation.content_id)
        with repo.open_content(observation.content_id) as stream:
            assert stream.read() == b"payload"

        persisted = repo.metadata.content(observation.content_id)
        assert persisted is not None
        assert persisted.content_id == observation.content_id
        assert persisted.byte_size == len(b"payload")
        assert "storage_key" not in persisted.to_dict()

        dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(Latest("artifact:memory")))
        assert dataset.verify()
        with dataset.open("artifact:memory") as stream:
            assert stream.read() == b"payload"


def test_pathless_blob_store_contains_verify_and_delete() -> None:
    store = MemoryBlobStore()
    ref = store.put_bytes(b"payload")

    assert store.contains(ref.content_id)
    assert store.verify(ref.content_id)
    assert store.delete(ref.content_id) is True
    assert store.contains(ref.content_id) is False
    assert store.verify(ref.content_id) is False
    assert store.delete(ref.content_id) is False
