from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.inventory import (
    ChangeToken,
    ChangeTokenReliability,
    IntegrityExpectation,
    InventoryCoverage,
    InventoryItem,
    SourceInventory,
)
from efloud.json_types import JsonMapping, JsonObject, JsonValue, copy_json_mapping, json_mapping_or_none
from efloud.reconciliation import PreviousInventoryItem, ReconciliationDecision, reconcile_inventory
from efloud.repository_models import ArtifactKey, ObservationId, SourceId, TreeEntry, canonical_json_bytes

if TYPE_CHECKING:
    from efloud.repository import Repository
    from efloud.repository_models import OperationId, RunId


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


def _change_token(value: JsonValue | None) -> ChangeToken | None:
    mapping = json_mapping_or_none(value)
    if mapping is None:
        return None
    kind = mapping.get("kind")
    token_value = mapping.get("value")
    reliability = mapping.get("reliability")
    if not isinstance(kind, str) or not isinstance(token_value, str):
        return None
    reliability_value: ChangeTokenReliability = "weak" if reliability == "weak" else "strong"
    return ChangeToken(kind=kind, value=token_value, reliability=reliability_value)


def _integrity_expectations(value: JsonValue | None) -> tuple[IntegrityExpectation, ...]:
    if not isinstance(value, list):
        return ()
    expectations: list[IntegrityExpectation] = []
    for raw in value:
        mapping = json_mapping_or_none(raw)
        if mapping is None:
            continue
        algorithm = mapping.get("algorithm")
        digest = mapping.get("digest")
        required = mapping.get("required")
        metadata = json_mapping_or_none(mapping.get("metadata"))
        if not isinstance(algorithm, str) or not isinstance(digest, str):
            continue
        expectations.append(
            IntegrityExpectation(
                algorithm=algorithm,
                digest=digest,
                required=required if isinstance(required, bool) else True,
                metadata=copy_json_mapping(metadata) if metadata is not None else {},
            )
        )
    return tuple(expectations)


def _inventory_item(source_id: SourceId, raw: JsonValue) -> InventoryItem:
    mapping = json_mapping_or_none(raw)
    if mapping is None:
        msg = "Collection inventory contains a non-object item."
        raise TypeError(msg)
    item_id = mapping.get("item_id")
    if not isinstance(item_id, str):
        msg = "Collection inventory item has no string item_id."
        raise TypeError(msg)
    locator = mapping.get("locator")
    source_path = mapping.get("source_path")
    metadata = json_mapping_or_none(mapping.get("metadata"))
    return InventoryItem(
        item_id=item_id,
        artifact_key=ArtifactKey(f"source:{source_id}:item:{item_id}"),
        locator=locator if isinstance(locator, str) else None,
        source_path=source_path if isinstance(source_path, str) else None,
        change_token=_change_token(mapping.get("change_token")),
        expected_integrity=_integrity_expectations(mapping.get("expected_integrity")),
        metadata=copy_json_mapping(metadata) if metadata is not None else {},
    )


def _inventory(source_id: SourceId, payload: JsonMapping, observed_at: float) -> SourceInventory:
    serialized = json_mapping_or_none(payload.get("inventory"))
    if serialized is None:
        msg = "Collection adapter result has no serialized SourceInventory."
        raise ValueError(msg)
    raw_items = serialized.get("items")
    if not isinstance(raw_items, list):
        msg = "Collection adapter result inventory has no item list."
        raise ValueError(msg)
    coverage = json_mapping_or_none(serialized.get("coverage")) or {}
    scope_value = coverage.get("scope")
    scope = (
        tuple(sorted(value for value in scope_value if isinstance(value, str)))
        if isinstance(scope_value, list)
        else ()
    )
    inventory_observed_at = serialized.get("observed_at")
    upstream_identity = serialized.get("upstream_identity")
    metadata = json_mapping_or_none(serialized.get("metadata"))
    return SourceInventory(
        source_id=source_id,
        observed_at=(
            float(inventory_observed_at)
            if isinstance(inventory_observed_at, int | float) and not isinstance(inventory_observed_at, bool)
            else observed_at
        ),
        coverage=InventoryCoverage(scope=scope, complete=coverage.get("complete") is True),
        items=tuple(_inventory_item(source_id, raw) for raw in raw_items),
        upstream_identity=upstream_identity if isinstance(upstream_identity, str) else None,
        metadata=copy_json_mapping(metadata) if metadata is not None else {},
    )


