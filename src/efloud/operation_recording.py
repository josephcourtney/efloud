from __future__ import annotations

import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from efloud.adapters import CollectionAcquisition, HttpAcquisition, RsyncAcquisition, SourceAcquisition
from efloud.collection_recording import record_collection_acquisition
from efloud.derived import DerivedResult, ExtensionContext, RepositoryDerivedTask, source_inputs
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository_models import ObservationId, TreeEntry, canonical_json_bytes
from efloud.rsync_reconciliation import reconcile_rsync_inventory

if TYPE_CHECKING:
    from efloud.derived import DerivedTask
    from efloud.inventory import IntegrityExpectation
    from efloud.json_types import JsonObject
    from efloud.models import EngineConfig
    from efloud.planning import PlannedOperation
    from efloud.registry import SourceDefinition
    from efloud.repository import Repository
    from efloud.repository_models import OperationId, RunId
    from efloud.validation import ValidationService


type RecordedStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class RecordedOperation:
    status: RecordedStatus
    observation_ids: tuple[ObservationId, ...] = ()
    details: JsonObject = field(default_factory=dict)


def _source_by_id(config: EngineConfig, source_id: str) -> SourceDefinition:
    source = next((candidate for candidate in config.sources if candidate.id == source_id), None)
    if source is None:
        msg = f"Adapter returned an unknown source identifier: {source_id!r}"
        raise KeyError(msg)
    return source


def _http_modified_timestamp(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _http_integrity_expectations(
    source: SourceDefinition,
    acquisition: HttpAcquisition,
) -> tuple[IntegrityExpectation, ...]:
    """Merge configured and adapter assertions, with configured expectations authoritative."""
    expectations = list(source.expected_integrity)
    seen = {(item.algorithm.lower(), item.digest.lower()) for item in expectations}
    for expectation in acquisition.expected_integrity:
        key = (expectation.algorithm.lower(), expectation.digest.lower())
        if key in seen:
            continue
        expectations.append(expectation)
        seen.add(key)
    return tuple(expectations)


def _record_http(
    repository: Repository,
    validation: ValidationService,
    *,
    config: EngineConfig,
    operation: PlannedOperation,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: HttpAcquisition,
) -> RecordedOperation:
    if acquisition.status == "failed" or acquisition.destination is None:
        return RecordedOperation("failed", details={"error": acquisition.error or "HTTP acquisition failed"})

    source = _source_by_id(config, acquisition.source_id)
    content = repository.store_path_content(acquisition.destination, media_type=acquisition.media_type)
    validation_batch = validation.validate_content(
        content,
        name=acquisition.destination.name,
        expectations=_http_integrity_expectations(source, acquisition),
        checked_at=acquisition.observed_at,
    )
    validation_payload = validation_batch.to_dict()
    if not validation_batch.ok:
        return RecordedOperation(
            "failed",
            details={
                "error": "required validation failed",
                "content_id": str(content.content_id),
                "validation": validation_payload,
            },
        )

    metadata: JsonObject = {
        "transport": source.kind.value,
        "adapter_execution": True,
        "validation": validation_payload,
    }
    if acquisition.status_code is not None:
        metadata["status_code"] = acquisition.status_code
    if acquisition.checksum is not None:
        metadata["transport_checksum"] = acquisition.checksum
    observation = repository.observe_content(
        f"source:{source.id}",
        content.content_id,
        run_id=run_id,
        operation_id=operation_id,
        source_id=source.id,
        observed_at=acquisition.observed_at,
        upstream_locator=source.url,
        upstream_modified_at=_http_modified_timestamp(acquisition.last_modified),
        upstream_version=acquisition.etag,
        metadata=metadata,
        materialization_kind="http",
        materialization_path=acquisition.destination,
    )
    evidence: JsonObject = {
        "adapter": operation.producer.to_dict(),
        "validation": validation_payload,
    }
    if acquisition.status_code is not None:
        evidence["status_code"] = acquisition.status_code
    if acquisition.etag is not None:
        evidence["etag"] = acquisition.etag
    if acquisition.last_modified is not None:
        evidence["last_modified"] = acquisition.last_modified
    if acquisition.checksum is not None:
        evidence["checksum"] = acquisition.checksum
    snapshot = repository.record_source_snapshot(
        source_id=source.id,
        run_id=run_id,
        complete=True,
        observed_at=acquisition.observed_at,
        evidence=evidence,
    )
    return RecordedOperation(
        "succeeded",
        observation_ids=(observation.observation_id,),
        details={
            "observation_id": str(observation.observation_id),
            "snapshot_id": str(snapshot.snapshot_id),
            "validation": validation_payload,
        },
    )


def _safe_local_path(root: Path, relative_path: str) -> Path | None:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*relative.parts).resolve(strict=False)
    return candidate if candidate.is_relative_to(root_resolved) else None


