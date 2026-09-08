from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from efloud.datasets import DatasetDefinition, DatasetSelection, ExactObservation
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository import Repository
from efloud.repository_models import SourceId

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def _create_dataset(root: Path) -> tuple[str, str]:
    with Repository(root) as repository:
        source = repository.register_source(SourceId("test-source"), {"kind": "test"})
        run = repository.start_run(source_ids=(source,), started_at=100.0)
        operation = repository.start_operation(
            run_id=run,
            source_id=source,
            kind="fetch",
            subject="fixture",
            started_at=100.0,
        )
        observation = repository.ingest_bytes(
            "artifact:a",
            b"hello",
            run_id=run,
            operation_id=operation,
            source_id=source,
            media_type="text/plain",
            observed_at=101.0,
        )
        dataset = repository.resolve_dataset(
            DatasetDefinition(
                selections=(DatasetSelection(ExactObservation(observation.observation_id), role="input"),)
            )
        )
        repository.finish_operation(operation, status="succeeded", finished_at=102.0)
        repository.finish_run(run, status="succeeded", finished_at=102.0)
        return str(dataset.id), str(observation.observation_id)


def _tree_state(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_read_only_repository_reads_dataset_without_mutating_store(tmp_path: Path) -> None:
    dataset_id, observation_id = _create_dataset(tmp_path)
    before = _tree_state(tmp_path)

    with ReadOnlyRepository(tmp_path) as repository:
        dataset = repository.dataset(dataset_id)
        assert dataset.id == dataset_id
        assert dataset.artifacts()[0].role == "input"
        observation = repository.observation(observation_id)
        assert observation is not None
        content = repository.content(observation.content_id)
        assert content is not None
        assert content.byte_size == 5
        assert repository.verify_content(observation.content_id)
        with dataset.open("artifact:a") as stream:
            assert stream.read() == b"hello"
        with pytest.raises(PermissionError, match="Read-only repository"):
            repository.blobs.put_bytes(b"no")

    assert _tree_state(tmp_path) == before


def test_read_only_repository_does_not_initialize_missing_store(tmp_path: Path) -> None:
    root = tmp_path / "missing"

    with pytest.raises(FileNotFoundError):
        ReadOnlyRepository(root)

    assert not root.exists()


def test_read_only_repository_refuses_schema_migration(tmp_path: Path) -> None:
    _create_dataset(tmp_path)
    metadata = tmp_path / "metadata.sqlite"
    with closing(sqlite3.connect(metadata)) as connection:
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    before = _tree_state(tmp_path)

    with pytest.raises(RuntimeError, match="requires the current metadata schema"):
        ReadOnlyRepository(tmp_path)

    with closing(sqlite3.connect(metadata)) as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 2
    assert _tree_state(tmp_path) == before
