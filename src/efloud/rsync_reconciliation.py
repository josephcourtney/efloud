from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from efloud.reconciliation import PreviousInventoryItem, ReconciliationDecision, reconcile_inventory
from efloud.repository_models import ObservationId, OperationId, RunId, SourceId, TreeEntry
from efloud.transport.rsync_inventory import rsync_change_token, rsync_source_inventory

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.repository import Repository
    from efloud.repository_models import SourceSnapshot
    from efloud.transport.rsync_inventory import RsyncInventory, RsyncInventoryEntry


@dataclass(frozen=True, slots=True)
class RsyncReconciliationResult:
    complete: bool
    snapshot_id: str
    observations: tuple[ObservationId, ...]
    ingested_file_count: int
    reused_content_count: int
    absence_count: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _ReconciliationContext:
    repository: Repository
    source_id: SourceId
    run_id: RunId
    operation_id: OperationId
    local_root: Path
    observed_at: float
    upstream_root: str


@dataclass(frozen=True, slots=True)
class _EntryResult:
    tree_entry: TreeEntry
    observation_id: ObservationId | None = None
    ingested: bool = False
    reused: bool = False


def _safe_local_path(root: Path, relative_path: str) -> Path | None:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*relative.parts).resolve(strict=False)
    return candidate if candidate.is_relative_to(root_resolved) else None


def _path_in_scope(path: str, scope: tuple[str, ...]) -> bool:
    if not scope:
        return True
    normalized = path.strip("/")
    return any(
        normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/")
        for item in scope
    )


def _baseline_snapshot(
    repository: Repository,
    source_id: SourceId,
    scope: tuple[str, ...],
) -> SourceSnapshot | None:
    for snapshot in repository.metadata.source_snapshots_for(source_id, limit=200):
        if snapshot.tree_id is None:
            continue
        if snapshot.evidence.get("reconciliation_complete") is not True:
            continue
        if snapshot.complete or snapshot.scope == scope:
            return snapshot
    return None


def _tree_metadata(entry: RsyncInventoryEntry) -> JsonObject:
    metadata: JsonObject = {}
    if entry.modified is not None:
        metadata["rsync_modified"] = entry.modified
    return metadata


def _observe_existing_content(
    context: _ReconciliationContext,
    *,
    previous: PreviousInventoryItem,
    source_path: str,
    upstream_locator: str,
    local_path: Path,
):
    if previous.content_id is None:
        return None
    try:
        return context.repository.observe_content(
            previous.artifact_key,
            previous.content_id,
            run_id=context.run_id,
            operation_id=context.operation_id,
            source_id=context.source_id,
            observed_at=context.observed_at,
            source_path=source_path,
            upstream_locator=upstream_locator,
            metadata={
                "transport": "RSYNC",
                "inventory_observation": True,
                "content_reused": True,
            },
            materialization_kind="rsync-mirror",
            materialization_path=local_path,
        )
    except KeyError:
        return None


def _incomplete_result(
    repository: Repository,
    *,
    source_id: SourceId,
    run_id: RunId,
    inventory: RsyncInventory,
    observed_at: float,
    error: str,
) -> RsyncReconciliationResult:
    snapshot = repository.record_source_snapshot(
        source_id=source_id,
        run_id=run_id,
        complete=False,
        scope=inventory.scope,
        observed_at=observed_at,
        evidence={
            "transport": "RSYNC",
            "inventory_model": "source-inventory-v1",
            "reconciliation_complete": False,
            "enumeration_complete": inventory.complete,
            "error": error,
        },
    )
    return RsyncReconciliationResult(
        complete=False,
        snapshot_id=str(snapshot.snapshot_id),
        observations=(),
        ingested_file_count=0,
        reused_content_count=0,
        absence_count=0,
        error=error,
    )