def _record_incomplete_rsync(
    repository: Repository,
    *,
    config: EngineConfig,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: RsyncAcquisition,
) -> RecordedOperation:
    source = _source_by_id(config, acquisition.source_id)
    observations: list[ObservationId] = []
    entries: list[TreeEntry] = []
    for relative_path in acquisition.updated_paths:
        path = _safe_local_path(acquisition.local_root, relative_path)
        if path is None or not path.exists():
            continue
        if path.is_symlink():
            entries.append(TreeEntry(relative_path=relative_path, kind="symlink", target=path.readlink().as_posix()))
            continue
        if path.is_dir():
            entries.append(TreeEntry(relative_path=relative_path, kind="directory"))
            continue
        if not path.is_file():
            continue
        observation = repository.ingest_path(
            f"source:{source.id}:path:{relative_path}",
            path,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source.id,
            observed_at=acquisition.observed_at,
            source_path=relative_path,
            upstream_locator=f"{source.url.rstrip('/')}/{relative_path}",
            metadata={"transport": "RSYNC", "adapter_execution": True, "inventory_complete": False},
            materialization_kind="rsync-mirror",
        )
        observations.append(observation.observation_id)
        entries.append(
            TreeEntry(
                relative_path=relative_path,
                kind="file",
                content_id=observation.content_id,
                byte_size=path.stat().st_size,
            )
        )
    inventory_error = (
        acquisition.inventory.error
        if acquisition.inventory is not None and acquisition.inventory.error is not None
        else acquisition.error or "rsync inventory unavailable"
    )
    snapshot = repository.record_tree_snapshot(
        source_id=source.id,
        run_id=run_id,
        entries=entries,
        complete=False,
        scope=acquisition.scope,
        observed_at=acquisition.observed_at,
        evidence={
            "transport": "RSYNC",
            "adapter_execution": True,
            "reconciliation_complete": False,
            "enumeration_complete": False,
            "inventory_error": inventory_error,
            "changed_entry_count": len(acquisition.updated_paths),
            "ingested_file_count": len(observations),
        },
    )
    return RecordedOperation(
        "succeeded",
        observation_ids=tuple(observations),
        details={
            "snapshot_id": str(snapshot.snapshot_id),
            "reconciliation_complete": False,
            "ingested_file_count": len(observations),
            "inventory_error": inventory_error,
        },
    )


def _record_rsync(
    repository: Repository,
    *,
    config: EngineConfig,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: RsyncAcquisition,
) -> RecordedOperation:
    if acquisition.status == "failed":
        return RecordedOperation("failed", details={"error": acquisition.error or "rsync acquisition failed"})
    if acquisition.inventory is None or not acquisition.inventory.complete:
        return _record_incomplete_rsync(
            repository,
            config=config,
            run_id=run_id,
            operation_id=operation_id,
            acquisition=acquisition,
        )

    source = _source_by_id(config, acquisition.source_id)
    result = reconcile_rsync_inventory(
        repository,
        source_id=source.id,
        run_id=run_id,
        operation_id=operation_id,
        local_root=acquisition.local_root,
        inventory=acquisition.inventory,
        observed_at=acquisition.observed_at,
        upstream_root=source.url,
    )
    details: JsonObject = {
        "snapshot_id": result.snapshot_id,
        "reconciliation_complete": result.complete,
        "ingested_file_count": result.ingested_file_count,
        "reused_content_count": result.reused_content_count,
        "absence_count": result.absence_count,
    }
    if result.error is not None:
        details["error"] = result.error
    return RecordedOperation(
        "succeeded" if result.complete else "failed",
        observation_ids=result.observations,
        details=details,
    )


