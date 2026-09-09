from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from efloud.adapters import HttpAcquisition, RsyncAcquisition
from efloud.compat.outputs import project_execution
from efloud.engine import Engine
from efloud.http_adapter import HttpSourceAdapter
from efloud.models import EngineConfig
from efloud.registry import SourceDefinition, SourceKind
from efloud.rsync_adapter import RsyncSourceAdapter
from efloud.transport.rsync_inventory import RsyncInventory, RsyncInventoryEntry

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]
if TYPE_CHECKING:
    from pathlib import Path


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

    async def fake_acquire(self, context):
        del self, context
        await asyncio.sleep(0)
        return HttpAcquisition(
            source_id="http",
            status="succeeded",
            destination=materialized,
            observed_at=101.0,
            status_code=200,
            etag='"v1"',
            media_type="application/json",
        )

    monkeypatch.setattr(HttpSourceAdapter, "acquire", fake_acquire)
    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())
        outputs = project_execution(engine.repository, config=engine.config, result=result)
        assert outputs.repository_manifest is not None
        assert outputs.manifest is outputs.repository_manifest
        assert outputs.legacy_manifest is outputs.sync_result.manifest
        assert outputs.manifest["results"]["http"]["http"]["repository_backed"] is True
        assert outputs.repository_manifest_path is not None
        persisted = json.loads(outputs.repository_manifest_path.read_text(encoding="utf-8"))
        assert persisted == outputs.manifest
        assert outputs.repository_mirror_state is None
        assert outputs.repository_mirror_state_path is None
        assert result.repository_run_id == result.execution.run_id
        assert result.plan.operation("source:http").producer.producer_id == "efloud:rest"


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

    async def fake_acquire(self, context):
        del self, context
        await asyncio.sleep(0)
        return RsyncAcquisition(
            source_id="mirror",
            status="succeeded",
            local_root=mirror_root,
            scope=(),
            observed_at=101.0,
            inventory=RsyncInventory(
                entries=(
                    RsyncInventoryEntry(
                        "aa/entry.txt",
                        "file",
                        len(b"version one"),
                        "2026/09/04 10:00:00",
                    ),
                ),
                scope=(),
                complete=True,
            ),
        )

    monkeypatch.setattr(RsyncSourceAdapter, "acquire", fake_acquire)
    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())
        outputs = project_execution(engine.repository, config=engine.config, result=result)
        assert outputs.repository_mirror_state is not None
        assert outputs.repository_mirror_state_path is not None
        assert outputs.repository_mirror_state_path.is_file()
        assert outputs.repository_mirror_state.sources[0].source_id == "mirror"


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

    async def fake_acquire(self, context):
        del self, context
        await asyncio.sleep(0)
        return RsyncAcquisition(
            source_id="mirror",
            status="succeeded",
            local_root=mirror_root,
            scope=("aa/",),
            observed_at=101.0,
            inventory=RsyncInventory(
                entries=(
                    RsyncInventoryEntry(
                        "aa/entry.txt",
                        "file",
                        len(b"version one"),
                        "2026/09/04 10:00:00",
                    ),
                ),
                scope=("aa/",),
                complete=True,
            ),
        )

    monkeypatch.setattr(RsyncSourceAdapter, "acquire", fake_acquire)
    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())
        outputs = project_execution(engine.repository, config=engine.config, result=result)
        assert outputs.repository_mirror_state is None
        assert outputs.repository_mirror_state_path is None
        assert state_path.read_text(encoding="utf-8") == '{"legacy":true}'
