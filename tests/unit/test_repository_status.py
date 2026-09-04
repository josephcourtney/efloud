from pathlib import Path

import pytest

from efloud.repository import Repository
from efloud.repository_models import SourceId
from efloud.repository_query import RepositoryQueryService

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression]


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
        assert source_payload["source"]["source_id"] == "source-a"
        assert source_payload["latest_snapshot"]["snapshot_id"] == str(snapshot.snapshot_id)
        assert source_payload["operations"][0]["status"] == "success"

        run_payload = query.query(f"run:{run}")
        assert run_payload["run"]["status"] == "success"
        assert run_payload["run"]["metadata"] == {"purpose": "test"}
        assert run_payload["operations"][0]["operation_id"] == str(operation)

        root_payload = query.query("root")
        assert root_payload["sources"][0]["source_id"] == "source-a"
        assert root_payload["recent_runs"][0]["run_id"] == str(run)