def _previous_items(repository: Repository, source_id: SourceId) -> tuple[PreviousInventoryItem, ...]:
    snapshot = next(
        (
            candidate
            for candidate in repository.metadata.source_snapshots_for(source_id, limit=200)
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
                change_token=_change_token(entry.metadata.get("change_token")),
                metadata={"kind": entry.kind},
            )
        )
    return tuple(previous)


def _entries(payload: JsonMapping) -> dict[str, JsonMapping]:
    raw_entries = json_mapping_or_none(payload.get("entries")) or {}
    entries: dict[str, JsonMapping] = {}
    for key, raw in raw_entries.items():
        mapping = json_mapping_or_none(raw)
        if mapping is None:
            continue
        item_id = mapping.get("item_id")
        normalized = item_id if isinstance(item_id, str) else key
        entries[normalized] = mapping
    return entries


def _relative_path(item: InventoryItem, entry: JsonMapping) -> str:
    request = json_mapping_or_none(entry.get("request")) or {}
    fanout_path = request.get("fanout_path")
    if isinstance(fanout_path, str) and fanout_path:
        return fanout_path
    if item.source_path is not None:
        return item.source_path
    return item.item_id


def _entry_metadata(item: InventoryItem, entry: JsonMapping, decision: ReconciliationDecision) -> JsonObject:
    raw_metadata = json_mapping_or_none(entry.get("metadata"))
    metadata: JsonObject = copy_json_mapping(raw_metadata) if raw_metadata is not None else {}
    metadata["item_id"] = item.item_id
    metadata["reconciliation_state"] = decision.state
    if item.change_token is not None:
        metadata["change_token"] = item.change_token.to_dict()
    return metadata


def _record_item(
    repository: Repository,
    *,
    state: _RecordingState,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    task_name: str,
    item: InventoryItem,
    entry: JsonMapping | None,
    decision: ReconciliationDecision,
    media_type: str | None,
) -> None:
    if entry is None:
        relative_path = item.source_path or item.item_id
        state.tree_entries.append(
            TreeEntry(
                relative_path=relative_path,
                kind="unresolved",
                metadata={"item_id": item.item_id, "error": "enumerated item has no acquisition result"},
            )
        )
        state.unresolved_count += 1
        return

    relative_path = _relative_path(item, entry)
    metadata = _entry_metadata(item, entry, decision)
    status = entry.get("status")
    destination = entry.get("dest")
    if status == "ok" and isinstance(destination, str) and Path(destination).is_file():
        path = Path(destination)
        observation = repository.ingest_path(
            decision.artifact_key,
            path,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=observed_at,
            source_path=relative_path,
            upstream_locator=item.locator,
            media_type=media_type,
            metadata={**metadata, "collection_task": task_name},
            materialization_kind="fanout",
        )
        state.observations.append(observation.observation_id)
        state.content_observations.append(observation.observation_id)
        state.tree_entries.append(
            TreeEntry(
                relative_path=relative_path,
                kind="file",
                content_id=observation.content_id,
                byte_size=path.stat().st_size,
                metadata=metadata,
            )
        )
        state.content_count += 1
        return

    error = entry.get("error")
    if status == "error" and error == "404":
        absence = repository.record_absence(
            decision.artifact_key,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=observed_at,
            source_path=relative_path,
            upstream_locator=item.locator,
            metadata={**metadata, "collection_task": task_name, "http_status": 404},
        )
        state.observations.append(absence.observation_id)
        state.tree_entries.append(TreeEntry(relative_path=relative_path, kind="absent", metadata=metadata))
        state.absence_count += 1
        return

    state.tree_entries.append(
        TreeEntry(
            relative_path=relative_path,
            kind="unresolved",
            metadata={**metadata, "error": error if isinstance(error, str) else "item acquisition failed"},
        )
    )
    state.unresolved_count += 1


