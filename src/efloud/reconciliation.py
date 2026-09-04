from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from efloud.inventory import ChangeToken, InventoryItem, SourceInventory
    from efloud.json_types import JsonObject
    from efloud.repository_models import ArtifactKey, ContentId

ReconciliationState = Literal["new", "changed", "unchanged", "absent"]


@dataclass(frozen=True, slots=True)
class PreviousInventoryItem:
    """Repository-backed baseline for protocol-independent reconciliation."""

    item_id: str
    artifact_key: ArtifactKey
    content_id: ContentId | None = None
    source_path: str | None = None
    change_token: ChangeToken | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    state: ReconciliationState
    item_id: str
    artifact_key: ArtifactKey
    current: InventoryItem | None
    previous: PreviousInventoryItem | None
    reason: str

    @property
    def content_id(self) -> ContentId | None:
        return None if self.previous is None else self.previous.content_id


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    inventory: SourceInventory
    decisions: tuple[ReconciliationDecision, ...]

    def by_state(self, state: ReconciliationState) -> tuple[ReconciliationDecision, ...]:
        return tuple(decision for decision in self.decisions if decision.state == state)

    def decision_for(self, item_id: str) -> ReconciliationDecision | None:
        return next((decision for decision in self.decisions if decision.item_id == item_id), None)

    def counts(self) -> dict[ReconciliationState, int]:
        return {
            "new": len(self.by_state("new")),
            "changed": len(self.by_state("changed")),
            "unchanged": len(self.by_state("unchanged")),
            "absent": len(self.by_state("absent")),
        }


def _previous_map(previous_items: tuple[PreviousInventoryItem, ...]) -> dict[str, PreviousInventoryItem]:
    item_ids = [item.item_id for item in previous_items]
    if len(set(item_ids)) != len(item_ids):
        msg = "Reconciliation baseline contains duplicate item identifiers."
        raise ValueError(msg)
    return {item.item_id: item for item in previous_items}


def _classify_present(
    current: InventoryItem,
    previous: PreviousInventoryItem | None,
) -> ReconciliationDecision:
    if previous is None:
        return ReconciliationDecision(
            state="new",
            item_id=current.item_id,
            artifact_key=current.artifact_key,
            current=current,
            previous=None,
            reason="item was not present in the repository baseline",
        )
    if previous.artifact_key != current.artifact_key:
        msg = (
            f"Inventory item {current.item_id!r} changed logical artifact identity from "
            f"{previous.artifact_key!s} to {current.artifact_key!s}."
        )
        raise ValueError(msg)
    if current.change_token is not None and current.change_token.equivalent_to(previous.change_token):
        return ReconciliationDecision(
            state="unchanged",
            item_id=current.item_id,
            artifact_key=current.artifact_key,
            current=current,
            previous=previous,
            reason="strong source change token matches repository baseline",
        )
    return ReconciliationDecision(
        state="changed",
        item_id=current.item_id,
        artifact_key=current.artifact_key,
        current=current,
        previous=previous,
        reason="no trustworthy matching change evidence is available",
    )


def _absent_decisions(
    inventory: SourceInventory,
    current_ids: set[str],
    previous_items: tuple[PreviousInventoryItem, ...],
) -> tuple[ReconciliationDecision, ...]:
    if not inventory.coverage.complete:
        return ()
    decisions: list[ReconciliationDecision] = []
    for previous in previous_items:
        if previous.item_id in current_ids:
            continue
        if not inventory.coverage.contains(previous.source_path):
            continue
        decisions.append(
            ReconciliationDecision(
                state="absent",
                item_id=previous.item_id,
                artifact_key=previous.artifact_key,
                current=None,
                previous=previous,
                reason="complete inventory coverage omitted a previously observed item",
            )
        )
    return tuple(decisions)


def reconcile_inventory(
    inventory: SourceInventory,
    previous_items: tuple[PreviousInventoryItem, ...] = (),
) -> ReconciliationResult:
    """Classify normalized source inventory without protocol-specific repository logic."""

    previous_by_id = _previous_map(previous_items)
    decisions = [
        _classify_present(current, previous_by_id.get(current.item_id))
        for current in sorted(inventory.items, key=lambda item: item.item_id)
    ]
    current_ids = {item.item_id for item in inventory.items}
    decisions.extend(_absent_decisions(inventory, current_ids, previous_items))
    decisions.sort(key=lambda decision: (decision.item_id, decision.state))
    return ReconciliationResult(inventory=inventory, decisions=tuple(decisions))


__all__ = [
    "PreviousInventoryItem",
    "ReconciliationDecision",
    "ReconciliationResult",
    "ReconciliationState",
    "reconcile_inventory",
]
