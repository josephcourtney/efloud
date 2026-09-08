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
    replace_once(
        "src/efloud/executor.py",
        "from efloud.registry import SourceDefinition\n",
        "",
    )
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
    replace_once(
        "src/efloud/repository.py",
        "from efloud.inventory import SourceInventory\n",
        "",
    )
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
        '''        if not isinstance(value, dict):
            msg = "Expected a JSON object in metadata storage."
            raise ValueError(msg)
''',
        '''        if not isinstance(value, dict):
            msg = "Expected a JSON object in metadata storage."
            raise TypeError(msg)
''',
    )


def clean_regression_tests() -> None:
    replace_once(
        "tests/test_review_regressions.py",
        "from pathlib import Path\n",
        "from typing import TYPE_CHECKING\n",
    )
    replace_once(
        "tests/test_review_regressions.py",
        "from efloud.sqlite_metadata_v3 import SQLiteMetadataStore\n\n\n",
        "from efloud.sqlite_metadata_v3 import SQLiteMetadataStore\n\nif TYPE_CHECKING:\n    from pathlib import Path\n\n\n",
    )
    replace_once(
        "tests/test_review_regressions.py",
        '''    def fail_history_scan(*args: object, **kwargs: object) -> tuple[()]:
        del args, kwargs
        raise AssertionError("history scan must not be used")
''',
        '''    def fail_history_scan(*args: object, **kwargs: object) -> tuple[()]:
        del args, kwargs
        msg = "history scan must not be used"
        raise AssertionError(msg)
''',
    )
    text = read("tests/test_review_regressions.py")
    old = '''    original_stage = store._stage_path

    def stage_then_mutate(path: Path) -> tuple[Path, str, int]:
        staged = original_stage(path)
        source.write_bytes(b"changed-after-stage")
        return staged

    monkeypatch.setattr(store, "_stage_path", stage_then_mutate)
'''
    if old in text:
        new = '''    original_stage = FilesystemBlobStore._stage_path

    def stage_then_mutate(self: FilesystemBlobStore, path: Path) -> tuple[Path, str, int]:
        staged = original_stage(self, path)
        source.write_bytes(b"changed-after-stage")
        return staged

    monkeypatch.setattr(FilesystemBlobStore, "_stage_path", stage_then_mutate)
'''
        write("tests/test_review_regressions.py", text.replace(old, new, 1))


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
