from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from efloud.adapters import (
    CollectionAcquisition,
    HttpAcquisition,
    LocalAcquisition,
    RsyncAcquisition,
    SourceAcquisition,
)
from efloud.collection_recording import record_collection_acquisition
from efloud.derivation import DerivedContext, DerivedResult, derivation_key_for, source_inputs
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository_models import ObservationId, TreeEntry, canonical_json_bytes
from efloud.rsync_reconciliation import reconcile_rsync_inventory
from efloud.sources import HttpSource, LocalSource, RestSource, RsyncSource

if TYPE_CHECKING:
    from efloud.derivation import DerivedTask
    from efloud.inventory import IntegrityExpectation
    from efloud.json_types import JsonObject
    from efloud.planning import PlannedOperation
    from efloud.repository_capabilities import RepositoryWriter
    from efloud.repository_models import OperationId, RunId
    from efloud.runtime import EngineRuntime
    from efloud.sources import Source
    from efloud.validation import ValidationService


type RecordedStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class RecordedOperation:
    status: RecordedStatus
    observation_ids: tuple[ObservationId, ...] = ()
    details: JsonObject = field(default_factory=dict)


def _http_modified_timestamp(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _http_integrity_expectations(
    source: HttpSource | RestSource,
    acquisition: HttpAcquisition,
) -> tuple[IntegrityExpectation, ...]:
    expectations = list(source.expected_integrity)
    seen = {(item.algorithm.lower(), item.digest.lower()) for item in expectations}
    for expectation in acquisition.expected_integrity:
        key = (expectation.algorithm.lower(), expectation.digest.lower())
        if key not in seen:
            expectations.append(expectation)
            seen.add(key)
    return tuple(expectations)


def _record_http(
    repository: RepositoryWriter,
    validation: ValidationService,
    *,
    source: HttpSource | RestSource,
    operation: PlannedOperation,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: HttpAcquisition,
) -> RecordedOperation:
    if acquisition.status == "failed" or acquisition.destination is None:
        return RecordedOperation("failed", details={"error": acquisition.error or "HTTP acquisition failed"})
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
        "adapter_id": source.adapter_id,
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
    evidence: JsonObject = {"adapter": operation.producer.to_dict(), "validation": validation_payload}
    if acquisition.status_code is not None:
        evidence["status_code"] = acquisition.status_code
    if acquisition.etag is not None:
        evidence["etag"] = acquisition.etag
    if acquisition.last_modified is not None:
        evidence["last_modified"] = acquisition.last_modified
    if acquisition.checksum is not None:
        evidence["checksum"] = acquisition.checksum
    snapshot = repository.record_source_snapshot(
        source_id=source.id, run_id=run_id, complete=True, observed_at=acquisition.observed_at, evidence=evidence
    )
    return RecordedOperation(
        "succeeded",
        (observation.observation_id,),
        {
            "observation_id": str(observation.observation_id),
            "snapshot_id": str(snapshot.snapshot_id),
            "validation": validation_payload,
        },
    )


def _local_integrity_expectations(
    source: LocalSource,
    acquisition: LocalAcquisition,
) -> tuple[IntegrityExpectation, ...]:
    expectations = list(source.expected_integrity)
    seen = {(item.algorithm.lower(), item.digest.lower()) for item in expectations}
    for expectation in acquisition.expected_integrity:
        key = (expectation.algorithm.lower(), expectation.digest.lower())
        if key not in seen:
            expectations.append(expectation)
            seen.add(key)
    return tuple(expectations)


def _record_local(
    repository: RepositoryWriter,
    validation: ValidationService,
    *,
    source: LocalSource,
    operation: PlannedOperation,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: LocalAcquisition,
) -> RecordedOperation:
    if acquisition.status == "failed" or acquisition.destination is None:
        return RecordedOperation("failed", details={"error": acquisition.error or "Local acquisition failed"})
    destination = acquisition.destination
    source_path = Path(source.path)
    try:
        content = repository.store_path_content(destination, media_type=acquisition.media_type)
        validation_batch = validation.validate_content(
            content,
            name=source_path.name,
            expectations=_local_integrity_expectations(source, acquisition),
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
        observation = repository.observe_content(
            source.resolved_artifact_key,
            content.content_id,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source.id,
            observed_at=acquisition.observed_at,
            source_path=source_path.name,
            upstream_locator=source_path.as_uri(),
            upstream_modified_at=acquisition.source_modified_at,
            metadata={
                "adapter_id": source.adapter_id,
                "adapter_execution": True,
                "local_import": True,
                "validation": validation_payload,
            },
        )
        evidence: JsonObject = {
            "adapter": operation.producer.to_dict(),
            "validation": validation_payload,
        }
        if acquisition.size_bytes is not None:
            evidence["size_bytes"] = acquisition.size_bytes
        if acquisition.source_modified_at is not None:
            evidence["source_modified_at"] = acquisition.source_modified_at
        snapshot = repository.record_source_snapshot(
            source_id=source.id,
            run_id=run_id,
            complete=True,
            observed_at=acquisition.observed_at,
            evidence=evidence,
        )
        return RecordedOperation(
            "succeeded",
            (observation.observation_id,),
            {
                "observation_id": str(observation.observation_id),
                "snapshot_id": str(snapshot.snapshot_id),
                "validation": validation_payload,
            },
        )
    finally:
        with contextlib.suppress(OSError):
            destination.unlink()


def _safe_local_path(root: Path, relative_path: str) -> Path | None:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*relative.parts).resolve(strict=False)
    return candidate if candidate.is_relative_to(root_resolved) else None


def _record_incomplete_rsync(
    repository: RepositoryWriter,
    *,
    source: RsyncSource,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: RsyncAcquisition,
) -> RecordedOperation:
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
            metadata={"adapter_id": source.adapter_id, "adapter_execution": True, "inventory_complete": False},
            materialization_kind="rsync-mirror",
        )
        observations.append(observation.observation_id)
        entries.append(
            TreeEntry(relative_path, "file", content_id=observation.content_id, byte_size=path.stat().st_size)
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
            "adapter_id": source.adapter_id,
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
        tuple(observations),
        {
            "snapshot_id": str(snapshot.snapshot_id),
            "reconciliation_complete": False,
            "ingested_file_count": len(observations),
            "inventory_error": inventory_error,
        },
    )


