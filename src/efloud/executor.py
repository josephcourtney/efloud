from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from efloud.adapters import (
    AdapterExecutionContext,
    AdapterRegistry,
    CollectionAcquisition,
    HttpAcquisition,
    RsyncAcquisition,
)
from efloud.collection_recording import record_collection_acquisition
from efloud.derived import RepositoryDerivedTask
from efloud.json_types import JsonObject, canonical_json_bytes if False else JsonObject
from efloud.json_types import copy_json_mapping, json_mapping_or_none
from efloud.planning import PlannedOperation, SyncPlan
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository_compat import repository_manifest
from efloud.repository_models import ObservationId, OperationId, RunId, SourceId, TreeEntry, canonical_json_bytes
from efloud.rsync_reconciliation import reconcile_rsync_inventory

if TYPE_CHECKING:
    from efloud.models import EngineConfig
    from efloud.repository import Repository


type ExecutionStatus = Literal["not-executed", "succeeded", "failed", "cancelled", "blocked"]


@dataclass(frozen=True, slots=True)
class OperationExecutionResult:
    operation_key: str
    status: ExecutionStatus
    observation_ids: tuple[ObservationId, ...] = ()
    details: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SyncExecutionResult:
    plan_id: str
    run_id: RunId | None
    operations: tuple[OperationExecutionResult, ...]

    @property
    def observations(self) -> tuple[ObservationId, ...]:
        return tuple(observation for operation in self.operations for observation in operation.observation_ids)

    @property
    def skipped_source_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                operation.operation_key.removeprefix("source:")
                for operation in self.operations
                if operation.operation_key.startswith("source:") and operation.status in {"not-executed", "blocked"}
            )
        )

    @property
    def ok(self) -> bool:
        return all(operation.status in {"succeeded", "not-executed"} for operation in self.operations)


@dataclass(frozen=True, slots=True)
class _ExecutionContext:
    config: EngineConfig
    repository: Repository
    adapters: AdapterRegistry
    plan: SyncPlan
    run_id: RunId


def _source_definition_payload(source: SourceDefinition) -> JsonObject:
    payload: JsonObject = {
        "description": source.description,
        "url": source.url,
        "kind": source.kind.value,
        "tags": list(source.tags),
    }
    if source.cache_name is not None:
        payload["cache_name"] = source.cache_name
    if source.local_subpath is not None:
        payload["local_subpath"] = source.local_subpath
    if source.mirror_mode is not None:
        payload["mirror_mode"] = source.mirror_mode.value
    if source.mirror_paths is not None:
        payload["mirror_paths"] = list(source.mirror_paths)
    if source.port is not None:
        payload["port"] = source.port
    if source.include is not None:
        payload["include"] = list(source.include)
    if source.exclude is not None:
        payload["exclude"] = list(source.exclude)
    if source.role is not None:
        payload["role"] = source.role
    return payload


def _source_by_id(config: EngineConfig, source_id: str) -> SourceDefinition:
    source = next((candidate for candidate in config.sources if candidate.id == source_id), None)
    if source is None:
        msg = f"Planned source is not configured: {source_id!r}"
        raise KeyError(msg)
    return source


def _operation_kind(operation: PlannedOperation, source: SourceDefinition | None) -> str:
    if operation.kind == "derived":
        return "derived"
    if source is not None and source.kind is SourceKind.REST_BASE:
        return "collection"
    return source.kind.value.lower() if source is not None else "source"


def _operation_parameters(plan: SyncPlan, operation: PlannedOperation) -> JsonObject:
    payload: JsonObject = {
        **operation.parameters,
        "plan_id": plan.plan_id,
        "plan_operation_key": operation.operation_key,
        "dependencies": list(operation.dependencies),
        "scope": list(operation.scope),
    }
    if operation.refresh is not None:
        payload["refresh"] = operation.refresh.to_dict()
    return payload


def _start_operation(context: _ExecutionContext, operation: PlannedOperation) -> OperationId:
    source = _source_by_id(context.config, operation.source_id) if operation.source_id is not None else None
    return context.repository.start_operation(
        run_id=context.run_id,
        source_id=operation.source_id,
        kind=_operation_kind(operation, source),
        subject=operation.subject,
        producer=operation.producer,
        parameters=_operation_parameters(context.plan, operation),
    )


