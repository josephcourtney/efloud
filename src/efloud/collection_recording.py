from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from efloud.inventory import AbsenceEvidence
from efloud.reconciliation import PreviousInventoryItem, ReconciliationDecision, reconcile_inventory
from efloud.repository_models import ArtifactKey, ObservationId, SourceId, TreeEntry, canonical_json_bytes

if TYPE_CHECKING:
    from efloud.adapters import CollectionAcquisition, CollectionItemAcquisition
    from efloud.inventory import InventoryItem, SourceInventory
    from efloud.json_types import JsonObject
    from efloud.repository_capabilities import RepositoryWriter
    from efloud.repository_models import OperationId, RunId
    from efloud.validation import ValidationService

_HTTP_NOT_FOUND = 404


@dataclass(frozen=True, slots=True)
class CollectionRecordingResult:
    observations: tuple[ObservationId, ...]
    snapshot_id: str
    execution_observation_id: ObservationId
    content_count: int
    absence_count: int
    unresolved_count: int


@dataclass(slots=True)
class _RecordingState:
    observations: list[ObservationId] = field(default_factory=list)
    content_observations: list[ObservationId] = field(default_factory=list)
    tree_entries: list[TreeEntry] = field(default_factory=list)
    content_count: int = 0
    absence_count: int = 0
    unresolved_count: int = 0


def _previous_items(repository: RepositoryWriter, source_id: SourceId) -> tuple[PreviousInventoryItem, ...]:
    snapshot = next(
        (
            candidate
            for candidate in repository.source_snapshots_for(source_id, limit=200)
            if candidate.complete and candidate.tree_id is not None
        ),
        None,
    )
    if snapshot is None or snapshot.tree_id is None:
        return ()
    previous: list[PreviousInventoryItem] = []
    for entry in repository.tree_entries(snapshot.tree_id):
        item_id = entry.metadata.get("item_id")
        if not isinstance(item_id, str):
            continue
        previous.append(
            PreviousInventoryItem(
                item_id=item_id,
                artifact_key=ArtifactKey(f"source:{source_id}:item:{item_id}"),
                content_id=entry.content_id,
                source_path=entry.relative_path,
                metadata={"kind": entry.kind},
            )
        )
    return tuple(previous)


def _entry_metadata(
    item: InventoryItem, result: CollectionItemAcquisition, decision: ReconciliationDecision
) -> JsonObject:
    metadata: JsonObject = dict(item.metadata)
    metadata.update(result.metadata)
    metadata["item_id"] = item.item_id
    metadata["reconciliation_state"] = decision.state
    if item.change_token is not None:
        metadata["change_token"] = item.change_token.to_dict()
    if result.status_code is not None:
        metadata["status_code"] = result.status_code
    return metadata


def _record_validated_item(
    repository: RepositoryWriter,
    validation: ValidationService,
    *,
    state: _RecordingState,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    item: InventoryItem,
    result: CollectionItemAcquisition,
    decision: ReconciliationDecision,
    media_type: str | None,
) -> None:
    if result.destination is None or not result.destination.is_file():
        state.tree_entries.append(
            TreeEntry(
                item.source_path or item.item_id,
                "unresolved",
                metadata={"item_id": item.item_id, "error": "successful fetch has no materialized file"},
            )
        )
        state.unresolved_count += 1
        return
    relative_path = item.source_path or item.item_id
    metadata = _entry_metadata(item, result, decision)
    content = repository.store_path_content(result.destination, media_type=media_type)
    batch = validation.validate_content(
        content, name=relative_path, expectations=item.expected_integrity, checked_at=observed_at
    )
    metadata["validation"] = batch.to_dict()
    if not batch.ok:
        state.tree_entries.append(
            TreeEntry(
                relative_path,
                "unresolved",
                content_id=content.content_id,
                byte_size=result.destination.stat().st_size,
                metadata={**metadata, "error": "required validation failed"},
            )
        )
        state.unresolved_count += 1
        return
    observation = repository.observe_content(
        decision.artifact_key,
        content.content_id,
        run_id=run_id,
        operation_id=operation_id,
        source_id=source_id,
        observed_at=observed_at,
        source_path=relative_path,
        upstream_locator=item.locator,
        metadata={**metadata, "collection": True},
        materialization_kind="collection",
        materialization_path=result.destination,
    )
    state.observations.append(observation.observation_id)
    state.content_observations.append(observation.observation_id)
    state.tree_entries.append(
        TreeEntry(
            relative_path,
            "file",
            content_id=observation.content_id,
            byte_size=result.destination.stat().st_size,
            metadata=metadata,
        )
    )
    state.content_count += 1


