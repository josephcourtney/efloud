from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from efloud.repository_models import (
    ArtifactObservation,
    ObservationId,
    OperationId,
    RunId,
    SourceId,
    TreeEntry,
)

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
        normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/") for item in scope
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


def _unchanged(previous: TreeEntry | None, current: RsyncInventoryEntry) -> bool:
    if previous is None or previous.kind != "file" or previous.content_id is None:
        return False
    if current.kind != "file" or previous.byte_size != current.byte_size:
        return False
    previous_modified = previous.metadata.get("rsync_modified")
    return current.modified is not None and previous_modified == current.modified


def _observe_existing_content(
    context: _ReconciliationContext,
    *,
    previous: TreeEntry,
    artifact_key: str,
    source_path: str,
    upstream_locator: str,
    local_path: Path,
) -> ArtifactObservation | None:
    if previous.content_id is None:
        return None
    try:
        return context.repository.observe_content(
            artifact_key,
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
    if not inventory.complete:
        return {}, {}, inventory.error or "rsync inventory was incomplete"

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


def _previous_entries(
    repository: Repository,
    source_id: SourceId,
    scope: tuple[str, ...],
) -> dict[str, TreeEntry]:
    baseline = _baseline_snapshot(repository, source_id, scope)
    if baseline is None or baseline.tree_id is None:
        return {}
    return {
        entry.relative_path: entry
        for entry in repository.tree_entries(baseline.tree_id)
        if _path_in_scope(entry.relative_path, scope)
    }


def _file_entry_result(
    context: _ReconciliationContext,
    *,
    entry: RsyncInventoryEntry,
    local_path: Path,
    previous: TreeEntry | None,
) -> _EntryResult:
    relative_path = entry.relative_path
    artifact_key = f"source:{context.source_id}:path:{relative_path}"
    upstream_locator = f"{context.upstream_root.rstrip('/')}/{relative_path}"
    observation = None
    reused = False
    if _unchanged(previous, entry) and previous is not None:
        observation = _observe_existing_content(
            context,
            previous=previous,
            artifact_key=artifact_key,
            source_path=relative_path,
            upstream_locator=upstream_locator,
            local_path=local_path,
        )
        reused = observation is not None
    if observation is None:
        observation = context.repository.ingest_path(
            artifact_key,
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
    previous: TreeEntry | None,
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
        previous=previous,
    )


def _record_absences(
    context: _ReconciliationContext,
    *,
    previous_entries: dict[str, TreeEntry],
    current_entries: dict[str, RsyncInventoryEntry],
) -> tuple[ObservationId, ...]:
    observations: list[ObservationId] = []
    for relative_path, previous in sorted(previous_entries.items()):
        if relative_path in current_entries or previous.kind != "file":
            continue
        absence = context.repository.record_absence(
            f"source:{context.source_id}:path:{relative_path}",
            run_id=context.run_id,
            operation_id=context.operation_id,
            source_id=context.source_id,
            observed_at=context.observed_at,
            source_path=relative_path,
            upstream_locator=f"{context.upstream_root.rstrip('/')}/{relative_path}",
            metadata={"transport": "RSYNC", "inventory_observation": True},
        )
        observations.append(absence.observation_id)
    return tuple(observations)


def _record_success_snapshot(
    context: _ReconciliationContext,
    *,
    inventory: RsyncInventory,
    tree_entries: list[TreeEntry],
    ingested: int,
    reused: int,
    absence_count: int,
) -> str:
    snapshot = context.repository.record_tree_snapshot(
        source_id=context.source_id,
        run_id=context.run_id,
        entries=tree_entries,
        complete=not inventory.scope,
        scope=inventory.scope,
        observed_at=context.observed_at,
        evidence={
            "transport": "RSYNC",
            "reconciliation_complete": True,
            "scope_complete": True,
            "inventory_entry_count": len(inventory.entries),
            "ingested_file_count": ingested,
            "reused_content_count": reused,
            "absence_count": absence_count,
        },
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

    context = _ReconciliationContext(
        repository=repository,
        source_id=normalized_source,
        run_id=run_id,
        operation_id=operation_id,
        local_root=local_root,
        observed_at=observed_at,
        upstream_root=upstream_root,
    )
    previous_entries = _previous_entries(repository, normalized_source, inventory.scope)
    observations: list[ObservationId] = []
    tree_entries: list[TreeEntry] = []
    ingested = 0
    reused = 0

    for relative_path in sorted(current_entries):
        result = _entry_result(
            context,
            entry=current_entries[relative_path],
            local_paths=local_paths,
            previous=previous_entries.get(relative_path),
        )
        tree_entries.append(result.tree_entry)
        if result.observation_id is not None:
            observations.append(result.observation_id)
        ingested += int(result.ingested)
        reused += int(result.reused)

    absences = _record_absences(
        context,
        previous_entries=previous_entries,
        current_entries=current_entries,
    )
    observations.extend(absences)
    snapshot_id = _record_success_snapshot(
        context,
        inventory=inventory,
        tree_entries=tree_entries,
        ingested=ingested,
        reused=reused,
        absence_count=len(absences),
    )
    return RsyncReconciliationResult(
        complete=True,
        snapshot_id=snapshot_id,
        observations=tuple(observations),
        ingested_file_count=ingested,
        reused_content_count=reused,
        absence_count=len(absences),
    )


__all__ = ["RsyncReconciliationResult", "reconcile_rsync_inventory"]
