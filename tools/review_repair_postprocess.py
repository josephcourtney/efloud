#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, text: str) -> None:
    (ROOT / relative).write_text(text, encoding="utf-8")


def replace_once(relative: str, old: str, new: str) -> None:
    text = read(relative)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one match, found {count}: {old[:100]!r}")
    write(relative, text.replace(old, new, 1))


def compact_root_api() -> None:
    write(
        "src/efloud/__init__.py",
        '''from __future__ import annotations

from importlib.metadata import version

from efloud.datasets import (
    DatasetDefinition,
    ExactObservation,
    ImmutableDataset,
    Latest,
    LatestAll,
    LatestBefore,
)
from efloud.engine import CompatibilityProjectionError, Engine, EngineSyncResult
from efloud.fanout import FanoutEnumeration, FanoutItem, RestBaseFanoutTask, two_char_bucket
from efloud.inventory import IntegrityExpectation
from efloud.materialization import http_dest_for_source_url, http_dests_for_source_urls
from efloud.models import EngineConfig
from efloud.planning import SyncPlan, SyncRequest
from efloud.query import query_target, root_payload, source_payload, store_payload
from efloud.registry import MirrorMode, SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_models import (
    ArtifactKey,
    ContentId,
    DatasetId,
    ObservationId,
    RunId,
    SourceId,
)
from efloud.status import collect_status_payload
from efloud.summary import build_summary
from efloud.sync import SyncResult, sync

__version__ = version("efloud")

__all__ = [
    "ArtifactKey",
    "CompatibilityProjectionError",
    "ContentId",
    "DatasetDefinition",
    "DatasetId",
    "Engine",
    "EngineConfig",
    "EngineSyncResult",
    "ExactObservation",
    "FanoutEnumeration",
    "FanoutItem",
    "ImmutableDataset",
    "IntegrityExpectation",
    "Latest",
    "LatestAll",
    "LatestBefore",
    "MirrorMode",
    "ObservationId",
    "Repository",
    "RestBaseFanoutTask",
    "RunId",
    "SourceDefinition",
    "SourceId",
    "SourceKind",
    "SyncPlan",
    "SyncRequest",
    "SyncResult",
    "__version__",
    "build_summary",
    "collect_status_payload",
    "http_dest_for_source_url",
    "http_dests_for_source_urls",
    "query_target",
    "root_payload",
    "source_payload",
    "store_payload",
    "sync",
    "two_char_bucket",
]
''',
    )


def clean_blob_store() -> None:
    replace_once(
        "src/efloud/blob_store.py",
        '''    def _stage_path(self, source: Path) -> tuple[Path, str, int]:
        """Copy once into the CAS filesystem while hashing the exact staged bytes."""
        staging = self.root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".blob.", dir=staging)
        tmp_path = Path(tmp_name)
        hasher = hashlib.sha256()
        byte_size = 0
        try:
            with os.fdopen(fd, "wb") as fout:
                with source.open("rb") as fin:
                    while chunk := fin.read(CHUNK_SIZE):
                        hasher.update(chunk)
                        byte_size += len(chunk)
                        fout.write(chunk)
                fout.flush()
                os.fsync(fout.fileno())
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        return tmp_path, hasher.hexdigest(), byte_size
''',
        '''    @staticmethod
    def _copy_and_digest(source: Path, fd: int) -> tuple[str, int]:
        hasher = hashlib.sha256()
        byte_size = 0
        with os.fdopen(fd, "wb") as fout, source.open("rb") as fin:
            while chunk := fin.read(CHUNK_SIZE):
                hasher.update(chunk)
                byte_size += len(chunk)
                fout.write(chunk)
            fout.flush()
            os.fsync(fout.fileno())
        return hasher.hexdigest(), byte_size

    def _stage_path(self, source: Path) -> tuple[Path, str, int]:
        """Copy once into the CAS filesystem while hashing the exact staged bytes."""
        staging = self.root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".blob.", dir=staging)
        tmp_path = Path(tmp_name)
        try:
            digest, byte_size = self._copy_and_digest(source, fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        return tmp_path, digest, byte_size
''',
    )


