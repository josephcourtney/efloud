from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from efloud.adapters import CollectionAcquisition, CollectionItemAcquisition
from efloud.collection_adapter import CollectionSourceAdapter
from efloud.collections import CollectionDefinition
from efloud.engine import Engine
from efloud.inventory import InventoryCoverage, InventoryItem, SourceInventory
from efloud.repository import Repository
from efloud.repository_models import ArtifactKey, SourceId
from efloud.sources import CollectionSource

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]
if TYPE_CHECKING:
    from pathlib import Path


async def _unused_enumerator(*, context):
    del context
    await asyncio.sleep(0)
    return []


def test_engine_records_collection_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item_path = tmp_path / "collection" / "alpha.json"
    item_path.parent.mkdir(parents=True)
    item_path.write_text('{"id":"alpha"}', encoding="utf-8")

    source = CollectionSource(
        id="collection",
        description="Collection",
        url="https://api.example.test/items",
    )
    definition = CollectionDefinition(
        source_id=source.id,
        enumerator=_unused_enumerator,
        dest_subdir="collection",
    )
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
            observed_at=101.0,
            inventory=inventory,
            items=(
                CollectionItemAcquisition(
                    item_id="alpha",
                    status="ok",
                    destination=item_path,
                ),
            ),
            media_type="application/json",
        )

    monkeypatch.setattr(CollectionSourceAdapter, "acquire", fake_acquire)
    with Repository(tmp_path) as repository:
        engine = Engine(repository, (source,), collections=(definition,))
        result = asyncio.run(engine.sync())
        assert result.skipped_source_ids == ()
        item = repository.latest_observation("source:collection:item:alpha")
        assert item is not None
        execution = repository.latest_observation("source:collection:collection-execution")
        assert execution is not None
        snapshot = repository.latest_source_snapshot("collection")
        assert snapshot is not None
        assert snapshot.complete
        assert result.repository_run_id is not None
        operation = repository.metadata.operations_for_run(result.repository_run_id)[0]
        assert operation.producer.producer_id == "efloud:collection"
