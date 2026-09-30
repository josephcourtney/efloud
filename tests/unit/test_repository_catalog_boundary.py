from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from efloud.catalog import MemoryCatalog
from efloud.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

    from efloud.metadata_store import MetadataStore
    from efloud.repository_models import ContentId, ContentRef

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.medium]


class _UnusedBlobStore:
    """Fail if a catalog-only repository slice touches content storage."""

    def put_path(self, path: Path, *, media_type: str | None = None) -> ContentRef:
        del path, media_type
        raise AssertionError

    def put_bytes(self, data: bytes, *, media_type: str | None = None) -> ContentRef:
        del data, media_type
        raise AssertionError

    def open(self, content_id: ContentId) -> BinaryIO:
        del content_id
        raise AssertionError

    def contains(self, content_id: ContentId) -> bool:
        del content_id
        raise AssertionError

    def verify(self, content_id: ContentId) -> bool:
        del content_id
        raise AssertionError

    def delete(self, content_id: ContentId) -> None:
        del content_id
        raise AssertionError


def test_repository_semantics_run_with_memory_catalog_without_legacy_storage(tmp_path: Path) -> None:
    catalog = MemoryCatalog()
    with Repository(
        tmp_path,
        metadata_store=cast("MetadataStore", catalog),
        blob_store=_UnusedBlobStore(),
    ) as repository:
        source_id = repository.register_source("memory-source", {"kind": "memory"})
        run_id = repository.start_run(source_ids=(source_id,), started_at=1.0)
        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source_id,
            kind="fetch",
            subject="memory",
            started_at=2.0,
        )
        repository.finish_operation(operation_id, status="succeeded", finished_at=3.0)
        repository.finish_run(run_id, status="succeeded", finished_at=4.0)

        source = repository.source(source_id)
        run = repository.run(run_id)
        operation = repository.operation(operation_id)
        assert source is not None
        assert source.definition == {"kind": "memory"}
        assert run is not None
        assert run.status == "succeeded"
        assert operation is not None
        assert operation.status == "succeeded"

    assert not (tmp_path / "metadata.sqlite").exists()
    assert not (tmp_path / "objects").exists()