def _record_membership_absences(
    repository: Repository,
    *,
    state: _RecordingState,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    task_name: str,
    decisions: tuple[ReconciliationDecision, ...],
) -> None:
    for decision in decisions:
        if decision.state != "absent" or decision.previous is None:
            continue
        absence = repository.record_absence(
            decision.artifact_key,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=observed_at,
            source_path=decision.previous.source_path,
            metadata={
                "collection_task": task_name,
                "item_id": decision.item_id,
                "reason": "removed-from-complete-enumeration",
                "reconciliation_state": decision.state,
            },
        )
        state.observations.append(absence.observation_id)
        state.absence_count += 1


def _snapshot_evidence(
    *,
    task_name: str,
    inventory: SourceInventory,
    state: _RecordingState,
    counts: JsonObject,
) -> JsonObject:
    evidence: JsonObject = {
        "collection": True,
        "task": task_name,
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


def record_collection_acquisition(
    repository: Repository,
    *,
    source_id: SourceId | str,
    task_name: str,
    payload: JsonMapping,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
) -> CollectionRecordingResult:
    """Record typed collection adapter evidence without invoking the legacy importer."""
    normalized_source = SourceId(str(source_id))
    inventory = _inventory(normalized_source, payload, observed_at)
    reconciliation = reconcile_inventory(inventory, _previous_items(repository, normalized_source))
    decisions = {decision.item_id: decision for decision in reconciliation.decisions}
    entries = _entries(payload)
    request = json_mapping_or_none(payload.get("request")) or {}
    media_type = "application/json" if request.get("response_mode") == "json" else None
    state = _RecordingState()

    for item in inventory.items:
        _record_item(
            repository,
            state=state,
            source_id=normalized_source,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=inventory.observed_at,
            task_name=task_name,
            item=item,
            entry=entries.get(item.item_id),
            decision=decisions[item.item_id],
            media_type=media_type,
        )
    _record_membership_absences(
        repository,
        state=state,
        source_id=normalized_source,
        run_id=run_id,
        operation_id=operation_id,
        observed_at=inventory.observed_at,
        task_name=task_name,
        decisions=reconciliation.decisions,
    )

    counts: JsonObject = dict(reconciliation.counts().items())
    snapshot = repository.record_tree_snapshot(
        source_id=normalized_source,
        run_id=run_id,
        entries=state.tree_entries,
        complete=inventory.coverage.complete,
        scope=inventory.coverage.scope,
        observed_at=inventory.observed_at,
        evidence=_snapshot_evidence(
            task_name=task_name,
            inventory=inventory,
            state=state,
            counts=counts,
        ),
    )
    execution = repository.ingest_bytes(
        f"derived:{task_name}:execution",
        canonical_json_bytes(copy_json_mapping(payload)),
        run_id=run_id,
        operation_id=operation_id,
        source_id=normalized_source,
        observed_at=inventory.observed_at,
        media_type="application/json",
        metadata={"collection": True, "adapter_execution": True, "snapshot_id": str(snapshot.snapshot_id)},
        inputs=tuple(state.content_observations),
    )
    observations = (*state.observations, execution.observation_id)
    return CollectionRecordingResult(
        observations=observations,
        snapshot_id=str(snapshot.snapshot_id),
        execution_observation_id=execution.observation_id,
        content_count=state.content_count,
        absence_count=state.absence_count,
        unresolved_count=state.unresolved_count,
    )


__all__ = ["CollectionRecordingResult", "record_collection_acquisition"]