def _validate_inventory(
    inventory: RsyncInventory,
    local_root: Path,
) -> tuple[dict[str, RsyncInventoryEntry], dict[str, Path], str | None]:
    current_entries = {entry.relative_path: entry for entry in inventory.entries}
    if len(current_entries) != len(inventory.entries):
        return {}, {}, "rsync inventory contains duplicate paths"

    local_paths: dict[str, Path] = {}
    for entry in inventory.entries:
        if not _path_in_scope(entry.relative_path, inventory.scope):
            return {}, {}, f"inventory path is outside declared scope: {entry.relative_path}"
        if entry.kind != "file":
            continue
        local_path = _safe_local_path(local_root, entry.relative_path)
        if local_path is None or not local_path.is_file():
            return {}, {}, f"enumerated file is not materialized locally: {entry.relative_path}"
        local_paths[entry.relative_path] = local_path
    return current_entries, local_paths, None


def _previous_items(
    repository: Repository,
    source_id: SourceId,
    scope: tuple[str, ...],
) -> tuple[PreviousInventoryItem, ...]:
    baseline = _baseline_snapshot(repository, source_id, scope)
    if baseline is None or baseline.tree_id is None:
        return ()
    items: list[PreviousInventoryItem] = []
    for entry in repository.tree_entries(baseline.tree_id):
        if not _path_in_scope(entry.relative_path, scope):
            continue
        modified = entry.metadata.get("rsync_modified")
        items.append(
            PreviousInventoryItem(
                item_id=entry.relative_path,
                artifact_key=f"source:{source_id}:path:{entry.relative_path}",
                content_id=entry.content_id,
                source_path=entry.relative_path,
                change_token=rsync_change_token(
                    kind=entry.kind,
                    byte_size=entry.byte_size,
                    modified=modified if isinstance(modified, str) else None,
                    target=entry.target,
                ),
                metadata={"kind": entry.kind},
            )
        )
    return tuple(items)


def _file_entry_result(
    context: _ReconciliationContext,
    *,
    entry: RsyncInventoryEntry,
    local_path: Path,
    decision: ReconciliationDecision,
) -> _EntryResult:
    relative_path = entry.relative_path
    upstream_locator = f"{context.upstream_root.rstrip('/')}/{relative_path}"
    observation = None
    reused = False
    if decision.state == "unchanged" and decision.previous is not None:
        observation = _observe_existing_content(
            context,
            previous=decision.previous,
            source_path=relative_path,
            upstream_locator=upstream_locator,
            local_path=local_path,
        )
        reused = observation is not None
    if observation is None:
        observation = context.repository.ingest_path(
            decision.artifact_key,
            local_path,
            run_id=context.run_id,
            operation_id=context.operation_id,
            source_id=context.source_id,
            observed_at=context.observed_at,
            source_path=relative_path,
            upstream_locator=upstream_locator,
            metadata={"transport": "RSYNC", "inventory_observation": True},
            materialization_kind="rsync-mirror",
        )
    return _EntryResult(
        tree_entry=TreeEntry(
            relative_path=relative_path,
            kind="file",
            content_id=observation.content_id,
            byte_size=entry.byte_size,
            metadata=_tree_metadata(entry),
        ),
        observation_id=observation.observation_id,
        ingested=not reused,
        reused=reused,
    )


def _entry_result(
    context: _ReconciliationContext,
    *,
    entry: RsyncInventoryEntry,
    local_paths: dict[str, Path],
    decision: ReconciliationDecision,
) -> _EntryResult:
    metadata = _tree_metadata(entry)
    if entry.kind == "directory":
        return _EntryResult(TreeEntry(entry.relative_path, "directory", metadata=metadata))
    if entry.kind == "symlink":
        return _EntryResult(
            TreeEntry(
                relative_path=entry.relative_path,
                kind="symlink",
                target=entry.target,
                metadata=metadata,
            )
        )
    return _file_entry_result(
        context,
        entry=entry,
        local_path=local_paths[entry.relative_path],
        decision=decision,
    )


def _record_absences(
    context: _ReconciliationContext,
    decisions: tuple[ReconciliationDecision, ...],
) -> tuple[ObservationId, ...]:
    observations: list[ObservationId] = []
    for decision in decisions:
        if decision.state != "absent" or decision.previous is None:
            continue
        if decision.previous.metadata.get("kind") != "file":
            continue
        source_path = decision.previous.source_path
        absence = context.repository.record_absence(
            decision.artifact_key,
            run_id=context.run_id,
            operation_id=context.operation_id,
            source_id=context.source_id,
            observed_at=context.observed_at,
            source_path=source_path,
            upstream_locator=(
                f"{context.upstream_root.rstrip('/')}/{source_path}" if source_path is not None else None
            ),
            metadata={"transport": "RSYNC", "inventory_observation": True},
        )
        observations.append(absence.observation_id)
    return tuple(observations)