def _http_modified_timestamp(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _record_http(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
    acquisition: HttpAcquisition,
) -> OperationExecutionResult:
    if acquisition.status == "failed" or acquisition.destination is None:
        details: JsonObject = {"error": acquisition.error or "HTTP acquisition failed"}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)

    source = _source_by_id(context.config, acquisition.source_id)
    metadata: JsonObject = {"transport": source.kind.value, "adapter_execution": True}
    if acquisition.status_code is not None:
        metadata["status_code"] = acquisition.status_code
    if acquisition.checksum is not None:
        metadata["transport_checksum"] = acquisition.checksum
    observation = context.repository.ingest_path(
        f"source:{source.id}",
        acquisition.destination,
        run_id=context.run_id,
        operation_id=operation_id,
        source_id=source.id,
        observed_at=acquisition.observed_at,
        upstream_locator=source.url,
        upstream_modified_at=_http_modified_timestamp(acquisition.last_modified),
        upstream_version=acquisition.etag,
        media_type=acquisition.media_type,
        metadata=metadata,
        materialization_kind="http",
    )
    evidence: JsonObject = {"adapter": operation.producer.to_dict()}
    if acquisition.status_code is not None:
        evidence["status_code"] = acquisition.status_code
    if acquisition.etag is not None:
        evidence["etag"] = acquisition.etag
    if acquisition.last_modified is not None:
        evidence["last_modified"] = acquisition.last_modified
    if acquisition.checksum is not None:
        evidence["checksum"] = acquisition.checksum
    context.repository.record_source_snapshot(
        source_id=source.id,
        run_id=context.run_id,
        complete=True,
        observed_at=acquisition.observed_at,
        evidence=evidence,
    )
    details = {"observation_id": str(observation.observation_id)}
    context.repository.finish_operation(operation_id, status="succeeded", details=details)
    return OperationExecutionResult(
        operation.operation_key,
        "succeeded",
        observation_ids=(observation.observation_id,),
        details=details,
    )


def _safe_local_path(root: Path, relative_path: str) -> Path | None:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*relative.parts).resolve(strict=False)
    return candidate if candidate.is_relative_to(root_resolved) else None


