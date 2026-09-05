from __future__ import annotations

from dataclasses import dataclass, field
from itertools import starmap
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.derived import RepositoryDerivedTask
from efloud.fanout import FanoutEnumeration, FanoutItem, fanout_source_inventory
from efloud.inventory import (
    ChangeToken,
    IntegrityExpectation,
    InventoryCoverage,
    InventoryItem,
    SourceInventory,
)
from efloud.json_types import (
    JsonMapping,
    JsonObject,
    JsonValue,
    copy_json_mapping,
    json_mapping_or_none,
)
from efloud.reconciliation import (
    PreviousInventoryItem,
    ReconciliationDecision,
    ReconciliationResult,
    reconcile_inventory,
)
from efloud.registry import SourceKind
from efloud.repository_models import (
    ArtifactKey,
    ArtifactObservation,
    ObservationId,
    OperationId,
    RunId,
    SourceId,
    TreeEntry,
    canonical_json_bytes,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from efloud.derived import DerivedTask
    from efloud.models import EngineConfig
    from efloud.registry import SourceDefinition
    from efloud.repository import Repository


@dataclass(frozen=True, slots=True)
class DerivedImportResult:
    observations: tuple[ObservationId, ...]
    handled_source_ids: tuple[str, ...]


@dataclass(slots=True)
class _CollectionImportState:
    observations: list[ObservationId] = field(default_factory=list)
    tree_entries: list[TreeEntry] = field(default_factory=list)
    unresolved_count: int = 0
    absent_count: int = 0
    content_count: int = 0
    unexpected_entry_count: int = 0


@dataclass(slots=True)
class _CollectionRecordContext:
    inventory: SourceInventory
    reconciliation: ReconciliationResult
    entries_by_id: dict[str, tuple[str, JsonValue]]
    media_type: str | None
    state: _CollectionImportState


@dataclass(frozen=True, slots=True)
class _DerivedTaskContext:
    task_name: str
    payload: JsonMapping
    task: DerivedTask | None
    task_version: str | None
    input_source_ids: tuple[str, ...]
    task_parameters: JsonObject
    input_ids: tuple[ObservationId, ...]
    input_snapshot_ids: list[str]
    source: SourceDefinition | None
    source_id: SourceId | None


def _json_string_list(values: Iterable[object]) -> list[JsonValue]:
    return [str(value) for value in values]


def _task_by_name(config: EngineConfig, name: str) -> DerivedTask | None:
    for task in config.derived_tasks:
        if task.name == name:
            return task
    return None


def _task_metadata(task: DerivedTask | None) -> tuple[str | None, tuple[str, ...], JsonObject]:
    if task is None or not isinstance(task, RepositoryDerivedTask):
        return None, (), {}
    return task.repository_version, task.repository_input_source_ids, task.repository_parameters()


def _current_inputs(repository: Repository, source_ids: tuple[str, ...]) -> tuple[ObservationId, ...]:
    wanted = set(source_ids)
    if not wanted:
        return ()
    observations: list[ObservationId] = []
    for artifact_key in repository.artifact_keys():
        state = repository.latest_state(artifact_key)
        if isinstance(state, ArtifactObservation) and state.source_id is not None and str(state.source_id) in wanted:
            observations.append(state.observation_id)
    return tuple(sorted(observations, key=str))


def _input_snapshot_ids(repository: Repository, source_ids: tuple[str, ...]) -> list[str]:
    snapshots: list[str] = []
    for source_id in source_ids:
        snapshot = repository.latest_source_snapshot(source_id)
        if snapshot is not None:
            snapshots.append(str(snapshot.snapshot_id))
    return sorted(snapshots)


def _operation_parameters(context: _DerivedTaskContext) -> JsonObject:
    payload: JsonObject = {
        "task": context.task_name,
        "parameters": dict(context.task_parameters),
        "input_source_ids": _json_string_list(context.input_source_ids),
        "input_snapshot_ids": _json_string_list(context.input_snapshot_ids),
        "input_observation_ids": _json_string_list(context.input_ids),
    }
    if context.task_version is not None:
        payload["task_version"] = context.task_version
    return payload


def _task_runtime_metadata(context: _DerivedTaskContext) -> JsonObject:
    metadata: JsonObject = {
        "task": context.task_name,
        "input_snapshot_ids": _json_string_list(context.input_snapshot_ids),
        "input_observation_ids": _json_string_list(context.input_ids),
        "provenance_complete": context.task is not None and isinstance(context.task, RepositoryDerivedTask),
    }
    if context.task_version is not None:
        metadata["task_version"] = context.task_version
    return metadata


def _collection_relative_path(item_id: str, entry: JsonMapping) -> str:
    request = json_mapping_or_none(entry.get("request")) or {}
    fanout_path = request.get("fanout_path")
    if isinstance(fanout_path, str) and fanout_path.strip():
        return fanout_path.replace("\\", "/").strip("/")
    return item_id


def _collection_locator(entry: JsonMapping) -> str | None:
    request = json_mapping_or_none(entry.get("request")) or {}
    url = request.get("url")
    return url if isinstance(url, str) else None


def _collection_item_metadata(item_id: str, entry: JsonMapping, task_name: str) -> JsonObject:
    payload: JsonObject = {
        "collection_task": task_name,
        "item_id": item_id,
    }
    metadata = json_mapping_or_none(entry.get("metadata"))
    if metadata is not None:
        payload["item_metadata"] = copy_json_mapping(metadata)
    return payload


def _change_token_from_mapping(value: JsonValue | None) -> ChangeToken | None:
    mapping = json_mapping_or_none(value)
    if mapping is None:
        return None
    kind = mapping.get("kind")
    token_value = mapping.get("value")
    if not isinstance(kind, str) or not isinstance(token_value, str):
        return None
    reliability = mapping.get("reliability")
    if reliability == "strong":
        return ChangeToken(kind=kind, value=token_value, reliability="strong")
    return ChangeToken(kind=kind, value=token_value, reliability="weak")


def _integrity_expectations_from_mapping(value: JsonValue | None) -> tuple[IntegrityExpectation, ...]:
    if not isinstance(value, list):
        return ()
    expectations: list[IntegrityExpectation] = []
    for raw in value:
        mapping = json_mapping_or_none(raw)
        if mapping is None:
            continue
        algorithm = mapping.get("algorithm")
        digest = mapping.get("digest")
        if not isinstance(algorithm, str) or not isinstance(digest, str):
            continue
        required = mapping.get("required") is not False
        metadata = json_mapping_or_none(mapping.get("metadata"))
        expectations.append(
            IntegrityExpectation(
                algorithm=algorithm,
                digest=digest,
                required=required,
                metadata=copy_json_mapping(metadata) if metadata is not None else {},
            )
        )
    return tuple(expectations)


def _fanout_item_from_entry(key: str, raw_entry: JsonValue) -> FanoutItem:
    entry = json_mapping_or_none(raw_entry)
    if entry is None:
        return FanoutItem(item_id=key)
    raw_item_id = entry.get("item_id")
    item_id = raw_item_id if isinstance(raw_item_id, str) else key
    request = json_mapping_or_none(entry.get("request")) or {}
    request_path_value = request.get("request_path")
    request_path = request_path_value if isinstance(request_path_value, str) else None
    evidence = json_mapping_or_none(entry.get("inventory")) or {}
    return FanoutItem(
        item_id=item_id,
        request_path=request_path,
        change_token=_change_token_from_mapping(evidence.get("change_token")),
        expected_integrity=_integrity_expectations_from_mapping(evidence.get("expected_integrity")),
    )


def _enumeration_count_matches(payload: JsonMapping, item_count: int) -> bool:
    enumeration = json_mapping_or_none(payload.get("enumeration")) or {}
    declared_count = enumeration.get("item_count")
    if declared_count is None:
        return True
    return isinstance(declared_count, int) and not isinstance(declared_count, bool) and declared_count == item_count


def _serialized_inventory_item(source_id: SourceId, raw: JsonValue) -> InventoryItem:
    mapping = json_mapping_or_none(raw)
    if mapping is None:
        msg = "Serialized collection inventory contains a non-object item."
        raise TypeError(msg)
    item_id = mapping.get("item_id")
    if not isinstance(item_id, str):
        msg = "Serialized collection inventory item has no string item_id."
        raise TypeError(msg)
    locator_value = mapping.get("locator")
    source_path_value = mapping.get("source_path")
    metadata = json_mapping_or_none(mapping.get("metadata"))
    return InventoryItem(
        item_id=item_id,
        artifact_key=ArtifactKey(f"source:{source_id}:item:{item_id}"),
        locator=locator_value if isinstance(locator_value, str) else None,
        source_path=source_path_value if isinstance(source_path_value, str) else None,
        change_token=_change_token_from_mapping(mapping.get("change_token")),
        expected_integrity=_integrity_expectations_from_mapping(mapping.get("expected_integrity")),
        metadata=copy_json_mapping(metadata) if metadata is not None else {},
    )


def _serialized_inventory_items(source_id: SourceId, value: JsonValue | None) -> tuple[InventoryItem, ...]:
    if not isinstance(value, list):
        msg = "Serialized collection inventory has no item list."
        raise TypeError(msg)
    return tuple(_serialized_inventory_item(source_id, raw) for raw in value)


def _serialized_inventory_complete(
    payload: JsonMapping,
    serialized: JsonMapping,
    *,
    item_count: int,
) -> bool:
    coverage = json_mapping_or_none(serialized.get("coverage")) or {}
    enumeration = json_mapping_or_none(payload.get("enumeration")) or {}
    if coverage.get("complete") is not True:
        return False
    if enumeration and enumeration.get("complete") is not True:
        return False
    return _enumeration_count_matches(payload, item_count)


def _serialized_inventory_observed_at(serialized: JsonMapping, fallback: float) -> float:
    value = serialized.get("observed_at")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return fallback


def _serialized_collection_inventory(
    *,
    source_id: SourceId,
    payload: JsonMapping,
    observed_at: float,
) -> SourceInventory | None:
    serialized = json_mapping_or_none(payload.get("inventory"))
    if serialized is None:
        return None
    serialized_source = serialized.get("source_id")
    if isinstance(serialized_source, str) and serialized_source != str(source_id):
        msg = f"Collection inventory source mismatch: {serialized_source!r} != {str(source_id)!r}"
        raise ValueError(msg)
    items = _serialized_inventory_items(source_id, serialized.get("items"))
    identity_value = serialized.get("upstream_identity")
    metadata = json_mapping_or_none(serialized.get("metadata"))
    return SourceInventory(
        source_id=source_id,
        observed_at=_serialized_inventory_observed_at(serialized, observed_at),
        coverage=InventoryCoverage(
            complete=_serialized_inventory_complete(payload, serialized, item_count=len(items))
        ),
        items=items,
        upstream_identity=identity_value if isinstance(identity_value, str) else None,
        metadata=copy_json_mapping(metadata) if metadata is not None else {},
    )


def _legacy_collection_inventory(
    *,
    source_id: SourceId,
    payload: JsonMapping,
    observed_at: float,
) -> SourceInventory:
    entries = json_mapping_or_none(payload.get("entries")) or {}
    enumeration = json_mapping_or_none(payload.get("enumeration")) or {}
    request = json_mapping_or_none(payload.get("request")) or {}
    base_url_value = request.get("base_url")
    base_url = base_url_value if isinstance(base_url_value, str) else ""
    identity_value = enumeration.get("upstream_identity")
    identity = identity_value if isinstance(identity_value, str) else None
    fanout_enumeration = FanoutEnumeration(
        items=tuple(starmap(_fanout_item_from_entry, sorted(entries.items()))),
        complete=enumeration.get("complete") is True and _enumeration_count_matches(payload, len(entries)),
        upstream_identity=identity,
    )
    return fanout_source_inventory(
        source_id=source_id,
        base_url=base_url,
        enumeration=fanout_enumeration,
        observed_at=observed_at,
    )


def _collection_inventory(
    *,
    source_id: SourceId,
    payload: JsonMapping,
    observed_at: float,
) -> SourceInventory:
    serialized = _serialized_collection_inventory(
        source_id=source_id,
        payload=payload,
        observed_at=observed_at,
    )
    if serialized is not None:
        return serialized
    return _legacy_collection_inventory(
        source_id=source_id,
        payload=payload,
        observed_at=observed_at,
    )


def _tree_change_token(tree_entry: TreeEntry) -> ChangeToken | None:
    return _change_token_from_mapping(tree_entry.metadata.get("change_token"))


def _previous_collection_items(
    repository: Repository,
    source_id: SourceId,
) -> tuple[PreviousInventoryItem, ...]:
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
    for tree_entry in repository.tree_entries(snapshot.tree_id):
        item_id = tree_entry.metadata.get("item_id")
        if not isinstance(item_id, str):
            continue
        previous.append(
            PreviousInventoryItem(
                item_id=item_id,
                artifact_key=ArtifactKey(f"source:{source_id}:item:{item_id}"),
                content_id=tree_entry.content_id,
                source_path=tree_entry.relative_path,
                change_token=_tree_change_token(tree_entry),
                metadata={"kind": tree_entry.kind},
            )
        )
    return tuple(previous)


def _tree_metadata(item_id: str, decision: ReconciliationDecision) -> JsonObject:
    metadata: JsonObject = {
        "item_id": item_id,
        "reconciliation_state": decision.state,
    }
    if decision.current is not None and decision.current.change_token is not None:
        metadata["change_token"] = decision.current.change_token.to_dict()
    return metadata


def _record_collection_content(
    repository: Repository,
    *,
    state: _CollectionImportState,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    item_id: str,
    relative_path: str,
    locator: str | None,
    media_type: str | None,
    item_metadata: JsonObject,
    destination: str,
    decision: ReconciliationDecision,
) -> None:
    path = Path(destination)
    observation = repository.ingest_path(
        decision.artifact_key,
        path,
        run_id=run_id,
        operation_id=operation_id,
        source_id=source_id,
        observed_at=observed_at,
        source_path=relative_path,
        upstream_locator=locator,
        media_type=media_type,
        metadata={**item_metadata, "reconciliation_state": decision.state},
        materialization_kind="compatibility-fanout",
    )
    state.observations.append(observation.observation_id)
    state.tree_entries.append(
        TreeEntry(
            relative_path=relative_path,
            kind="file",
            content_id=observation.content_id,
            byte_size=path.stat().st_size,
            metadata=_tree_metadata(item_id, decision),
        )
    )
    state.content_count += 1


def _record_collection_absence(
    repository: Repository,
    *,
    state: _CollectionImportState,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    item_id: str,
    relative_path: str,
    locator: str | None,
    item_metadata: JsonObject,
    decision: ReconciliationDecision,
) -> None:
    absence = repository.record_absence(
        decision.artifact_key,
        run_id=run_id,
        operation_id=operation_id,
        source_id=source_id,
        observed_at=observed_at,
        source_path=relative_path,
        upstream_locator=locator,
        metadata={
            **item_metadata,
            "http_status": 404,
            "reconciliation_state": decision.state,
        },
    )
    state.observations.append(absence.observation_id)
    state.tree_entries.append(
        TreeEntry(
            relative_path=relative_path,
            kind="absent",
            metadata=_tree_metadata(item_id, decision),
        )
    )
    state.absent_count += 1


def _record_collection_entry(
    repository: Repository,
    *,
    state: _CollectionImportState,
    source_id: SourceId,
    task_name: str,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    media_type: str | None,
    key: str,
    raw_entry: JsonValue,
    decision: ReconciliationDecision,
) -> None:
    entry = json_mapping_or_none(raw_entry)
    if entry is None:
        current = decision.current
        relative_path = current.source_path if current is not None and current.source_path else key
        state.unresolved_count += 1
        state.tree_entries.append(
            TreeEntry(
                relative_path=relative_path,
                kind="unresolved",
                metadata={
                    **_tree_metadata(decision.item_id, decision),
                    "error": "invalid acquisition result",
                },
            )
        )
        return

    raw_item_id = entry.get("item_id")
    item_id = raw_item_id if isinstance(raw_item_id, str) else key
    relative_path = _collection_relative_path(item_id, entry)
    locator = _collection_locator(entry)
    item_metadata = _collection_item_metadata(item_id, entry, task_name)
    status = entry.get("status")
    destination = entry.get("dest")

    if status == "ok" and isinstance(destination, str) and Path(destination).is_file():
        _record_collection_content(
            repository,
            state=state,
            source_id=source_id,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed_at,
            item_id=item_id,
            relative_path=relative_path,
            locator=locator,
            media_type=media_type,
            item_metadata=item_metadata,
            destination=destination,
            decision=decision,
        )
        return

    error = entry.get("error")
    if status == "error" and error == "404":
        _record_collection_absence(
            repository,
            state=state,
            source_id=source_id,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed_at,
            item_id=item_id,
            relative_path=relative_path,
            locator=locator,
            item_metadata=item_metadata,
            decision=decision,
        )
        return

    error_text = error if isinstance(error, str) else "collection item was not materialized"
    state.tree_entries.append(
        TreeEntry(
            relative_path=relative_path,
            kind="unresolved",
            metadata={
                **_tree_metadata(item_id, decision),
                "error": error_text,
            },
        )
    )
    state.unresolved_count += 1


def _record_missing_collection_entry(
    state: _CollectionImportState,
    decision: ReconciliationDecision,
) -> None:
    current = decision.current
    relative_path = current.source_path if current is not None and current.source_path is not None else decision.item_id
    state.tree_entries.append(
        TreeEntry(
            relative_path=relative_path,
            kind="unresolved",
            metadata={
                **_tree_metadata(decision.item_id, decision),
                "error": "enumerated item has no acquisition result",
            },
        )
    )
    state.unresolved_count += 1


def _record_collection_membership_absences(
    repository: Repository,
    *,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    task_name: str,
    decisions: tuple[ReconciliationDecision, ...],
) -> list[ObservationId]:
    removed: list[ObservationId] = []
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
        removed.append(absence.observation_id)
    return removed


def _entries_by_item_id(entries: JsonMapping) -> dict[str, tuple[str, JsonValue]]:
    indexed: dict[str, tuple[str, JsonValue]] = {}
    for key, raw_entry in sorted(entries.items()):
        entry = json_mapping_or_none(raw_entry)
        raw_item_id = entry.get("item_id") if entry is not None else None
        item_id = raw_item_id if isinstance(raw_item_id, str) else key
        if item_id in indexed:
            msg = f"Collection acquisition results contain duplicate item identifier: {item_id!r}"
            raise ValueError(msg)
        indexed[item_id] = (key, raw_entry)
    return indexed


def _collection_record_context(
    repository: Repository,
    *,
    source_id: SourceId,
    payload: JsonMapping,
    observed_at: float,
) -> _CollectionRecordContext:
    entries = json_mapping_or_none(payload.get("entries")) or {}
    inventory = _collection_inventory(source_id=source_id, payload=payload, observed_at=observed_at)
    reconciliation = reconcile_inventory(inventory, _previous_collection_items(repository, source_id))
    entries_by_id = _entries_by_item_id(entries)
    inventory_ids = {item.item_id for item in inventory.items}
    request = json_mapping_or_none(payload.get("request")) or {}
    return _CollectionRecordContext(
        inventory=inventory,
        reconciliation=reconciliation,
        entries_by_id=entries_by_id,
        media_type="application/json" if request.get("response_mode") == "json" else None,
        state=_CollectionImportState(
            unexpected_entry_count=len(set(entries_by_id) - inventory_ids),
        ),
    )


def _record_collection_members(
    repository: Repository,
    *,
    context: _CollectionRecordContext,
    source_id: SourceId,
    task_name: str,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
) -> None:
    decisions_by_id = {decision.item_id: decision for decision in context.reconciliation.decisions}
    for item in context.inventory.items:
        decision = decisions_by_id[item.item_id]
        acquired = context.entries_by_id.get(item.item_id)
        if acquired is None:
            _record_missing_collection_entry(context.state, decision)
            continue
        key, raw_entry = acquired
        _record_collection_entry(
            repository,
            state=context.state,
            source_id=source_id,
            task_name=task_name,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed_at,
            media_type=context.media_type,
            key=key,
            raw_entry=raw_entry,
            decision=decision,
        )


def _collection_snapshot_evidence(
    context: _CollectionRecordContext,
    *,
    task_name: str,
    removed_count: int,
) -> JsonObject:
    classification_counts: JsonObject = {
        state: count for state, count in context.reconciliation.counts().items()
    }
    evidence: JsonObject = {
        "collection": True,
        "task": task_name,
        "inventory_model": "source-inventory-v1",
        "enumeration_complete": context.inventory.coverage.complete,
        "enumerated_item_count": len(context.inventory.items),
        "content_item_count": context.state.content_count,
        "absent_item_count": context.state.absent_count,
        "unresolved_item_count": context.state.unresolved_count,
        "unexpected_entry_count": context.state.unexpected_entry_count,
        "removed_item_count": removed_count,
        "acquisition_complete": (
            context.state.unresolved_count == 0 and context.state.unexpected_entry_count == 0
        ),
        "classification_counts": classification_counts,
    }
    if context.inventory.upstream_identity is not None:
        evidence["upstream_identity"] = context.inventory.upstream_identity
    return evidence


def _record_collection(
    repository: Repository,
    *,
    source_id: SourceId,
    task_name: str,
    payload: JsonMapping,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
) -> tuple[list[ObservationId], str]:
    context = _collection_record_context(
        repository,
        source_id=source_id,
        payload=payload,
        observed_at=observed_at,
    )
    _record_collection_members(
        repository,
        context=context,
        source_id=source_id,
        task_name=task_name,
        run_id=run_id,
        operation_id=operation_id,
        observed_at=observed_at,
    )
    removed = _record_collection_membership_absences(
        repository,
        source_id=source_id,
        run_id=run_id,
        operation_id=operation_id,
        observed_at=observed_at,
        task_name=task_name,
        decisions=context.reconciliation.decisions,
    )
    context.state.observations.extend(removed)
    snapshot = repository.record_tree_snapshot(
        source_id=source_id,
        run_id=run_id,
        entries=context.state.tree_entries,
        complete=context.inventory.coverage.complete,
        observed_at=context.inventory.observed_at,
        evidence=_collection_snapshot_evidence(
            context,
            task_name=task_name,
            removed_count=len(removed),
        ),
    )
    return context.state.observations, str(snapshot.snapshot_id)


def _record_top_level_output(
    repository: Repository,
    *,
    task_name: str,
    payload: JsonMapping,
    run_id: RunId,
    operation_id: OperationId,
    source_id: SourceId | None,
    observed_at: float,
    inputs: tuple[ObservationId, ...],
    task_metadata: JsonObject,
) -> ObservationId | None:
    destination = payload.get("dest")
    if not isinstance(destination, str):
        return None
    path = Path(destination)
    if not path.is_file():
        return None
    observation = repository.ingest_path(
        f"derived:{task_name}:output",
        path,
        run_id=run_id,
        operation_id=operation_id,
        source_id=source_id,
        observed_at=observed_at,
        metadata=task_metadata,
        inputs=inputs,
        materialization_kind="compatibility-derived",
    )
    return observation.observation_id


def _result_status(payload: JsonMapping) -> str:
    err = payload.get("err")
    if isinstance(err, int) and not isinstance(err, bool):
        return "success" if err == 0 else "partial"
    ok = payload.get("ok")
    if isinstance(ok, bool):
        return "success" if ok else "failed"
    return "success"


def _task_context(
    repository: Repository,
    *,
    config: EngineConfig,
    task_name: str,
    payload: JsonMapping,
) -> _DerivedTaskContext:
    task = _task_by_name(config, task_name)
    task_version, input_source_ids, task_parameters = _task_metadata(task)
    input_ids = _current_inputs(repository, input_source_ids)
    input_snapshot_ids = _input_snapshot_ids(repository, input_source_ids)
    payload_source_id = payload.get("source_id")
    source = (
        next((item for item in config.sources if item.id == payload_source_id), None)
        if isinstance(payload_source_id, str)
        else None
    )
    source_id = SourceId(source.id) if source is not None else None
    return _DerivedTaskContext(
        task_name=task_name,
        payload=payload,
        task=task,
        task_version=task_version,
        input_source_ids=input_source_ids,
        task_parameters=task_parameters,
        input_ids=input_ids,
        input_snapshot_ids=input_snapshot_ids,
        source=source,
        source_id=source_id,
    )


def _import_one_derived_result(
    repository: Repository,
    *,
    context: _DerivedTaskContext,
    run_id: RunId,
    started_at: float,
) -> tuple[list[ObservationId], str | None]:
    operation_id = repository.start_operation(
        run_id=run_id,
        source_id=context.source_id,
        kind="derived",
        subject=context.task_name,
        started_at=started_at,
        parameters=_operation_parameters(context),
    )
    task_metadata = _task_runtime_metadata(context)
    observations: list[ObservationId] = []
    handled_source_id: str | None = None
    collection_snapshot_id: str | None = None

    if context.source is not None and context.source.kind is SourceKind.REST_BASE:
        collection_observations, collection_snapshot_id = _record_collection(
            repository,
            source_id=SourceId(context.source.id),
            task_name=context.task_name,
            payload=context.payload,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=started_at,
        )
        observations.extend(collection_observations)
        handled_source_id = context.source.id
        task_metadata["collection_snapshot_id"] = collection_snapshot_id

    output_id = _record_top_level_output(
        repository,
        task_name=context.task_name,
        payload=context.payload,
        run_id=run_id,
        operation_id=operation_id,
        source_id=context.source_id,
        observed_at=started_at,
        inputs=context.input_ids,
        task_metadata=task_metadata,
    )
    if output_id is not None:
        observations.append(output_id)

    execution_inputs = [*context.input_ids]
    if output_id is not None:
        execution_inputs.append(output_id)
    execution_metadata: JsonObject = {
        **task_metadata,
        "compatibility_execution_record": True,
    }
    execution_observation = repository.ingest_bytes(
        f"derived:{context.task_name}:execution",
        canonical_json_bytes(copy_json_mapping(context.payload)),
        run_id=run_id,
        operation_id=operation_id,
        source_id=context.source_id,
        observed_at=started_at,
        media_type="application/json",
        metadata=execution_metadata,
        inputs=tuple(execution_inputs),
    )
    observations.append(execution_observation.observation_id)

    details: JsonObject = {
        "execution_observation_id": str(execution_observation.observation_id),
        "input_observation_count": len(context.input_ids),
    }
    if collection_snapshot_id is not None:
        details["collection_snapshot_id"] = collection_snapshot_id
    repository.finish_operation(
        operation_id,
        status=_result_status(context.payload),
        details=details,
    )
    return observations, handled_source_id


def import_derived_results(
    repository: Repository,
    *,
    config: EngineConfig,
    run_id: RunId,
    started_at: float,
    derived_results: JsonMapping,
) -> DerivedImportResult:
    observations: list[ObservationId] = []
    handled_source_ids: set[str] = set()
    for task_name, raw_payload in sorted(derived_results.items()):
        payload = json_mapping_or_none(raw_payload)
        if payload is None:
            continue
        context = _task_context(
            repository,
            config=config,
            task_name=task_name,
            payload=payload,
        )
        imported, handled_source_id = _import_one_derived_result(
            repository,
            context=context,
            run_id=run_id,
            started_at=started_at,
        )
        observations.extend(imported)
        if handled_source_id is not None:
            handled_source_ids.add(handled_source_id)

    return DerivedImportResult(
        observations=tuple(observations),
        handled_source_ids=tuple(sorted(handled_source_ids)),
    )


__all__ = ["DerivedImportResult", "import_derived_results"]
