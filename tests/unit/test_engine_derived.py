from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from efloud.adapters import CollectionAcquisition
from efloud.collection_adapter import CollectionSourceAdapter
from efloud.engine import Engine
from efloud.fanout import RestBaseFanoutTask
from efloud.inventory import InventoryCoverage, InventoryItem, SourceInventory
from efloud.models import EngineConfig
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository_models import ArtifactKey, SourceId

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]
if TYPE_CHECKING:
    from pathlib import Path


async def _unused_enumerator(*, context):
    del context
    await asyncio.sleep(0)
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
    inventory = SourceInventory(
        source_id=SourceId(source.id),
        observed_at=101.0,
        coverage=InventoryCoverage(complete=True),
        items=(
            InventoryItem(
                item_id="alpha",
                artifact_key=ArtifactKey("source:collection:item:alpha"),
                locator=f"{source.url}/alpha",
                source_path="alpha.json",
            ),
        ),
    )

    async def fake_acquire(self, context):
        del self, context
        await asyncio.sleep(0)
        return CollectionAcquisition(
            source_id=source.id,
            status="succeeded",
            task_name="fanout",
            observed_at=101.0,
            payload={
                "source_id": source.id,
                "kind": "REST_BASE",
                "request": {
                    "base_url": source.url,
                    "fanout_root": str(item_path.parent),
                    "response_mode": "json",
                },
                "inventory": inventory.to_dict(),
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
            },
        )

    monkeypatch.setattr(CollectionSourceAdapter, "acquire", fake_acquire)
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
        assert result.repository_run_id is not None
        operation = engine.repository.metadata.operations_for_run(result.repository_run_id)[0]
        assert operation.producer.producer_id == "efloud:collection"
