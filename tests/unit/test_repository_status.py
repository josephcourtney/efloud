from pathlib import Path

import pytest

from efloud.json_types import JsonMapping, JsonValue, json_mapping_or_none
from efloud.repository import Repository
from efloud.repository_models import OperationId, RunId, SourceId
from efloud.repository_query import RepositoryQueryService

pytestmark = [
    pytest.mark.unit,
    pytest.mark.db,
    pytest.mark.regression,
    pytest.mark.medium,
]


def _mapping(value: JsonValue | None) -> JsonMapping:
    mapping = json_mapping_or_none(value)
    assert mapping is not None
    return mapping


def _array(value: JsonValue | None) -> list[JsonValue]:
    assert isinstance(value, list)
    return value


def _assert_source_payload(
    query: RepositoryQueryService,
    *,
    snapshot_id: str,
) -> None:
    payload = query.query("source:source-a")
    source = _mapping(payload.get("source"))
    snapshot = _mapping(payload.get("latest_snapshot"))
    operations = _array(payload.get("operations"))

    assert source["source_id"] == "source-a"
    assert snapshot["snapshot_id"] == snapshot_id
    assert _mapping(operations[0])["status"] == "success"


def _assert_run_payload(
    query: RepositoryQueryService,
    *,
    run_id: RunId,
    operation_id: OperationId,
) -> None:
    payload = query.query(f"run:{run_id}")
    run_record = _mapping(payload.get("run"))
    operations = _array(payload.get("operations"))

    assert run_record["status"] == "success"
    assert run_record["metadata"] == {"purpose": "test"}
    assert _mapping(operations[0])["operation_id"] == str(operation_id)


def _assert_root_payload(
    query: RepositoryQueryService,
    *,
    run_id: RunId,
) -> None:
    payload = query.query("root")
    sources = _array(payload.get("sources"))
    recent_runs = _array(payload.get("recent_runs"))

    assert _mapping(sources[0])["source_id"] == "source-a"
    assert _mapping(recent_runs[0])["run_id"] == str(run_id)


def test_source_and_run_status_survive_reopen_without_manifests(tmp_path: Path) -> None:
    repo = Repository(tmp_path)
    source = repo.register_source(
        SourceId("source-a"),
        {"kind": "HTTP", "url": "https://example.invalid/data.json"},
    )
    run_id = repo.start_run(
        source_ids=(source,),
        started_at=100.0,
        metadata={"purpose": "test"},
    )
    operation_id = repo.start_operation(
        run_id=run_id,
        source_id=source,
        kind="http",
        subject="source-a",
        started_at=100.0,
        parameters={"url": "https://example.invalid/data.json"},
    )
    repo.ingest_bytes(
        "source:source-a",
        b"{}",
        run_id=run_id,
        operation_id=operation_id,
        source_id=source,
        observed_at=101.0,
        media_type="application/json",
    )
    snapshot = repo.record_source_snapshot(
        source_id=source,
        run_id=run_id,
        complete=True,
        observed_at=101.0,
        evidence={"etag": "abc"},
    )
    repo.finish_operation(operation_id, status="success", finished_at=102.0)
    repo.finish_run(run_id, status="success", finished_at=103.0)
    repo.close()

    assert not (tmp_path / "sync-manifest.json").exists()
    assert not (tmp_path / "mirror-state.json").exists()

    with Repository(tmp_path) as reopened:
        query = RepositoryQueryService(reopened)

        _assert_source_payload(
            query,
            snapshot_id=str(snapshot.snapshot_id),
        )
        _assert_run_payload(
            query,
            run_id=run_id,
            operation_id=operation_id,
        )
        _assert_root_payload(
            query,
            run_id=run_id,
        )
