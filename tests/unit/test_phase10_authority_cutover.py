from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

import efloud.engine as engine_module
from efloud.adoption import adopt_existing_store
from efloud.engine import Engine
from efloud.models import EngineConfig, SyncResult
from efloud.query import query_target
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_models import SourceId
from efloud.status import collect_status_payload
from efloud.transport.http_utils import dest_for_http_source

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def _http_source(source_id: str) -> SourceDefinition:
    return SourceDefinition(
        source_id,
        source_id.upper(),
        f"https://example.test/{source_id}.json",
        SourceKind.REST,
    )


def _record_http_source(
    repository: Repository,
    *,
    source: SourceDefinition,
    path: Path,
    started_at: float,
):
    repository.register_source(SourceId(source.id), {"kind": source.kind.value, "url": source.url})
    run_id = repository.start_run(source_ids=(source.id,), started_at=started_at)
    operation_id = repository.start_operation(
        run_id=run_id,
        source_id=source.id,
        kind="rest",
        subject=source.id,
        started_at=started_at,
    )
    observation = repository.ingest_path(
        f"source:{source.id}",
        path,
        run_id=run_id,
        operation_id=operation_id,
        source_id=source.id,
        observed_at=started_at + 1,
        upstream_locator=source.url,
        media_type="application/json",
        materialization_kind="compatibility-http",
    )
    repository.record_source_snapshot(
        source_id=source.id,
        run_id=run_id,
        complete=True,
        observed_at=started_at + 1,
        evidence={"status_code": 200},
    )
    repository.finish_operation(operation_id, status="succeeded", finished_at=started_at + 2)
    repository.finish_run(run_id, status="succeeded", finished_at=started_at + 3)
    return observation


def test_targeted_engine_sync_preserves_untouched_state_without_manifest_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_a = _http_source("a")
    source_b = _http_source("b")
    config = EngineConfig(root=tmp_path, sources=[source_a, source_b])

    b_path = tmp_path / "retained-b.json"
    b_path.write_text('{"value":"b"}', encoding="utf-8")
    with Repository(tmp_path) as repository:
        b_observation = _record_http_source(
            repository,
            source=source_b,
            path=b_path,
            started_at=10.0,
        )

    canonical = tmp_path / config.log_dir / config.manifest_filename
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text('{"poisoned":true}', encoding="utf-8")

    a_path = tmp_path / "retained-a.json"
    a_path.write_text('{"value":"a"}', encoding="utf-8")

    async def fake_acquire(_config: EngineConfig) -> SyncResult:
        await asyncio.sleep(0)
        return SyncResult(
            ok=True,
            root=tmp_path,
            manifest_path=None,
            manifest={
                "version": 1,
                "root": str(tmp_path),
                "results": {
                    "http": {
                        "a": {
                            "ok": True,
                            "dest": str(a_path),
                            "freshness": {"fetched_at_unix": 101.0, "status_code": 200},
                        }
                    },
                    "rsync": {},
                    "derived": {},
                },
                "errors": [],
            },
        )

    monkeypatch.setattr(engine_module, "legacy_sync", fake_acquire)
    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())

    assert set(result.manifest["results"]["http"]) == {"a", "b"}
    assert result.manifest["results"]["http"]["b"]["content_id"] == str(b_observation.content_id)
    assert json.loads(canonical.read_text(encoding="utf-8")) == result.manifest

    timestamped = list((tmp_path / config.log_dir).glob("sync-manifest-*.json"))
    assert len(timestamped) == 1
    assert json.loads(timestamped[0].read_text(encoding="utf-8")) == result.manifest

    canonical.unlink()
    timestamped[0].unlink()
    source_payload = query_target("source:b", cfg=config)
    status_payload, warnings = collect_status_payload(config)
    assert source_payload["repository_entry"]["content_id"] == str(b_observation.content_id)
    assert status_payload["health"]["http_results"]["b"]["content_id"] == str(b_observation.content_id)
    assert warnings == []


def test_uninitialized_queries_do_not_use_compatibility_files_as_state(tmp_path: Path) -> None:
    source = _http_source("legacy")
    config = EngineConfig(root=tmp_path, sources=[source])
    log_dir = tmp_path / config.log_dir
    log_dir.mkdir(parents=True)
    (log_dir / config.manifest_filename).write_text(
        json.dumps({
            "version": 1,
            "root": str(tmp_path),
            "results": {
                "http": {"legacy": {"ok": True, "dest": "/claimed/by/legacy.json"}},
                "rsync": {},
                "derived": {},
            },
            "errors": [],
        }),
        encoding="utf-8",
    )
    (tmp_path / config.state_filename).write_text('{"legacy":true}', encoding="utf-8")

    source_payload = query_target("source:legacy#/value", cfg=config)
    status_payload, warnings = collect_status_payload(config)

    assert source_payload["repository_status"] == "uninitialized"
    assert source_payload["manifest_entry"] is None
    assert source_payload["locator"]["value"] is None
    assert status_payload["repository_status"] == "uninitialized"
    assert status_payload["health"]["http_results"] == {}
    assert warnings


def test_adoption_observes_retained_local_bytes_without_claiming_source_history(tmp_path: Path) -> None:
    http_source = _http_source("http")
    rsync_source = SourceDefinition(
        "mirror",
        "Mirror",
        "rsync://example.test/module",
        SourceKind.RSYNC,
        local_subpath="mirror",
    )
    config = EngineConfig(root=tmp_path, sources=[http_source, rsync_source])

    http_path = dest_for_http_source(
        tmp_path / config.http_dir,
        url=http_source.url,
        description=http_source.description,
        kind=http_source.kind.value,
        cache_name=http_source.cache_name,
    )
    http_path.parent.mkdir(parents=True)
    http_path.write_text('{"retained":true}', encoding="utf-8")
    mirror_path = tmp_path / config.mirrors_dir / "mirror" / "aa" / "entry.dat"
    mirror_path.parent.mkdir(parents=True)
    mirror_path.write_bytes(b"retained mirror bytes")

    log_dir = tmp_path / config.log_dir
    log_dir.mkdir(parents=True)
    (log_dir / config.manifest_filename).write_text('{"claims":"ignored"}', encoding="utf-8")
    (tmp_path / config.state_filename).write_text('{"claims":"ignored"}', encoding="utf-8")

    with Repository(tmp_path) as repository:
        first = adopt_existing_store(repository, cfg=config, observed_at=100.0)
        assert first.ok
        assert len(first.observations) == 2
        assert repository.latest_observation("source:http") is None
        assert repository.latest_source_snapshot("http") is None
        assert repository.latest_source_snapshot("mirror") is None

        for observation_id in first.observations:
            observation = repository.observation(observation_id)
            assert observation is not None
            assert observation.source_id is None
            assert observation.upstream_locator is None
            assert observation.metadata["adoption"] is True
            assert observation.metadata["historical_provenance_known"] is False

        second = adopt_existing_store(repository, cfg=config, observed_at=200.0)
        assert second.ok
        assert second.observations == ()
        assert len(second.unchanged_artifacts) == 2

    assert http_path.is_file()
    assert mirror_path.is_file()
