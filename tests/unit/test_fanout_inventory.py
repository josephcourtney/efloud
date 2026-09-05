from __future__ import annotations

import pytest

from efloud.fanout import (
    FanoutEnumeration,
    FanoutItem,
    fanout_source_inventory,
    normalize_fanout_enumeration,
)
from efloud.inventory import ChangeToken, IntegrityExpectation, InventoryCoverage
from efloud.reconciliation import PreviousInventoryItem, reconcile_inventory
from efloud.repository_models import ArtifactKey, ContentId, SourceId

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
