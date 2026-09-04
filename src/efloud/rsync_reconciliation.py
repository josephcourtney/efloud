from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from efloud.json_types import JsonObject
from efloud.repository_models import (
    ArtifactObservation,
    ObservationId,
    OperationId,
    RunId,
    SourceId,
    TreeEntry,
)
from efloud.transport.rsync_inventory import RsyncInventory, RsyncInventoryEntry

if TYPE_CHECKING:
    from efloud.repository import Repository
    from efloud.repository_models import SourceSnapshot


@dataclass(frozen=True, slots=True)
class RsyncReconciliationResult:
    complete: bool
    snapshot_id: str
    observations: tuple[ObservationId, ...]
    ingested_file_count: int
    reused_content_count: int
    absence_count: int
    error: str | None = None


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


def _unchanged(previous: TreeEntry | None, current: RsyncInventoryEntry) -> bool:
    if previous is None or previous.kind != "file" or previous.content_id is None:
        return False
    if current.kind != "file" or previous.byte_size != current.byte_size:
        return False
    previous_modified = previous.metadata.get("rsync_modified")
    return current.modified is not None and previous_modified == current.modified


def _observe_existing_content(
    repository: Repository,
    *,
    previous: TreeEntry,
    artifact_key: str,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    source_path: str,
    upstream_locator: str,
    local_path: Path,
) -> ArtifactObservation | None:
    if previous.content_id is None:
        return None
    try:
        return repository.observe_content(
            artifact_key,
            previous.content_id,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=observed_at,
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
    if not inventory.complete:
        return _incomplete_result(
            repository,
            source_id=normalized_source,
            run_id=run_id,
            inventory=inventory,
            observed_at=observed_at,
            error=inventory.error or "rsync inventory was incomplete",
        )

    current_entries = {entry.relative_path: entry for entry in inventory.entries}
    if len(current_entries) != len(inventory.entries):
        return _incomplete_result(
            repository,
            source_id=normalized_source,
            run_id=run_id,
            inventory=inventory,
            observed_at=observed_at,
            error="rsync inventory contains duplicate paths",
        )

    local_paths: dict[str, Path] = {}
    for entry in inventory.entries:
        if not _path_in_scope(entry.relative_path, inventory.scope):
            return _incomplete_result(
                repository,
                source_id=normalized_source,
                run_id=run_id,
                inventory=inventory,
                observed_at=observed_at,
                error=f"inventory path is outside declared scope: {entry.relative_path}",
            )
        if entry.kind != "file":
            continue
        local_path = _safe_local_path(local_root, entry.relative_path)
        if local_path is None or not local_path.is_file():
            return _incomplete_result(
                repository,
                source_id=normalized_source,
                run_id=run_id,
                inventory=inventory,
                observed_at=observed_at,
                error=f"enumerated file is not materialized locally: {entry.relative_path}",
            )
        local_paths[entry.relative_path] = local_path

    baseline = _baseline_snapshot(repository, normalized_source, inventory.scope)
    previous_entries: dict[str, TreeEntry] = {}
    if baseline is not None and baseline.tree_id is not None:
        previous_entries = {
            entry.relative_path: entry
            for entry in repository.tree_entries(baseline.tree_id)
            if _path_in_scope(entry.relative_path, inventory.scope)
        }

    observations: list[ObservationId] = []
    tree_entries: list[TreeEntry] = []
    ingested = 0
    reused = 0
    for relative_path in sorted(current_entries):
        entry = current_entries[relative_path]
        metadata = _tree_metadata(entry)
        if entry.kind == "directory":
            tree_entries.append(
                TreeEntry(relative_path=relative_path, kind="directory", metadata=metadata)
            )
            continue
        if entry.kind == "symlink":
            tree_entries.append(
                TreeEntry(
                    relative_path=relative_path,
                    kind="symlink",
                    target=entry.target,
                    metadata=metadata,
                )
            )
            continue

        local_path = local_paths[relative_path]
        artifact_key = f"source:{normalized_source}:path:{relative_path}"
        upstream_locator = f"{upstream_root.rstrip('/')}/{relative_path}"
        previous = previous_entries.get(relative_path)
        observation: ArtifactObservation | None = None
        if _unchanged(previous, entry) and previous is not None:
            observation = _observe_existing_content(
                repository,
                previous=previous,
                artifact_key=artifact_key,
                source_id=normalized_source,
                run_id=run_id,
                operation_id=operation_id,
                observed_at=observed_at,
                source_path=relative_path,
                upstream_locator=upstream_locator,
                local_path=local_path,
            )
            if observation is not None:
                reused += 1
        if observation is None:
            observation = repository.ingest_path(
                artifact_key,
                local_path,
                run_id=run_id,
                operation_id=operation_id,
                source_id=normalized_source,
                observed_at=observed_at,
                source_path=relative_path,
                upstream_locator=upstream_locator,
                metadata={"transport": "RSYNC", "inventory_observation": True},
                materialization_kind="rsync-mirror",
            )
            ingested += 1
        observations.append(observation.observation_id)
        tree_entries.append(
            TreeEntry(
                relative_path=relative_path,
                kind="file",
                content_id=observation.content_id,
                byte_size=entry.byte_size,
                metadata=metadata,
            )
        )

    absence_count = 0
    for relative_path, previous in sorted(previous_entries.items()):
        if relative_path in current_entries or previous.kind != "file":
            continue
        absence = repository.record_absence(
            f"source:{normalized_source}:path:{relative_path}",
            run_id=run_id,
            operation_id=operation_id,
            source_id=normalized_source,
            observed_at=observed_at,
            source_path=relative_path,
            upstream_locator=f"{upstream_root.rstrip('/')}/{relative_path}",
            metadata={"transport": "RSYNC", "inventory_observation": True},
        )
        observations.append(absence.observation_id)
        absence_count += 1

    snapshot = repository.record_tree_snapshot(
        source_id=normalized_source,
        run_id=run_id,
        entries=tree_entries,
        complete=not inventory.scope,
        scope=inventory.scope,
        observed_at=observed_at,
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
    return RsyncReconciliationResult(
        complete=True,
        snapshot_id=str(snapshot.snapshot_id),
        observations=tuple(observations),
        ingested_file_count=ingested,
        reused_content_count=reused,
        absence_count=absence_count,
    )


__all__ = ["RsyncReconciliationResult", "reconcile_rsync_inventory"]
