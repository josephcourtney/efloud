from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.derived import RepositoryDerivedTask
from efloud.json_types import JsonMapping, JsonObject, copy_json_mapping, json_mapping_or_none
from efloud.registry import SourceKind
from efloud.repository_models import (
    ArtifactAbsence,
    ArtifactObservation,
    ObservationId,
    OperationId,
    RunId,
    SourceId,
    TreeEntry,
    canonical_json_bytes,
)

if TYPE_CHECKING:
    from efloud.derived import DerivedTask
    from efloud.models import EngineConfig
    from efloud.repository import Repository


@dataclass(frozen=True, slots=True)
class DerivedImportResult:
    observations: tuple[ObservationId, ...]
    handled_source_ids: tuple[str, ...]


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
        if isinstance(state, ArtifactObservation) and state.source_id is not None:
            if str(state.source_id) in wanted:
                observations.append(state.observation_id)
    return tuple(sorted(observations, key=str))


def _input_snapshot_ids(repository: Repository, source_ids: tuple[str, ...]) -> list[str]:
    snapshots: list[str] = []
    for source_id in source_ids:
        snapshot = repository.latest_source_snapshot(source_id)
        if snapshot is not None:
            snapshots.append(str(snapshot.snapshot_id))
    return sorted(snapshots)


def _operation_parameters(
    *,
    task_name: str,
    task_version: str | None,
    task_parameters: JsonObject,
    input_source_ids: tuple[str, ...],
    input_snapshot_ids: list[str],
) -> JsonObject:
    payload: JsonObject = {
        "task": task_name,
        "parameters": dict(task_parameters),
        "input_source_ids": list(input_source_ids),
        "input_snapshot_ids": list(input_snapshot_ids),
    }
    if task_version is not None:
        payload["task_version"] = task_version
    return payload


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


def _previous_collection_items(
    repository: Repository,
    source_id: SourceId,
) -> dict[str, TreeEntry]:
    snapshot = repository.latest_source_snapshot(source_id)
    if snapshot is None or not snapshot.complete or snapshot.tree_id is None:
        return {}
    previous: dict[str, TreeEntry] = {}
    for tree_entry in repository.tree_entries(snapshot.tree_id):
        item_id = tree_entry.metadata.get("item_id")
        if isinstance(item_id, str):
            previous[item_id] = tree_entry
    return previous


def _record_removed_collection_items(
    repository: Repository,
    *,
    source_id: SourceId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    previous: dict[str, TreeEntry],
    current_item_ids: set[str],
    task_name: str,
) -> list[ObservationId]:
    removed: list[ObservationId] = []
    for item_id, old_entry in sorted(previous.items()):
        if item_id in current_item_ids:
            continue
        absence = repository.record_absence(
            f"source:{source_id}:item:{item_id}",
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=observed_at,
            source_path=old_entry.relative_path,
            metadata={
                "collection_task": task_name,
                "item_id": item_id,
                "reason": "removed-from-complete-enumeration",
            },
        )
        removed.append(absence.observation_id)
    return removed


