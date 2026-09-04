from pathlib import Path

import pytest

from efloud.models import EngineConfig
from efloud.query import query_target
from efloud.registry import MirrorMode, SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_models import SourceId, TreeEntry
from efloud.status import collect_status_payload, source_status_rows_from_repository

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def test_http_source_query_uses_repository_without_manifest_or_materialization(tmp_path: Path) -> None:
    source = SourceDefinition(
        id="http-source",
        description="HTTP source",
        url="https://example.invalid/data.json",
        kind=SourceKind.HTTP,
    )
    cfg = EngineConfig(root=tmp_path, sources=[source])
    materialized = tmp_path / "http" / "data.json"
    materialized.parent.mkdir(parents=True)
    materialized.write_text('{"answer":42}', encoding="utf-8")

    with Repository(tmp_path) as repo:
        source_id = repo.register_source(SourceId(source.id), {"kind": "HTTP", "url": source.url})
        run = repo.start_run(source_ids=(source_id,), started_at=100.0)
        operation = repo.start_operation(
            run_id=run,
            source_id=source_id,
            kind="http",
            subject=source.id,
            started_at=100.0,
        )
        observation = repo.ingest_path(
            f"source:{source.id}",
            materialized,
            run_id=run,
            operation_id=operation,
            source_id=source_id,
            observed_at=101.0,
            upstream_locator=source.url,
            upstream_version='"v1"',
            media_type="application/json",
            materialization_kind="http",
        )
        repo.record_source_snapshot(
            source_id=source_id,
            run_id=run,
            complete=True,
            observed_at=101.0,
            evidence={"etag": '"v1"', "status_code": 200},
        )
        repo.finish_operation(operation, status="success", finished_at=102.0)
        repo.finish_run(run, status="success", finished_at=103.0)
        assert repo.verify_content(observation.content_id)

    materialized.unlink()
    assert not (tmp_path / cfg.log_dir / cfg.manifest_filename).exists()

    payload = query_target(f"source:{source.id}#/answer", cfg=cfg)
    assert payload["repository_backed"] is True
    assert payload["manifest_entry"]["repository_backed"] is True
    assert payload["locator"]["value"] == 42
    assert payload["locator"]["error"] is None

    status, warnings = collect_status_payload(cfg)
    assert warnings == []
    assert status["repository_authoritative"] is True
    assert status["manifest_path"] is None
    assert status["health"]["http_results"][source.id]["content_id"] == str(observation.content_id)


def test_rsync_status_projects_authoritative_snapshot_without_manifest(tmp_path: Path) -> None:
    source = SourceDefinition(
        id="mirror",
        description="Mirror",
        url="rsync://example.invalid/module",
        kind=SourceKind.RSYNC,
        local_subpath="mirror",
        mirror_mode=MirrorMode.FULL,
    )
    cfg = EngineConfig(root=tmp_path, sources=[source])
    mirror_root = tmp_path / cfg.mirrors_dir / "mirror"
    mirror_file = mirror_root / "aa" / "a.txt"
    mirror_file.parent.mkdir(parents=True)
    mirror_file.write_bytes(b"hello")

    with Repository(tmp_path) as repo:
        source_id = repo.register_source(SourceId(source.id), {"kind": "RSYNC", "url": source.url})
        run = repo.start_run(source_ids=(source_id,), started_at=100.0)
        operation = repo.start_operation(
            run_id=run,
            source_id=source_id,
            kind="rsync",
            subject=source.id,
            started_at=100.0,
        )
        observation = repo.ingest_path(
            f"source:{source.id}:path:aa/a.txt",
            mirror_file,
            run_id=run,
            operation_id=operation,
            source_id=source_id,
            observed_at=101.0,
            source_path="aa/a.txt",
            upstream_locator=f"{source.url}/aa/a.txt",
            materialization_kind="rsync-mirror",
        )
        repo.record_tree_snapshot(
            source_id=source_id,
            run_id=run,
            entries=(
                TreeEntry(
                    relative_path="aa/a.txt",
                    kind="file",
                    content_id=observation.content_id,
                    byte_size=5,
                ),
            ),
            complete=True,
            observed_at=101.0,
            evidence={"reconciliation_complete": True, "inventory_entry_count": 1},
        )
        repo.finish_operation(
            operation,
            status="success",
            finished_at=102.0,
            details={"reconciliation_complete": True},
        )
        repo.finish_run(run, status="success", finished_at=103.0)

    assert not (tmp_path / cfg.log_dir / cfg.manifest_filename).exists()
    payload = query_target(f"source:{source.id}", cfg=cfg)
    assert payload["repository_backed"] is True
    assert payload["manifest_entry"]["complete"] is True
    assert payload["manifest_entry"]["reconciliation_complete"] is True

    with Repository(tmp_path) as repo:
        rows = source_status_rows_from_repository(repo, cfg)
    assert rows[0]["status"] == "ok"
    assert rows[0]["details"]["complete"] is True
    assert rows[0]["details"]["reconciliation_complete"] is True
