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

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


async def _unused_enumerator(*, context):
    del context
    await asyncio.sleep(0)
    return []


def test_collection_history_survives_deleted_materialization_and_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materialized = tmp_path / "collection" / "alpha.json"
    materialized.parent.mkdir(parents=True)
    materialized.write_text('{"id":"alpha"}', encoding="utf-8")

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
        observed_at=10.0,
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
            observed_at=10.0,
            inventory=inventory,
            items=(
                CollectionItemAcquisition(
                    item_id="alpha",
                    status="ok",
                    destination=materialized,
                ),
            ),
            media_type="application/json",
        )

    monkeypatch.setattr(CollectionSourceAdapter, "acquire", fake_acquire)

    with Repository(tmp_path) as repository:
        result = asyncio.run(Engine(repository, (source,), collections=(definition,)).sync())
        assert result.ok
        observation = repository.latest_observation("source:collection:item:alpha")
        snapshot = repository.latest_source_snapshot(source.id)
        assert observation is not None
        assert snapshot is not None
        content_id = observation.content_id
        snapshot_id = snapshot.snapshot_id

    materialized.unlink()

    with Repository(tmp_path) as reopened:
        observation = reopened.latest_observation("source:collection:item:alpha")
        snapshot = reopened.latest_source_snapshot(source.id)
        assert observation is not None
        assert observation.content_id == content_id
        assert snapshot is not None
        assert snapshot.snapshot_id == snapshot_id
        with reopened.open_content(content_id) as stream:
            assert stream.read() == b'{"id":"alpha"}'