def _record_collection(
    repository: Repository,
    *,
    source_id: SourceId,
    task_name: str,
    payload: JsonMapping,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
) -> tuple[list[ObservationId], str | None]:
    entries = json_mapping_or_none(payload.get("entries")) or {}
    enumeration = json_mapping_or_none(payload.get("enumeration")) or {}
    enumeration_complete = enumeration.get("complete") is True
    request = json_mapping_or_none(payload.get("request")) or {}
    response_mode = request.get("response_mode")
    media_type = "application/json" if response_mode == "json" else None

    previous = _previous_collection_items(repository, source_id) if enumeration_complete else {}
    observations: list[ObservationId] = []
    tree_entries: list[TreeEntry] = []
    current_item_ids: set[str] = set()
    unresolved_count = 0
    absent_count = 0
    content_count = 0

    for key, raw_entry in sorted(entries.items()):
        entry = json_mapping_or_none(raw_entry)
        if entry is None:
            unresolved_count += 1
            continue
        raw_item_id = entry.get("item_id")
        item_id = raw_item_id if isinstance(raw_item_id, str) else key
        current_item_ids.add(item_id)
        relative_path = _collection_relative_path(item_id, entry)
        locator = _collection_locator(entry)
        item_metadata = _collection_item_metadata(item_id, entry, task_name)
        tree_metadata: JsonObject = {"item_id": item_id}
        status = entry.get("status")
        destination = entry.get("dest")

        if status == "ok" and isinstance(destination, str) and Path(destination).is_file():
            observation = repository.ingest_path(
                f"source:{source_id}:item:{item_id}",
                Path(destination),
                run_id=run_id,
                operation_id=operation_id,
                source_id=source_id,
                observed_at=observed_at,
                source_path=relative_path,
                upstream_locator=locator,
                media_type=media_type,
                metadata=item_metadata,
                materialization_kind="compatibility-fanout",
            )
            observations.append(observation.observation_id)
            tree_entries.append(
                TreeEntry(
                    relative_path=relative_path,
                    kind="file",
                    content_id=observation.content_id,
                    byte_size=Path(destination).stat().st_size,
                    metadata=tree_metadata,
                )
            )
            content_count += 1
            continue

        error = entry.get("error")
        if status == "error" and error == "404":
            absence = repository.record_absence(
                f"source:{source_id}:item:{item_id}",
                run_id=run_id,
                operation_id=operation_id,
                source_id=source_id,
                observed_at=observed_at,
                source_path=relative_path,
                upstream_locator=locator,
                metadata={**item_metadata, "http_status": 404},
            )
            observations.append(absence.observation_id)
            tree_entries.append(
                TreeEntry(
                    relative_path=relative_path,
                    kind="absent",
                    metadata=tree_metadata,
                )
            )
            absent_count += 1
            continue

        error_text = error if isinstance(error, str) else "collection item was not materialized"
        tree_entries.append(
            TreeEntry(
                relative_path=relative_path,
                kind="unresolved",
                metadata={"item_id": item_id, "error": error_text},
            )
        )
        unresolved_count += 1

    removed = _record_removed_collection_items(
        repository,
        source_id=source_id,
        run_id=run_id,
        operation_id=operation_id,
        observed_at=observed_at,
        previous=previous,
        current_item_ids=current_item_ids,
        task_name=task_name,
    ) if enumeration_complete else []
    observations.extend(removed)

    snapshot = repository.record_tree_snapshot(
        source_id=source_id,
        run_id=run_id,
        entries=tree_entries,
        complete=enumeration_complete,
        observed_at=observed_at,
        evidence={
            "collection": True,
            "task": task_name,
            "enumeration_complete": enumeration_complete,
            "enumerated_item_count": len(current_item_ids),
            "content_item_count": content_count,
            "absent_item_count": absent_count,
            "unresolved_item_count": unresolved_count,
            "removed_item_count": len(removed),
            "acquisition_complete": unresolved_count == 0,
        },
    )
    return observations, str(snapshot.snapshot_id)


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

    source_by_id = {source.id: source for source in config.sources}
    for task_name, raw_payload in sorted(derived_results.items()):
        payload = json_mapping_or_none(raw_payload)
        if payload is None:
            continue
        task = _task_by_name(config, task_name)
        task_version, input_source_ids, task_parameters = _task_metadata(task)
        input_ids = _current_inputs(repository, input_source_ids)
        input_snapshot_ids = _input_snapshot_ids(repository, input_source_ids)

        payload_source_id = payload.get("source_id")
        source = source_by_id.get(payload_source_id) if isinstance(payload_source_id, str) else None
        source_id = SourceId(source.id) if source is not None else None
        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source_id,
            kind="derived",
            subject=task_name,
            started_at=started_at,
            parameters=_operation_parameters(
                task_name=task_name,
                task_version=task_version,
                task_parameters=task_parameters,
                input_source_ids=input_source_ids,
                input_snapshot_ids=input_snapshot_ids,
            ),
        )

        task_metadata: JsonObject = {
            "task": task_name,
            "input_snapshot_ids": input_snapshot_ids,
            "provenance_complete": task is not None and isinstance(task, RepositoryDerivedTask),
        }
        if task_version is not None:
            task_metadata["task_version"] = task_version

        collection_snapshot_id: str | None = None
        if source is not None and source.kind is SourceKind.REST_BASE:
            collection_observations, collection_snapshot_id = _record_collection(
                repository,
                source_id=SourceId(source.id),
                task_name=task_name,
                payload=payload,
                run_id=run_id,
                operation_id=operation_id,
                observed_at=started_at,
            )
            observations.extend(collection_observations)
            handled_source_ids.add(source.id)
            task_metadata["collection_snapshot_id"] = collection_snapshot_id

        output_id = _record_top_level_output(
            repository,
            task_name=task_name,
            payload=payload,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=started_at,
            inputs=input_ids,
            task_metadata=task_metadata,
        )
        if output_id is not None:
            observations.append(output_id)

        result_inputs = list(input_ids)
        if output_id is not None:
            result_inputs.append(output_id)
        result_observation = repository.ingest_bytes(
            f"derived:{task_name}:result",
            canonical_json_bytes(copy_json_mapping(payload)),
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=started_at,
            media_type="application/json",
            metadata=task_metadata,
            inputs=tuple(result_inputs),
        )
        observations.append(result_observation.observation_id)

        status = _result_status(payload)
        details: JsonObject = {
            "result_observation_id": str(result_observation.observation_id),
            "input_observation_count": len(input_ids),
        }
        if collection_snapshot_id is not None:
            details["collection_snapshot_id"] = collection_snapshot_id
        repository.finish_operation(operation_id, status=status, details=details)

    return DerivedImportResult(
        observations=tuple(observations),
        handled_source_ids=tuple(sorted(handled_source_ids)),
    )


__all__ = ["DerivedImportResult", "import_derived_results"]
