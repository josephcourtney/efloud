from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import efloud.engine as engine_module
import efloud.repository_recording as recording_module
from efloud.engine import Engine
from efloud.models import EngineConfig, SyncResult
from efloud.registry import SourceDefinition, SourceKind
from efloud.transport.rsync_inventory import RsyncInventory, RsyncInventoryEntry

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression]


def test_engine_manifest_property_and_canonical_file_are_repository_derived(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materialized = tmp_path / "http" / "data.json"
    materialized.parent.mkdir(parents=True)
    materialized.write_text('{"value":1}', encoding="utf-8")
    source = SourceDefinition(
        "http",
        "HTTP",
        "https://example.test/data.json",
        SourceKind.REST,
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
                        "http": {
                            "ok": True,
                            "dest": str(materialized),
                            "freshness": {
                                "fetched_at_unix": 101.0,
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
        assert result.repository_manifest is not None
        assert result.manifest is result.repository_manifest
        assert result.legacy_manifest is result.sync_result.manifest
        assert result.manifest["results"]["http"]["http"]["repository_backed"] is True
        assert result.repository_manifest_path is not None
        persisted = json.loads(result.repository_manifest_path.read_text(encoding="utf-8"))
        assert persisted == result.manifest
        assert result.repository_mirror_state is None
        assert result.repository_mirror_state_path is None


def test_engine_publishes_repository_mirror_state_after_complete_rsync_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror_root = tmp_path / "mirrors" / "mirror"
    materialized = mirror_root / "aa" / "entry.txt"
    materialized.parent.mkdir(parents=True)
    materialized.write_bytes(b"version one")
    source = SourceDefinition(
        "mirror",
        "Mirror",
        "rsync://example.test/module",
        SourceKind.RSYNC,
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
                                "update": {"status": "success", "updated": ["aa/entry.txt"]}
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
        assert result.repository_mirror_state is not None
        assert result.repository_mirror_state_path is not None
        assert result.repository_mirror_state_path.is_file()
        assert result.repository_mirror_state.sources[0].source_id == "mirror"


def test_engine_does_not_replace_mirror_state_from_partial_only_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror_root = tmp_path / "mirrors" / "mirror"
    materialized = mirror_root / "aa" / "entry.txt"
    materialized.parent.mkdir(parents=True)
    materialized.write_bytes(b"version one")
    state_path = tmp_path / "mirror-state.json"
    state_path.write_text('{"legacy":true}', encoding="utf-8")
    source = SourceDefinition(
        "mirror",
        "Mirror",
        "rsync://example.test/module",
        SourceKind.RSYNC,
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
                                "aa/": {"status": "success", "updated": ["aa/entry.txt"]}
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
        assert result.repository_mirror_state is None
        assert result.repository_mirror_state_path is None
        assert state_path.read_text(encoding="utf-8") == '{"legacy":true}'