def _record_success_snapshot(
    context: _ReconciliationContext,
    *,
    inventory: RsyncInventory,
    tree_entries: list[TreeEntry],
    decisions: tuple[ReconciliationDecision, ...],
    ingested: int,
    reused: int,
    absence_count: int,
) -> str:
    counts = {
        state: sum(decision.state == state for decision in decisions)
        for state in ("new", "changed", "unchanged", "absent")
    }
    evidence: JsonObject = {
        "transport": "RSYNC",
        "inventory_model": "source-inventory-v1",
        "reconciliation_complete": inventory.complete,
        "scope_complete": inventory.complete,
        "inventory_entry_count": len(inventory.entries),
        "ingested_file_count": ingested,
        "reused_content_count": reused,
        "absence_count": absence_count,
        "classification_counts": counts,
    }
    if inventory.error is not None:
        evidence["inventory_error"] = inventory.error
    snapshot = context.repository.record_tree_snapshot(
        source_id=context.source_id,
        run_id=context.run_id,
        entries=tree_entries,
        complete=inventory.complete and not inventory.scope,
        scope=inventory.scope,
        observed_at=context.observed_at,
        evidence=evidence,
    )
    return str(snapshot.snapshot_id)


def reconcile_rsync_inventory(
    repository: Repository,
    *,
    source_id: SourceId | str,
    run_id: RunId,
    operation_id: OperationId,
    local_root: Path,
    inventory: RsyncInventory,
    observed_at: float,
    upstream_root: str,
) -> RsyncReconciliationResult:
    normalized_source = SourceId(str(source_id))
    current_entries, local_paths, validation_error = _validate_inventory(inventory, local_root)
    if validation_error is not None:
        return _incomplete_result(
            repository,
            source_id=normalized_source,
            run_id=run_id,
            inventory=inventory,
            observed_at=observed_at,
            error=validation_error,
        )

    source_inventory = rsync_source_inventory(
        inventory,
        source_id=normalized_source,
        observed_at=observed_at,
        upstream_root=upstream_root,
    )
    reconciliation = reconcile_inventory(
        source_inventory,
        _previous_items(repository, normalized_source, inventory.scope),
    )
    decisions_by_id = {decision.item_id: decision for decision in reconciliation.decisions}
    context = _ReconciliationContext(
        repository=repository,
        source_id=normalized_source,
        run_id=run_id,
        operation_id=operation_id,
        local_root=local_root,
        observed_at=observed_at,
        upstream_root=upstream_root,
    )
    observations: list[ObservationId] = []
    tree_entries: list[TreeEntry] = []
    ingested = 0
    reused = 0

    for relative_path in sorted(current_entries):
        decision = decisions_by_id[relative_path]
        result = _entry_result(
            context,
            entry=current_entries[relative_path],
            local_paths=local_paths,
            decision=decision,
        )
        tree_entries.append(result.tree_entry)
        if result.observation_id is not None:
            observations.append(result.observation_id)
        ingested += int(result.ingested)
        reused += int(result.reused)

    absences = _record_absences(context, reconciliation.decisions)
    observations.extend(absences)
    snapshot_id = _record_success_snapshot(
        context,
        inventory=inventory,
        tree_entries=tree_entries,
        decisions=reconciliation.decisions,
        ingested=ingested,
        reused=reused,
        absence_count=len(absences),
    )
    return RsyncReconciliationResult(
        complete=inventory.complete,
        snapshot_id=snapshot_id,
        observations=tuple(observations),
        ingested_file_count=ingested,
        reused_content_count=reused,
        absence_count=len(absences),
        error=inventory.error,
    )


__all__ = ["RsyncReconciliationResult", "reconcile_rsync_inventory"]
