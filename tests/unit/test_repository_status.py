from pathlib import Path

import pytest

from efloud.json_types import JsonMapping, JsonValue, json_mapping_or_none
from efloud.repository import Repository
from efloud.repository_models import SourceId
from efloud.repository_query import RepositoryQueryService

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.small]


def _mapping(value: JsonValue | None) -> JsonMapping:
    mapping = json_mapping_or_none(value)
    assert mapping is not None
    return mapping


def _array(value: JsonValue | None) -> list[JsonValue]:
    assert isinstance(value, list)
    return value


def test_source_and_run_status_survive_reopen_without_manifests(tmp_path: Path) -> None:
    repo = Repository(tmp_path)
    source = repo.register_source(
        SourceId("source-a"),
        {"kind": "HTTP", "url": "https://example.invalid/data.json"},
    )
    run = repo.start_run(source_ids=(source,), started_at=100.0, metadata={"purpose": "test"})
    operation = repo.start_operation(
        run_id=run,
        source_id=source,
        kind="http",
        subject="source-a",
        started_at=100.0,
        parameters={"url": "https://example.invalid/data.json"},
    )
    repo.ingest_bytes(
        "source:source-a",
        b"{}",
        run_id=run,
        operation_id=operation,
        source_id=source,
        observed_at=101.0,
        media_type="application/json",
    )
    snapshot = repo.record_source_snapshot(
        source_id=source,
        run_id=run,
        complete=True,
        observed_at=101.0,
        evidence={"etag": "abc"},
    )
    repo.finish_operation(operation, status="success", finished_at=102.0)
    repo.finish_run(run, status="success", finished_at=103.0)
    repo.close()

    assert not (tmp_path / "sync-manifest.json").exists()
    assert not (tmp_path / "mirror-state.json").exists()

    with Repository(tmp_path) as reopened:
        query = RepositoryQueryService(reopened)
        source_payload = query.query("source:source-a")
        source_record = _mapping(source_payload.get("source"))
        latest_snapshot = _mapping(source_payload.get("latest_snapshot"))
        source_operations = _array(source_payload.get("operations"))
        assert source_record["source_id"] == "source-a"
        assert latest_snapshot["snapshot_id"] == str(snapshot.snapshot_id)
        assert _mapping(source_operations[0])["status"] == "success"

        run_payload = query.query(f"run:{run}")
        run_record = _mapping(run_payload.get("run"))
        run_operations = _array(run_payload.get("operations"))
        assert run_record["status"] == "success"
        assert run_record["metadata"] == {"purpose": "test"}
        assert _mapping(run_operations[0])["operation_id"] == str(operation)

        root_payload = query.query("root")
        sources = _array(root_payload.get("sources"))
        recent_runs = _array(root_payload.get("recent_runs"))
        assert _mapping(sources[0])["source_id"] == "source-a"
        assert _mapping(recent_runs[0])["run_id"] == str(run)