def _record_incomplete_rsync(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
    acquisition: RsyncAcquisition,
) -> OperationExecutionResult:
    source = _source_by_id(context.config, acquisition.source_id)
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
        observation = context.repository.ingest_path(
            f"source:{source.id}:path:{relative_path}",
            path,
            run_id=context.run_id,
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
    snapshot = context.repository.record_tree_snapshot(
        source_id=source.id,
        run_id=context.run_id,
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
    details: JsonObject = {
        "snapshot_id": str(snapshot.snapshot_id),
        "reconciliation_complete": False,
        "ingested_file_count": len(observations),
        "inventory_error": inventory_error,
    }
    context.repository.finish_operation(operation_id, status="succeeded", details=details)
    return OperationExecutionResult(
        operation.operation_key,
        "succeeded",
        observation_ids=tuple(observations),
        details=details,
    )


def _record_rsync(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
    acquisition: RsyncAcquisition,
) -> OperationExecutionResult:
    if acquisition.status == "failed":
        details: JsonObject = {"error": acquisition.error or "rsync acquisition failed"}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)
    if acquisition.inventory is None or not acquisition.inventory.complete:
        return _record_incomplete_rsync(context, operation, operation_id, acquisition)

    source = _source_by_id(context.config, acquisition.source_id)
    result = reconcile_rsync_inventory(
        context.repository,
        source_id=source.id,
        run_id=context.run_id,
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
    status = "succeeded" if result.complete else "failed"
    context.repository.finish_operation(operation_id, status=status, details=details)
    return OperationExecutionResult(
        operation.operation_key,
        status,
        observation_ids=result.observations,
        details=details,
    )


def _record_collection(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
    acquisition: CollectionAcquisition,
) -> OperationExecutionResult:
    if acquisition.payload is None:
        details: JsonObject = {"error": acquisition.error or "collection acquisition produced no result"}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)

    recorded = record_collection_acquisition(
        context.repository,
        source_id=acquisition.source_id,
        task_name=acquisition.task_name,
        payload=acquisition.payload,
        run_id=context.run_id,
        operation_id=operation_id,
        observed_at=acquisition.observed_at,
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
    status: ExecutionStatus = "failed" if failed else "succeeded"
    context.repository.finish_operation(operation_id, status=status, details=details)
    return OperationExecutionResult(
        operation.operation_key,
        status,
        observation_ids=recorded.observations,
        details=details,
    )


def _current_inputs(repository: Repository, source_ids: tuple[str, ...]) -> tuple[ObservationId, ...]:
    wanted = set(source_ids)
    observations: list[ObservationId] = []
    for artifact_key in repository.artifact_keys():
        observation = repository.latest_observation(artifact_key)
        if observation is None or observation.source_id is None or str(observation.source_id) not in wanted:
            continue
        observations.append(observation.observation_id)
    return tuple(sorted(observations, key=str))


def _derived_task(context: _ExecutionContext, name: str):
    return next((task for task in context.config.derived_tasks if task.name == name), None)


async def _execute_derived(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
) -> OperationExecutionResult:
    task = _derived_task(context, operation.subject)
    if task is None:
        details: JsonObject = {"error": f"Unknown derived task: {operation.subject}"}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)
    input_source_ids = task.repository_input_source_ids if isinstance(task, RepositoryDerivedTask) else ()
    inputs = _current_inputs(context.repository, input_source_ids)
    manifest = repository_manifest(context.repository, cfg=context.config)
    try:
        raw_payload = await task.run(
            sync_root=Path(context.config.root),
            manifest=manifest,
            sources=tuple(context.config.sources),
        )
    except Exception as exc:  # ruff: ignore[blind-except] - derived tasks are extension failure domains and must not abort independent operations.
        details = {"error": f"{type(exc).__name__}: {exc}"}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)
    mapping = json_mapping_or_none(raw_payload)
    if mapping is None:
        details = {"error": "Derived task returned a non-JSON result."}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)
    payload = copy_json_mapping(mapping)
    observations: list[ObservationId] = []
    output = payload.get("dest")
    if isinstance(output, str) and Path(output).is_file():
        output_observation = context.repository.ingest_path(
            f"derived:{operation.subject}:output",
            Path(output),
            run_id=context.run_id,
            operation_id=operation_id,
            observed_at=time.time(),
            metadata={"derived_task": operation.subject, "adapter_execution": True},
            inputs=inputs,
            materialization_kind="derived",
        )
        observations.append(output_observation.observation_id)
    execution_inputs = (*inputs, *observations)
    execution = context.repository.ingest_bytes(
        f"derived:{operation.subject}:execution",
        canonical_json_bytes(payload),
        run_id=context.run_id,
        operation_id=operation_id,
        observed_at=time.time(),
        media_type="application/json",
        metadata={"derived_task": operation.subject, "adapter_execution": True},
        inputs=execution_inputs,
    )
    observations.append(execution.observation_id)
    err = payload.get("err")
    ok = payload.get("ok")
    failed = (isinstance(err, int) and not isinstance(err, bool) and err > 0) or ok is False
    details: JsonObject = {"execution_observation_id": str(execution.observation_id)}
    status: ExecutionStatus = "failed" if failed else "succeeded"
    context.repository.finish_operation(operation_id, status=status, details=details)
    return OperationExecutionResult(operation.operation_key, status, tuple(observations), details)


async def _execute_source(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
) -> OperationExecutionResult:
    if operation.source_id is None:
        details: JsonObject = {"error": "Source operation has no source_id."}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)
    source = _source_by_id(context.config, operation.source_id)
    adapter = context.adapters.adapter_for(source)
    if adapter is None:
        details = {"error": f"No adapter registered for {source.kind.value}."}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)
    acquisition = await adapter.acquire(
        AdapterExecutionContext(
            config=context.config,
            repository=context.repository,
            source=source,
            operation=operation,
        )
    )
    if isinstance(acquisition, HttpAcquisition):
        return _record_http(context, operation, operation_id, acquisition)
    if isinstance(acquisition, RsyncAcquisition):
        return _record_rsync(context, operation, operation_id, acquisition)
    return _record_collection(context, operation, operation_id, acquisition)


async def _execute_operation(
    context: _ExecutionContext,
    operation: PlannedOperation,
) -> OperationExecutionResult:
    operation_id = _start_operation(context, operation)
    try:
        if operation.kind == "source":
            return await _execute_source(context, operation, operation_id)
        return await _execute_derived(context, operation, operation_id)
    except asyncio.CancelledError:
        context.repository.finish_operation(
            operation_id,
            status="cancelled",
            details={"error": "operation cancelled"},
        )
        raise
    except Exception as exc:  # ruff: ignore[blind-except] - adapter/task extensions are isolated so sibling planned operations can continue.
        details: JsonObject = {"error": f"{type(exc).__name__}: {exc}"}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)