def clean_executor() -> None:
    replace_once("src/efloud/executor.py", "from efloud.registry import SourceDefinition\n", "")
    replace_once(
        "src/efloud/executor.py",
        "    from efloud.models import EngineConfig\n",
        "    from efloud.models import EngineConfig\n    from efloud.registry import SourceDefinition\n",
    )
    replace_once(
        "src/efloud/executor.py",
        "    source = _source_by_id(context.config, operation.source_id) if operation.source_id is not None else None\n",
        "",
    )


def clean_repository() -> None:
    replace_once("src/efloud/repository.py", "from efloud.inventory import SourceInventory\n", "")
    replace_once(
        "src/efloud/repository.py",
        "    from efloud.json_types import JsonObject\n",
        "    from efloud.inventory import SourceInventory\n    from efloud.json_types import JsonObject\n",
    )


def clean_schema_migration() -> None:
    replace_once(
        "src/efloud/schema_migrations.py",
        '''    for table_name, json_column in (
        ("observations", "metadata_json"),
        ("artifact_absences", "metadata_json"),
    ):
        connection.execute(
            f"""
            UPDATE {table_name}
            SET source_revision_id = COALESCE(
                (
                    SELECT revision_id FROM source_definition_revisions AS revisions
                    WHERE revisions.source_id = {table_name}.source_id
                      AND revisions.revision_id = json_extract(
                          {table_name}.{json_column}, '$.source_definition_revision_id'
                      )
                ),
                (
                    SELECT source_revision_id FROM operations
                    WHERE operations.operation_id = {table_name}.operation_id
                ),
                (SELECT current_revision_id FROM sources WHERE sources.source_id = {table_name}.source_id)
            )
            WHERE source_id IS NOT NULL
            """
        )
''',
        '''    connection.execute(
        """
        UPDATE observations
        SET source_revision_id = COALESCE(
            (
                SELECT revision_id FROM source_definition_revisions AS revisions
                WHERE revisions.source_id = observations.source_id
                  AND revisions.revision_id = json_extract(
                      observations.metadata_json, '$.source_definition_revision_id'
                  )
            ),
            (
                SELECT source_revision_id FROM operations
                WHERE operations.operation_id = observations.operation_id
            ),
            (SELECT current_revision_id FROM sources WHERE sources.source_id = observations.source_id)
        )
        WHERE source_id IS NOT NULL
        """
    )
    connection.execute(
        """
        UPDATE artifact_absences
        SET source_revision_id = COALESCE(
            (
                SELECT revision_id FROM source_definition_revisions AS revisions
                WHERE revisions.source_id = artifact_absences.source_id
                  AND revisions.revision_id = json_extract(
                      artifact_absences.metadata_json, '$.source_definition_revision_id'
                  )
            ),
            (
                SELECT source_revision_id FROM operations
                WHERE operations.operation_id = artifact_absences.operation_id
            ),
            (SELECT current_revision_id FROM sources WHERE sources.source_id = artifact_absences.source_id)
        )
        WHERE source_id IS NOT NULL
        """
    )
''',
    )


def clean_sqlite_metadata() -> None:
    replace_once(
        "src/efloud/sqlite_metadata_v3.py",
        '''    if not isinstance(value, dict):
        msg = "Expected a JSON object in repository metadata."
        raise ValueError(msg)
''',
        '''    if not isinstance(value, dict):
        msg = "Expected a JSON object in repository metadata."
        raise TypeError(msg)
''',
    )


