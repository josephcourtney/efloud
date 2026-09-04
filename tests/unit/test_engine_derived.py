from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import efloud.engine as engine_module
from efloud.engine import Engine
from efloud.fanout import RestBaseFanoutTask
from efloud.models import EngineConfig, SyncResult
from efloud.registry import SourceDefinition, SourceKind

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression]


async def _unused_enumerator(*, sync_root, manifest, sources):
    del sync_root, manifest, sources
    return []


def test_engine_records_rest_base_fanout_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item_path = tmp_path / "fanout" / "alpha.json"
    item_path.parent.mkdir(parents=True)
    item_path.write_text('{"id":"alpha"}', encoding="utf-8")

    source = SourceDefinition(
        "collection",
        "Collection",
        "https://api.example.test/items",
        SourceKind.REST_BASE,
    )
    task = RestBaseFanoutTask(
        name="fanout",
        source_id=source.id,
        base_url=source.url,
        enumerator=_unused_enumerator,
        dest_subdir="fanout",
    )
    config = EngineConfig(root=tmp_path, sources=[source], derived_tasks=(task,))

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
                    "rsync": {},
                    "derived": {
                        "fanout": {
                            "source_id": "collection",
                            "kind": "REST_BASE",
                            "request": {
                                "base_url": source.url,
                                "fanout_root": str(item_path.parent),
                                "response_mode": "json",
                            },
                            "enumeration": {"complete": True, "item_count": 1},
                            "entries": {
                                "alpha": {
                                    "status": "ok",
                                    "item_id": "alpha",
                                    "dest": str(item_path),
                                    "request": {
                                        "url": f"{source.url}/alpha",
                                        "fanout_path": "alpha.json",
                                    },
                                    "metadata": {},
                                }
                            },
                            "ok": 1,
                            "err": 0,
                        }
                    },
                },
                "errors": [],
            },
        )

    monkeypatch.setattr(engine_module, "legacy_sync", fake_sync)
    with Engine.from_config(config) as engine:
        result = asyncio.run(engine.sync())
        assert result.skipped_source_ids == ()
        item = engine.repository.latest_observation("source:collection:item:alpha")
        assert item is not None
        execution = engine.repository.latest_observation("derived:fanout:execution")
        assert execution is not None
        snapshot = engine.repository.latest_source_snapshot("collection")
        assert snapshot is not None
        assert snapshot.complete