def _record_collection(
    repository: Repository,
    validation: ValidationService,
    *,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: CollectionAcquisition,
) -> RecordedOperation:
    if acquisition.payload is None:
        return RecordedOperation(
            "failed",
            details={"error": acquisition.error or "collection acquisition produced no result"},
        )
    recorded = record_collection_acquisition(
        repository,
        validation,
        source_id=acquisition.source_id,
        task_name=acquisition.task_name,
        payload=acquisition.payload,
        run_id=run_id,
        operation_id=operation_id,
        observed_at=acquisition.observed_at,
        input_observation_ids=acquisition.input_observation_ids,
    )
    failed = acquisition.status == "failed" or recorded.unresolved_count > 0
    details: JsonObject = {
        "snapshot_id": recorded.snapshot_id,
        "execution_observation_id": str(recorded.execution_observation_id),
        "content_count": recorded.content_count,
        "absence_count": recorded.absence_count,
        "unresolved_count": recorded.unresolved_count,
    }
    if acquisition.error is not None:
        details["error"] = acquisition.error
    return RecordedOperation(
        "failed" if failed else "succeeded",
        observation_ids=recorded.observations,
        details=details,
    )


def record_source_acquisition(
    repository: Repository,
    validation: ValidationService,
    *,
    config: EngineConfig,
    operation: PlannedOperation,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: SourceAcquisition,
) -> RecordedOperation:
    """Translate one typed adapter result into validated repository state."""
    if isinstance(acquisition, HttpAcquisition):
        return _record_http(
            repository,
            validation,
            config=config,
            operation=operation,
            run_id=run_id,
            operation_id=operation_id,
            acquisition=acquisition,
        )
    if isinstance(acquisition, RsyncAcquisition):
        return _record_rsync(
            repository,
            config=config,
            run_id=run_id,
            operation_id=operation_id,
            acquisition=acquisition,
        )
    return _record_collection(
        repository,
        validation,
        run_id=run_id,
        operation_id=operation_id,
        acquisition=acquisition,
    )


def _derived_task(config: EngineConfig, name: str) -> DerivedTask | None:
    return next((task for task in config.derived_tasks if task.name == name), None)


async def run_derived_operation(
    repository: Repository,
    *,
    config: EngineConfig,
    operation: PlannedOperation,
    run_id: RunId,
    operation_id: OperationId,
) -> RecordedOperation:
    """Execute and record one configured derived task behind the typed operation boundary."""
    task = _derived_task(config, operation.subject)
    if task is None:
        return RecordedOperation("failed", details={"error": f"Unknown derived task: {operation.subject}"})
    input_source_ids = task.repository_input_source_ids if isinstance(task, RepositoryDerivedTask) else ()
    input_observations = source_inputs(repository, input_source_ids)
    inputs = tuple(item.observation_id for item in input_observations)
    try:
        with ReadOnlyRepository(repository.root) as view:
            result = await task.run(
                context=ExtensionContext(
                    repository=view,
                    workspace=Path(config.root),
                    sources=tuple(config.sources),
                    inputs=input_observations,
                ),
            )
    except Exception as exc:  # ruff: ignore[blind-except] - extension tasks are isolated operation failure domains.
        return RecordedOperation("failed", details={"error": f"{type(exc).__name__}: {exc}"})
    if not isinstance(result, DerivedResult):
        return RecordedOperation("failed", details={"error": "Derived task must return DerivedResult."})
    payload = result.details
    observations: list[ObservationId] = []
    names = [output.name for output in result.outputs]
    if len(set(names)) != len(names) or any(not name for name in names):
        return RecordedOperation("failed", details={"error": "Derived output names must be nonempty and unique."})
    for output in result.outputs if result.ok else ():
        output_observation = repository.ingest_path(
            f"derived:{operation.subject}:{output.name}",
            output.path,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=time.time(),
            metadata={"derived_task": operation.subject, "adapter_execution": True},
            inputs=inputs,
            materialization_kind="derived",
        )
        observations.append(output_observation.observation_id)
    execution_inputs = (*inputs, *observations)
    execution = repository.ingest_bytes(
        f"derived:{operation.subject}:execution",
        canonical_json_bytes(payload),
        run_id=run_id,
        operation_id=operation_id,
        observed_at=time.time(),
        media_type="application/json",
        metadata={"derived_task": operation.subject, "adapter_execution": True},
        inputs=execution_inputs,
    )
    observations.append(execution.observation_id)
    return RecordedOperation(
        "succeeded" if result.ok else "failed",
        observation_ids=tuple(observations),
        details={"execution_observation_id": str(execution.observation_id)},
    )


__all__ = [
    "RecordedOperation",
    "RecordedStatus",
    "record_source_acquisition",
    "run_derived_operation",
]