def clean_regression_tests() -> None:
    write(
        "tests/test_review_regressions.py",
        '''from __future__ import annotations

import hashlib
import sqlite3
from typing import TYPE_CHECKING

import pytest

from efloud.blob_store import FilesystemBlobStore
from efloud.inventory import InventoryCoverage, InventoryItem, SourceInventory
from efloud.repository import Repository
from efloud.repository_models import ArtifactKey, SourceId
from efloud.sqlite_metadata_v3 import SQLiteMetadataStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_put_path_hashes_the_exact_staged_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FilesystemBlobStore(tmp_path / "objects")
    source = tmp_path / "source.bin"
    original = b"original bytes"
    source.write_bytes(original)
    original_stage = FilesystemBlobStore._stage_path

    def stage_then_mutate(self: FilesystemBlobStore, path: Path) -> tuple[Path, str, int]:
        staged = original_stage(self, path)
        path.write_bytes(b"changed after staging")
        return staged

    monkeypatch.setattr(FilesystemBlobStore, "_stage_path", stage_then_mutate)
    content = store.put_path(source)

    expected = hashlib.sha256(original).hexdigest()
    assert str(content.content_id) == f"sha256:{expected}"
    assert store.path_for(content.content_id).read_bytes() == original
    assert store.verify(content.content_id)


def test_record_absence_requires_complete_inventory(tmp_path: Path) -> None:
    with Repository(tmp_path / "repository") as repository:
        source_id = repository.register_source("source-a", {"url": "https://example.test/a"})
        run_id = repository.start_run(source_ids=[source_id], started_at=1.0)
        operation_id = repository.start_operation(
            run_id=run_id,
            kind="test",
            subject="source-a",
            source_id=source_id,
            started_at=1.0,
        )
        incomplete = SourceInventory(
            source_id=SourceId("source-a"),
            observed_at=2.0,
            coverage=InventoryCoverage(complete=False),
            items=(),
        )
        with pytest.raises(ValueError, match="complete source inventory"):
            repository.record_absence(
                "source:source-a:item:missing",
                run_id=run_id,
                operation_id=operation_id,
                source_id=source_id,
                inventory=incomplete,
            )

        present_key = ArtifactKey("source:source-a:item:present")
        complete = SourceInventory(
            source_id=SourceId("source-a"),
            observed_at=2.0,
            coverage=InventoryCoverage(complete=True),
            items=(InventoryItem(item_id="present", artifact_key=present_key),),
        )
        with pytest.raises(ValueError, match="still enumerates artifact"):
            repository.record_absence(
                present_key,
                run_id=run_id,
                operation_id=operation_id,
                source_id=source_id,
                inventory=complete,
            )

        absence = repository.record_absence(
            "source:source-a:item:missing",
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            inventory=complete,
        )
        assert absence.observed_at == complete.observed_at
        assert absence.metadata["absence_proof"]["coverage"] == {"scope": [], "complete": True}


def test_finish_operation_uses_direct_primary_key_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with Repository(tmp_path / "repository") as repository:
        source_id = repository.register_source("source-a", {"url": "https://example.test/a"})
        run_id = repository.start_run(source_ids=[source_id], started_at=1.0)
        operation_id = repository.start_operation(
            run_id=run_id,
            kind="test",
            subject="source-a",
            source_id=source_id,
            started_at=1.0,
        )

        def fail_history_scan(*args: object, **kwargs: object) -> object:
            del args, kwargs
            msg = "history scan must not be used"
            raise AssertionError(msg)

        monkeypatch.setattr(SQLiteMetadataStore, "recent_runs", fail_history_scan)
        repository.finish_operation(operation_id, status="succeeded", finished_at=2.0)
        operation = repository.metadata.operation(operation_id)
        assert operation is not None
        assert operation.status == "succeeded"


def test_schema_v4_normalizes_source_revisions(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    with Repository(root) as repository:
        repository.register_source("source-a", {"url": "https://example.test/v1"})
        repository.register_source("source-a", {"url": "https://example.test/v2"})
        source = repository.metadata.source(SourceId("source-a"))
        assert source is not None
        assert len(source.revisions) == 2
        assert isinstance(repository.metadata, SQLiteMetadataStore)
        assert repository.metadata.schema_version == 4

    connection = sqlite3.connect(root / "metadata.sqlite")
    try:
        definition, revision_id = connection.execute(
            "SELECT definition_json, current_revision_id FROM sources WHERE source_id = 'source-a'"
        ).fetchone()
        revision_count = connection.execute(
            "SELECT COUNT(*) FROM source_definition_revisions WHERE source_id = 'source-a'"
        ).fetchone()[0]
        assert "_efloud_source_definition_history" not in definition
        assert revision_id is not None
        assert revision_count == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
''',
    )


def main() -> None:
    compact_root_api()
    clean_blob_store()
    clean_executor()
    clean_repository()
    clean_schema_migration()
    clean_sqlite_metadata()
    clean_regression_tests()


if __name__ == "__main__":
    main()