def _blocked_operation(
    context: _ExecutionContext,
    operation: PlannedOperation,
    failed_dependencies: tuple[str, ...],
) -> OperationExecutionResult:
    operation_id = _start_operation(context, operation)
    details: JsonObject = {
        "error": "operation blocked by unsuccessful dependencies",
        "failed_dependencies": list(failed_dependencies),
    }
    context.repository.finish_operation(operation_id, status="cancelled", details=details)
    return OperationExecutionResult(operation.operation_key, "blocked", details=details)


async def _execute_wave(
    context: _ExecutionContext,
    operations: tuple[PlannedOperation, ...],
    *,
    max_concurrency: int,
) -> tuple[OperationExecutionResult, ...]:
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run(operation: PlannedOperation) -> OperationExecutionResult:
        async with semaphore:
            return await _execute_operation(context, operation)

    return tuple(await asyncio.gather(*(run(operation) for operation in operations)))


async def _execute_operations(context: _ExecutionContext) -> tuple[OperationExecutionResult, ...]:
    pending = {operation.operation_key: operation for operation in context.plan.operations}
    known_keys = set(pending)
    for operation in pending.values():
        unknown = set(operation.dependencies) - known_keys
        if unknown:
            msg = f"Operation {operation.operation_key!r} has unknown dependencies: {sorted(unknown)!r}"
            raise ValueError(msg)

    results: dict[str, OperationExecutionResult] = {}
    while pending:
        ready = tuple(
            sorted(
                (operation for operation in pending.values() if all(dep in results for dep in operation.dependencies)),
                key=lambda item: item.operation_key,
            )
        )
        if not ready:
            msg = f"Sync plan contains a dependency cycle: {sorted(pending)!r}"
            raise ValueError(msg)

        executable: list[PlannedOperation] = []
        for operation in ready:
            failed_dependencies = tuple(
                dependency
                for dependency in operation.dependencies
                if results[dependency].status != "succeeded"
            )
            if failed_dependencies:
                results[operation.operation_key] = _blocked_operation(context, operation, failed_dependencies)
            else:
                executable.append(operation)
            pending.pop(operation.operation_key)
        if executable:
            completed = await _execute_wave(
                context,
                tuple(executable),
                max_concurrency=context.plan.request.max_concurrency,
            )
            results.update((result.operation_key, result) for result in completed)
    return tuple(results[key] for key in sorted(results))


def _run_status(results: tuple[OperationExecutionResult, ...]) -> str:
    failed = any(result.status in {"failed", "blocked"} for result in results)
    succeeded = any(result.status == "succeeded" for result in results)
    if failed and succeeded:
        return "partial"
    if failed:
        return "failed"
    return "succeeded"


@dataclass(frozen=True, slots=True)
class SyncExecutor:
    adapters: AdapterRegistry

    async def execute(
        self,
        *,
        plan: SyncPlan,
        config: EngineConfig,
        repository: Repository,
    ) -> SyncExecutionResult:
        """Execute exactly one typed plan; dry-run performs no authoritative mutation."""
        if plan.request.dry_run:
            return SyncExecutionResult(
                plan_id=plan.plan_id,
                run_id=None,
                operations=tuple(
                    OperationExecutionResult(operation.operation_key, "not-executed") for operation in plan.operations
                ),
            )

        selected_source_ids = tuple(
            sorted(operation.source_id for operation in plan.operations if operation.source_id is not None)
        )
        for source_id in selected_source_ids:
            source = _source_by_id(config, source_id)
            repository.register_source(SourceId(source.id), _source_definition_payload(source))
        run_id = repository.start_run(
            source_ids=selected_source_ids,
            metadata={"plan_id": plan.plan_id, "request": plan.request.to_dict(), "planner": "phase11-v1"},
        )
        context = _ExecutionContext(config, repository, self.adapters, plan, run_id)
        try:
            results = await _execute_operations(context)
        except asyncio.CancelledError:
            for operation in repository.metadata.operations_for_run(run_id):
                if operation.status == "running":
                    repository.finish_operation(
                        operation.operation_id,
                        status="cancelled",
                        details={"error": "sync execution cancelled"},
                    )
            repository.finish_run(run_id, status="cancelled")
            raise
        except Exception:
            for operation in repository.metadata.operations_for_run(run_id):
                if operation.status == "running":
                    repository.finish_operation(
                        operation.operation_id,
                        status="failed",
                        details={"error": "sync executor aborted"},
                    )
            repository.finish_run(run_id, status="failed")
            raise
        repository.finish_run(run_id, status=_run_status(results))
        return SyncExecutionResult(plan.plan_id, run_id, results)


__all__ = [
    "ExecutionStatus",
    "OperationExecutionResult",
    "SyncExecutionResult",
    "SyncExecutor",
]
