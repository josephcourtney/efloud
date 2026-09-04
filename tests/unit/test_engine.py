import asyncio
from pathlib import Path

import pytest

import efloud.engine as engine_module
import efloud.repository_recording as recording_module
from efloud.engine import Engine
from efloud.models import EngineConfig, SyncResult
from efloud.registry import SourceDefinition, SourceKind
from efloud.transport.rsync_inventory import RsyncInventory, RsyncInventoryEntry

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
                                "etag": '"v1"',
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
        assert observation.upstream_version == '"v1"'
        with engine.repository.open_content(observation.content_id) as stream:
            assert stream.read() == b"payload"
        snapshot = engine.repository.latest_source_snapshot("example")
        assert snapshot is not None
        assert snapshot.complete
        assert snapshot.evidence["status_code"] == 200


def test_engine_leaves_missing_rsync_result_unrecorded(
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


def test_engine_falls_back_to_rsync_delta_when_inventory_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror_root = tmp_path / "mirrors" / "mirror"
    changed = mirror_root / "aa" / "entry.txt"
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"version one")
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
                "results": {
                    "http": {},
                    "rsync": {
                        "mirror": {
                            "ok": True,
                            "local": str(mirror_root),
                            "request": {"paths": ["aa/"]},
                            "results": {
                                "aa/": {
                                    "status": "success",
                                    "updated": ["aa/entry.txt"],
                                }
                            },
                        }
                    },
                    "derived": {},
                },
                "errors": [],
            },
        )

    monkeypatch.setattr(engine_module, "legacy_sync", fake_sync)
    monkeypatch.setattr(
        recording_module,
        "enumerate_rsync",
        lambda _cfg, *, scope=(): RsyncInventory(
            entries=(),
            scope=scope,
            complete=False,
            error="offline",
        ),
    )
    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())
        assert result.skipped_source_ids == ()
        observation = engine.repository.latest_observation("source:mirror:path:aa/entry.txt")
        assert observation is not None
        assert observation.source_path == "aa/entry.txt"
        with engine.repository.open_content(observation.content_id) as stream:
            assert stream.read() == b"version one"
        snapshot = engine.repository.latest_source_snapshot("mirror")
        assert snapshot is not None
        assert snapshot.complete is False
        assert snapshot.scope == ("aa/",)
        assert snapshot.evidence["reconciliation_complete"] is False
        assert snapshot.evidence["inventory_error"] == "offline"
        assert snapshot.tree_id is not None
        assert engine.repository.tree_entries(snapshot.tree_id)[0].relative_path == "aa/entry.txt"


def test_engine_authoritatively_records_rsync_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror_root = tmp_path / "mirrors" / "mirror"
    materialized = mirror_root / "aa" / "entry.txt"
    materialized.parent.mkdir(parents=True)
    materialized.write_bytes(b"version one")
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
                "results": {
                    "http": {},
                    "rsync": {
                        "mirror": {
                            "ok": True,
                            "local": str(mirror_root),
                            "request": {"paths": None},
                            "results": {"update": {"status": "success", "updated": ["aa/entry.txt"]}},
                        }
                    },
                    "derived": {},
                },
                "errors": [],
            },
        )

    monkeypatch.setattr(engine_module, "legacy_sync", fake_sync)
    monkeypatch.setattr(
        recording_module,
        "enumerate_rsync",
        lambda _cfg, *, scope=(): RsyncInventory(
            entries=(
                RsyncInventoryEntry(
                    "aa/entry.txt",
                    "file",
                    len(b"version one"),
                    "2026/09/04 10:00:00",
                ),
            ),
            scope=scope,
            complete=True,
        ),
    )

    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())
        assert len(result.observations) == 1
        observation = engine.repository.latest_observation("source:mirror:path:aa/entry.txt")
        assert observation is not None
        snapshot = engine.repository.latest_source_snapshot("mirror")
        assert snapshot is not None
        assert snapshot.complete is True
        assert snapshot.evidence["reconciliation_complete"] is True
        assert snapshot.evidence["inventory_entry_count"] == 1


def test_engine_does_not_infer_rsync_deletion_when_inventory_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror_root = tmp_path / "mirrors" / "mirror"
    mirror_root.mkdir(parents=True)
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
                "results": {
                    "http": {},
                    "rsync": {
                        "mirror": {
                            "ok": True,
                            "local": str(mirror_root),
                            "request": {"paths": None},
                            "results": {
                                "update": {
                                    "status": "success",
                                    "updated": ["deleting stale.txt"],
                                }
                            },
                        }
                    },
                    "derived": {},
                },
                "errors": [],
            },
        )

    monkeypatch.setattr(engine_module, "legacy_sync", fake_sync)
    monkeypatch.setattr(
        recording_module,
        "enumerate_rsync",
        lambda _cfg, *, scope=(): RsyncInventory(
            entries=(),
            scope=scope,
            complete=False,
            error="offline",
        ),
    )
    with Engine.from_config(config) as engine:
        asyncio.run(engine.sync())
        assert engine.repository.latest_state("source:mirror:path:stale.txt") is None
        snapshot = engine.repository.latest_source_snapshot("mirror")
        assert snapshot is not None
        assert snapshot.complete is False