def _record_rsync(
    repository: RepositoryWriter,
    *,
    source: RsyncSource,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: RsyncAcquisition,
) -> RecordedOperation:
    if acquisition.status == "failed":
        return RecordedOperation("failed", details={"error": acquisition.error or "rsync acquisition failed"})
    if acquisition.inventory is None or not acquisition.inventory.complete:
        return _record_incomplete_rsync(
            repository, source=source, run_id=run_id, operation_id=operation_id, acquisition=acquisition
        )
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
    return RecordedOperation("succeeded" if result.complete else "failed", result.observations, details)


def _record_collection(
    repository: RepositoryWriter,
    validation: ValidationService,
    *,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: CollectionAcquisition,
) -> RecordedOperation:
    if acquisition.inventory is None:
        return RecordedOperation(
            "failed", details={"error": acquisition.error or "collection acquisition produced no inventory"}
        )
    recorded = record_collection_acquisition(
        repository, validation, acquisition=acquisition, run_id=run_id, operation_id=operation_id
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
    return RecordedOperation("failed" if failed else "succeeded", recorded.observations, details)


def record_source_acquisition(
    repository: RepositoryWriter,
    validation: ValidationService,
    *,
    source: Source,
    operation: PlannedOperation,
    run_id: RunId,
    operation_id: OperationId,
    acquisition: SourceAcquisition,
) -> RecordedOperation:
    """Translate one typed adapter result into validated repository state."""
    if acquisition.source_id != source.id:
        return RecordedOperation(
            "failed", details={"error": f"Adapter returned source {acquisition.source_id!r} for {source.id!r}."}
        )
    if isinstance(acquisition, HttpAcquisition) and isinstance(source, HttpSource | RestSource):
        return _record_http(
            repository,
            validation,
            source=source,
            operation=operation,
            run_id=run_id,
            operation_id=operation_id,
            acquisition=acquisition,
        )
    if isinstance(acquisition, LocalAcquisition) and isinstance(source, LocalSource):
        return _record_local(
            repository,
            validation,
            source=source,
            operation=operation,
            run_id=run_id,
            operation_id=operation_id,
            acquisition=acquisition,
        )
    if isinstance(acquisition, RsyncAcquisition) and isinstance(source, RsyncSource):
        return _record_rsync(
            repository, source=source, run_id=run_id, operation_id=operation_id, acquisition=acquisition
        )
    if isinstance(acquisition, CollectionAcquisition):
        return _record_collection(
            repository, validation, run_id=run_id, operation_id=operation_id, acquisition=acquisition
        )
    return RecordedOperation(
        "failed",
        details={"error": f"Adapter result {type(acquisition).__name__} is incompatible with {type(source).__name__}."},
    )


async def run_derived_operation(
    repository: RepositoryWriter,
    *,
    runtime: EngineRuntime,
    task: DerivedTask,
    run_id: RunId,
    operation_id: OperationId,
) -> RecordedOperation:
    """Execute one canonical exact-input/declared-output derived task."""
    with ReadOnlyRepository(repository.root) as view:
        input_observations = source_inputs(view, tuple(sorted(set(task.input_source_ids))))
        try:
            result = await task.run(context=DerivedContext(view, runtime.root, input_observations))
        except Exception as exc:  # ruff: ignore[blind-except] - extension tasks are isolated operation failure domains.
            return RecordedOperation("failed", details={"error": f"{type(exc).__name__}: {exc}"})
    if not isinstance(result, DerivedResult):
        return RecordedOperation("failed", details={"error": "Derived task must return derivation.DerivedResult."})
    declared = tuple(task.output_names)
    names = tuple(output.name for output in result.outputs)
    if len(set(names)) != len(names) or any(not name for name in names):
        return RecordedOperation("failed", details={"error": "Derived output names must be nonempty and unique."})
    undeclared = sorted(set(names) - set(declared))
    if undeclared:
        return RecordedOperation(
            "failed", details={"error": f"Derived task returned undeclared outputs: {undeclared!r}"}
        )
    output_keys = tuple(f"derived:{task.name}:{name}" for name in declared)
    derivation_key = (
        derivation_key_for(task.spec, outputs=output_keys, inputs=input_observations)
        if task.spec.deterministic
        else None
    )
    observations: list[ObservationId] = []
    for output in result.outputs if result.ok else ():
        output_observation = repository.record_derived_path(
            f"derived:{task.name}:{output.name}",
            output.path,
            derivation_key=derivation_key,
            run_id=run_id,
            operation_id=operation_id,
            inputs=input_observations,
            observed_at=time.time(),
            metadata={"derived_task": task.name, "task_spec": task.spec.to_dict()},
            materialization_kind="derived",
        )
        observations.append(output_observation.observation_id)
    input_ids = tuple(item.observation_id for item in input_observations)
    execution = repository.ingest_bytes(
        f"derived:{task.name}:execution",
        canonical_json_bytes(result.details),
        run_id=run_id,
        operation_id=operation_id,
        observed_at=time.time(),
        media_type="application/json",
        metadata={
            "derived_task": task.name,
            "task_spec": task.spec.to_dict(),
            "derivation_key": str(derivation_key) if derivation_key is not None else None,
        },
        inputs=(*input_ids, *observations),
    )
    observations.append(execution.observation_id)
    return RecordedOperation(
        "succeeded" if result.ok else "failed",
        tuple(observations),
        {
            "execution_observation_id": str(execution.observation_id),
            "derivation_key": str(derivation_key) if derivation_key is not None else None,
        },
    )


__all__ = ["RecordedOperation", "RecordedStatus", "record_source_acquisition", "run_derived_operation"]
