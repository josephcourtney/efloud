import asyncio
from pathlib import Path

import pytest

import efloud.engine as engine_module
from efloud.engine import Engine
from efloud.models import EngineConfig, SyncResult
from efloud.registry import SourceDefinition, SourceKind

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression]


def test_engine_dual_records_http_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    materialized = tmp_path / "http" / "data.txt"
    materialized.parent.mkdir(parents=True)
    materialized.write_bytes(b"payload")
    source = SourceDefinition(
        id="example",
        description="Example",
        url="https://example.test/data.txt",
        kind=SourceKind.HTTP,
    )
    config = EngineConfig(root=tmp_path, sources=[source])

    async def fake_sync(_config: EngineConfig) -> SyncResult:
        return SyncResult(
            ok=True,
            root=tmp_path,
            manifest_path=None,
            manifest={
                "version": 1,
                "root": str(tmp_path),
                "results": {
                    "http": {
                        "example": {
                            "ok": True,
                            "dest": str(materialized),
                            "freshness": {
                                "fetched_at_unix": 123.0,
                                "status_code": 200,
                                "etag": "\"v1\"",
                            },
                        }
                    },
                    "rsync": {},
                    "derived": {},
                },
                "errors": [],
            },
        )

    monkeypatch.setattr(engine_module, "legacy_sync", fake_sync)
    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())
        assert result.ok
        assert len(result.observations) == 1
        observation = engine.repository.latest_observation("source:example")
        assert observation is not None
        assert observation.observed_at == 123.0
        assert observation.upstream_version == "\"v1\""
        with engine.repository.open_content(observation.content_id) as stream:
            assert stream.read() == b"payload"
        snapshot = engine.repository.latest_source_snapshot("example")
        assert snapshot is not None
        assert snapshot.complete
        assert snapshot.evidence["status_code"] == 200


def test_engine_leaves_rsync_for_incremental_tree_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SourceDefinition(
        id="mirror",
        description="Mirror",
        url="rsync://example.test/module",
        kind=SourceKind.RSYNC,
        local_subpath="mirror",
    )
    config = EngineConfig(root=tmp_path, sources=[source])

    async def fake_sync(_config: EngineConfig) -> SyncResult:
        return SyncResult(
            ok=True,
            root=tmp_path,
            manifest_path=None,
            manifest={
                "version": 1,
                "root": str(tmp_path),
                "results": {"http": {}, "rsync": {}, "derived": {}},
                "errors": [],
            },
        )

    monkeypatch.setattr(engine_module, "legacy_sync", fake_sync)
    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())
        assert result.skipped_source_ids == ("mirror",)
        assert engine.repository.artifact_keys() == ()
