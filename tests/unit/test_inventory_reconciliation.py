from __future__ import annotations

import pytest

from efloud.inventory import (
    ChangeToken,
    IntegrityExpectation,
    IntegrityExpectationError,
    InventoryCoverage,
    InventoryItem,
    SourceInventory,
    require_integrity,
)
from efloud.reconciliation import PreviousInventoryItem, reconcile_inventory
from efloud.repository_models import ArtifactKey, ContentId, ContentRef, SourceId
from efloud.transport.http_inventory import http_source_inventory
from efloud.transport.rsync_inventory import (
    RsyncInventory,
    RsyncInventoryEntry,
    rsync_source_inventory,
)

pytestmark = [pytest.mark.unit]


def _item(
    item_id: str,
    *,
    token: ChangeToken | None = None,
    source_path: str | None = None,
) -> InventoryItem:
    return InventoryItem(
        item_id=item_id,
        artifact_key=ArtifactKey(f"artifact:{item_id}"),
        source_path=source_path,
        change_token=token,
    )


def _previous(
    item_id: str,
    *,
    token: ChangeToken | None = None,
    source_path: str | None = None,
) -> PreviousInventoryItem:
    return PreviousInventoryItem(
        item_id=item_id,
        artifact_key=ArtifactKey(f"artifact:{item_id}"),
        content_id=ContentId(f"sha256:{item_id:0<64}"),
        source_path=source_path,
        change_token=token,
    )


@pytest.mark.small
def test_complete_inventory_classifies_new_changed_unchanged_and_absent() -> None:
    same = ChangeToken("revision", "7", reliability="strong")
    old = ChangeToken("revision", "1", reliability="strong")
    new = ChangeToken("revision", "2", reliability="strong")
    inventory = SourceInventory(
        source_id=SourceId("source"),
        observed_at=10.0,
        coverage=InventoryCoverage(complete=True),
        items=(
            _item("new", token=new),
            _item("changed", token=new),
            _item("same", token=same),
        ),
    )
    result = reconcile_inventory(
        inventory,
        (
            _previous("changed", token=old),
            _previous("same", token=same),
            _previous("gone", token=old),
        ),
    )

    assert result.counts() == {"new": 1, "changed": 1, "unchanged": 1, "absent": 1}
    same_decision = result.decision_for("same")
    gone_decision = result.decision_for("gone")
    assert same_decision is not None and same_decision.state == "unchanged"
    assert gone_decision is not None and gone_decision.state == "absent"


@pytest.mark.small
def test_incomplete_inventory_never_infers_absence() -> None:
    inventory = SourceInventory(
        source_id=SourceId("source"),
        observed_at=10.0,
        coverage=InventoryCoverage(complete=False),
        items=(),
    )
    result = reconcile_inventory(inventory, (_previous("missing"),))
    assert result.by_state("absent") == ()


@pytest.mark.small
def test_complete_scoped_inventory_only_infers_absence_inside_known_scope() -> None:
    inventory = SourceInventory(
        source_id=SourceId("source"),
        observed_at=10.0,
        coverage=InventoryCoverage(scope=("aa/",), complete=True),
        items=(),
    )
    result = reconcile_inventory(
        inventory,
        (
            _previous("inside", source_path="aa/inside.dat"),
            _previous("outside", source_path="bb/outside.dat"),
            _previous("unknown-location"),
        ),
    )
    assert tuple(decision.item_id for decision in result.by_state("absent")) == ("inside",)


@pytest.mark.small
def test_weak_change_evidence_does_not_authorize_content_reuse() -> None:
    weak = ChangeToken("http-last-modified", "yesterday", reliability="weak")
    inventory = SourceInventory(
        source_id=SourceId("source"),
        observed_at=10.0,
        coverage=InventoryCoverage(),
        items=(_item("item", token=weak),),
    )
    result = reconcile_inventory(inventory, (_previous("item", token=weak),))
    decision = result.decision_for("item")
    assert decision is not None and decision.state == "changed"


@pytest.mark.small
def test_http_resource_uses_normalized_inventory_and_keeps_etag_out_of_content_identity() -> None:
    inventory = http_source_inventory(
        source_id="http-source",
        artifact_key="source:http-source",
        url="https://example.test/data.json",
        observed_at=10.0,
        etag='"revision-7"',
        expected_sha256="a" * 64,
        status_code=200,
    )
    item = inventory.items[0]
    assert inventory.coverage.complete
    assert item.change_token is not None
    assert item.change_token == ChangeToken("http-etag", '"revision-7"', reliability="strong")
    assert item.expected_integrity[0].expected_content_id == ContentId(f"sha256:{'a' * 64}")
    assert item.change_token.value != str(item.expected_integrity[0].expected_content_id)


@pytest.mark.small
def test_rsync_inventory_converts_to_same_normalized_inventory_model() -> None:
    inventory = rsync_source_inventory(
        RsyncInventory(
            entries=(
                RsyncInventoryEntry(
                    relative_path="aa/file.dat",
                    kind="file",
                    byte_size=12,
                    modified="2026/09/04 12:00:00",
                ),
            ),
            scope=("aa/",),
            complete=True,
        ),
        source_id="mirror",
        observed_at=10.0,
        upstream_root="rsync.example::data",
    )
    item = inventory.items[0]
    assert isinstance(inventory, SourceInventory)
    assert inventory.coverage == InventoryCoverage(scope=("aa/",), complete=True)
    assert item.artifact_key == ArtifactKey("source:mirror:path:aa/file.dat")
    assert item.change_token is not None
    assert item.change_token.kind == "rsync-list-state"


@pytest.mark.small
def test_collection_enumeration_uses_normalized_inventory_without_special_reconciliation() -> None:
    inventory = SourceInventory(
        source_id=SourceId("collection"),
        observed_at=10.0,
        coverage=InventoryCoverage(complete=True),
        items=(
            InventoryItem(
                item_id="42",
                artifact_key=ArtifactKey("source:collection:item:42"),
                locator="https://example.test/items/42",
                change_token=ChangeToken("api-version", "v3", reliability="strong"),
            ),
        ),
        upstream_identity="page-set:v3",
        metadata={"transport": "synthetic-collection"},
    )
    result = reconcile_inventory(inventory)
    assert result.counts() == {"new": 1, "changed": 0, "unchanged": 0, "absent": 0}


@pytest.mark.small
def test_integrity_expectation_is_checked_against_independently_computed_content_id() -> None:
    actual = ContentRef(
        content_id=ContentId(f"sha256:{'a' * 64}"),
        byte_size=3,
        storage_key="sha256/aa/actual",
    )
    checks = require_integrity(actual, (IntegrityExpectation.sha256("a" * 64),))
    assert checks[0].ok
    assert checks[0].actual_content_id == actual.content_id

    with pytest.raises(IntegrityExpectationError):
        require_integrity(actual, (IntegrityExpectation.sha256("b" * 64),))