def _record_item(
    repository: RepositoryWriter,
    validation: ValidationService,
    *,
    state: _RecordingState,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    inventory: SourceInventory,
    item: InventoryItem,
    result: CollectionItemAcquisition | None,
    decision: ReconciliationDecision,
    media_type: str | None,
) -> None:
    relative_path = item.source_path or item.item_id
    if result is None:
        state.tree_entries.append(
            TreeEntry(
                relative_path,
                "unresolved",
                metadata={"item_id": item.item_id, "error": "enumerated item has no fetch result"},
            )
        )
        state.unresolved_count += 1
        return
    if result.status == "ok":
        _record_validated_item(
            repository,
            validation,
            state=state,
            source_id=source_id,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=inventory.observed_at,
            item=item,
            result=result,
            decision=decision,
            media_type=media_type,
        )
        return
    metadata = _entry_metadata(item, result, decision)
    if result.status_code == _HTTP_NOT_FOUND:
        absence = repository.record_absence(
            decision.artifact_key,
            evidence=AbsenceEvidence.direct_negative(
                source_id=source_id,
                observed_at=inventory.observed_at,
                source_path=relative_path,
                locator=item.locator,
                metadata={"http_status": _HTTP_NOT_FOUND, "collection": True},
            ),
            run_id=run_id,
            operation_id=operation_id,
            metadata={**metadata, "collection": True, "http_status": _HTTP_NOT_FOUND},
        )
        state.observations.append(absence.observation_id)
        state.tree_entries.append(TreeEntry(relative_path, "absent", metadata=metadata))
        state.absence_count += 1
        return
    state.tree_entries.append(
        TreeEntry(
            relative_path, "unresolved", metadata={**metadata, "error": result.error or "item acquisition failed"}
        )
    )
    state.unresolved_count += 1


def _record_membership_absences(
    repository: RepositoryWriter,
    *,
    state: _RecordingState,
    inventory: SourceInventory,
    run_id: RunId,
    operation_id: OperationId,
    decisions: tuple[ReconciliationDecision, ...],
) -> None:
    for decision in decisions:
        if decision.state != "absent" or decision.previous is None:
            continue
        absence = repository.record_absence(
            decision.artifact_key,
            evidence=AbsenceEvidence.from_inventory(
                inventory,
                source_path=decision.previous.source_path,
                metadata={"collection": True, "item_id": decision.item_id},
            ),
            run_id=run_id,
            operation_id=operation_id,
            metadata={
                "collection": True,
                "item_id": decision.item_id,
                "reason": "removed-from-complete-enumeration",
                "reconciliation_state": decision.state,
            },
        )
        state.observations.append(absence.observation_id)
        state.absence_count += 1


def _snapshot_evidence(inventory: SourceInventory, state: _RecordingState, counts: JsonObject) -> JsonObject:
    evidence: JsonObject = {
        "collection": True,
        "inventory_model": "source-inventory-v1",
        "enumeration_complete": inventory.coverage.complete,
        "enumerated_item_count": len(inventory.items),
        "content_item_count": state.content_count,
        "absence_count": state.absence_count,
        "unresolved_item_count": state.unresolved_count,
        "classification_counts": counts,
    }
    if inventory.upstream_identity is not None:
        evidence["upstream_identity"] = inventory.upstream_identity
    return evidence


def _acquisition_payload(acquisition: CollectionAcquisition) -> JsonObject:
    return {
        "source_id": acquisition.source_id,
        "status": acquisition.status,
        "inventory": acquisition.inventory.to_dict() if acquisition.inventory is not None else None,
        "items": [
            {
                "item_id": item.item_id,
                "status": item.status,
                "destination": str(item.destination) if item.destination is not None else None,
                "status_code": item.status_code,
                "metadata": dict(item.metadata),
                "error": item.error,
            }
            for item in acquisition.items
        ],
        "error": acquisition.error,
    }


def record_collection_acquisition(
    repository: RepositoryWriter,
    validation: ValidationService,
    *,
    acquisition: CollectionAcquisition,
    run_id: RunId,
    operation_id: OperationId,
) -> CollectionRecordingResult:
    """Record typed collection inventory/fetch evidence into repository semantics."""
    if acquisition.inventory is None:
        msg = acquisition.error or "Collection acquisition produced no inventory."
        raise ValueError(msg)
    inventory = acquisition.inventory
    source_id = SourceId(acquisition.source_id)
    reconciliation = reconcile_inventory(inventory, _previous_items(repository, source_id))
    decisions = {decision.item_id: decision for decision in reconciliation.decisions}
    results = {item.item_id: item for item in acquisition.items}
    state = _RecordingState()
    for item in inventory.items:
        _record_item(
            repository,
            validation,
            state=state,
            source_id=source_id,
            run_id=run_id,
            operation_id=operation_id,
            inventory=inventory,
            item=item,
            result=results.get(item.item_id),
            decision=decisions[item.item_id],
            media_type=acquisition.media_type,
        )
    _record_membership_absences(
        repository,
        state=state,
        inventory=inventory,
        run_id=run_id,
        operation_id=operation_id,
        decisions=reconciliation.decisions,
    )
    counts: JsonObject = dict(reconciliation.counts().items())
    snapshot = repository.record_tree_snapshot(
        source_id=source_id,
        run_id=run_id,
        entries=state.tree_entries,
        complete=inventory.coverage.complete and state.unresolved_count == 0,
        scope=inventory.coverage.scope,
        observed_at=inventory.observed_at,
        evidence=_snapshot_evidence(inventory, state, counts),
    )
    execution = repository.ingest_bytes(
        f"source:{source_id}:collection-execution",
        canonical_json_bytes(_acquisition_payload(acquisition)),
        run_id=run_id,
        operation_id=operation_id,
        source_id=source_id,
        observed_at=inventory.observed_at,
        media_type="application/json",
        metadata={"collection": True, "adapter_execution": True, "snapshot_id": str(snapshot.snapshot_id)},
        inputs=(*acquisition.input_observation_ids, *state.content_observations),
    )
    observations = (*state.observations, execution.observation_id)
    return CollectionRecordingResult(
        observations,
        str(snapshot.snapshot_id),
        execution.observation_id,
        state.content_count,
        state.absence_count,
        state.unresolved_count,
    )


__all__ = ["CollectionRecordingResult", "record_collection_acquisition"]
