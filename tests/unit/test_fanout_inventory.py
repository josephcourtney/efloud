from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

from efloud.fanout import (
    FanoutEnumeration,
    FanoutItem,
    RestBaseFanoutTask,
    fanout_source_inventory,
    normalize_fanout_enumeration,
)
from efloud.inventory import ChangeToken, IntegrityExpectation, InventoryCoverage
from efloud.reconciliation import PreviousInventoryItem, reconcile_inventory
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository_models import ArtifactKey, ContentId, SourceId

fanout_mod = importlib.import_module("efloud.fanout")

pytestmark = [pytest.mark.unit, pytest.mark.small]


def test_sequence_enumerator_results_remain_complete_by_default() -> None:
    enumeration = normalize_fanout_enumeration([FanoutItem("alpha"), FanoutItem("beta")])
    assert enumeration.complete is True
    assert tuple(item.item_id for item in enumeration.items) == ("alpha", "beta")


def test_partial_fanout_inventory_cannot_establish_absence() -> None:
    enumeration = FanoutEnumeration(
        items=(FanoutItem("alpha"),),
        complete=False,
        upstream_identity="page-1-of-many",
    )
    inventory = fanout_source_inventory(
        source_id="collection",
        base_url="https://api.example.test/items",
        enumeration=enumeration,
        observed_at=10.0,
    )
    previous = (
        PreviousInventoryItem(
            item_id="alpha",
            artifact_key=ArtifactKey("source:collection:item:alpha"),
            content_id=ContentId(f"sha256:{'a' * 64}"),
        ),
        PreviousInventoryItem(
            item_id="beta",
            artifact_key=ArtifactKey("source:collection:item:beta"),
            content_id=ContentId(f"sha256:{'b' * 64}"),
        ),
    )

    reconciliation = reconcile_inventory(inventory, previous)
    assert inventory.coverage == InventoryCoverage(complete=False)
    assert inventory.upstream_identity == "page-1-of-many"
    assert reconciliation.by_state("absent") == ()


def test_fanout_inventory_preserves_change_and_integrity_evidence() -> None:
    token = ChangeToken("api-revision", "17", reliability="strong")
    expectation = IntegrityExpectation.sha256("c" * 64)
    inventory = fanout_source_inventory(
        source_id=SourceId("collection"),
        base_url="https://api.example.test/items",
        enumeration=FanoutEnumeration(
            items=(
                FanoutItem(
                    "alpha",
                    request_path="records/alpha",
                    change_token=token,
                    expected_integrity=(expectation,),
                ),
            ),
            complete=True,
            upstream_identity="catalog-17",
        ),
        observed_at=10.0,
    )

    item = inventory.items[0]
    assert item.artifact_key == ArtifactKey("source:collection:item:alpha")
    assert item.locator == "https://api.example.test/items/records/alpha"
    assert item.change_token == token
    assert item.expected_integrity == (expectation,)


def test_duplicate_fanout_item_ids_are_rejected_at_enumeration_boundary() -> None:
    with pytest.raises(ValueError, match="duplicate item identifiers"):
        FanoutEnumeration(items=(FanoutItem("alpha"), FanoutItem("alpha")))


@pytest.mark.asyncio
async def test_fanout_task_serializes_inventory_independently_of_retrieval_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = ChangeToken("api-revision", "17", reliability="strong")

    async def enumerator(*, sync_root, manifest, sources):
        del manifest, sources
        assert sync_root == tmp_path
        await asyncio.sleep(0)
        return FanoutEnumeration(
            items=(FanoutItem("alpha", change_token=token), FanoutItem("beta")),
            complete=False,
            upstream_identity="catalog-page-1",
        )

    async def fake_materialize_fanout(**kwargs):
        assert tuple(item.item_id for item in kwargs["items"]) == ("alpha", "beta")
        await asyncio.sleep(0)
        return {"alpha": {"status": "ok"}}

    class FakeHttpCache:
        def __init__(self, config):
            self.config = config

        async def aclose(self) -> None:
            await asyncio.sleep(0)

    monkeypatch.setattr(fanout_mod, "HttpCache", FakeHttpCache)
    monkeypatch.setattr(fanout_mod, "_materialize_fanout", fake_materialize_fanout)

    source = SourceDefinition(
        "collection",
        "Collection",
        "https://api.example.test/items",
        SourceKind.REST_BASE,
    )
    task = RestBaseFanoutTask(
        name="fanout",
        source_id=source.id,
        base_url="https://api.example.test/items",
        enumerator=enumerator,
        dest_subdir="fanout",
    )
    payload = await task.run(
        sync_root=tmp_path,
        manifest={
            "results": {"http": {}, "rsync": {}, "derived": {}},
            "errors": [],
            "root": str(tmp_path),
            "version": 1,
        },
        sources=(source,),
    )

    inventory = payload["inventory"]
    assert isinstance(inventory, dict)
    assert inventory["source_id"] == "collection"
    assert inventory["coverage"] == {"scope": [], "complete": False}
    items = inventory["items"]
    assert isinstance(items, list)
    assert [item["item_id"] for item in items] == ["alpha", "beta"]
    assert items[0]["change_token"] == token.to_dict()
    assert payload["enumeration"] == {
        "complete": False,
        "item_count": 2,
        "model": "source-inventory-v1",
        "upstream_identity": "catalog-page-1",
    }
    assert payload["entries"] == {"alpha": {"status": "ok"}}
