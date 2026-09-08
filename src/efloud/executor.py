from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from efloud.adapters import AdapterExecutionContext, AdapterRegistry
from efloud.fs import delete_http_cache_files, prune_orphan_mirrors
from efloud.json_types import JsonArray, JsonObject
from efloud.operation_recording import RecordedOperation, record_source_acquisition, run_derived_operation
from efloud.planning import PlannedOperation, SyncPlan
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository_models import ObservationId, OperationId, RunId, SourceId
from efloud.validation import ValidationRegistry, ValidationService

if TYPE_CHECKING:
    from collections.abc import Iterable

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
        """Observation identifiers produced by all executed operations."""
        return tuple(observation for operation in self.operations for observation in operation.observation_ids)

    @property
    def blocked_source_ids(self) -> tuple[str, ...]:
        """Source identifiers whose planned operations were blocked or not executed."""
        return tuple(
            sorted(
                operation.operation_key.removeprefix("source:")
                for operation in self.operations
                if operation.operation_key.startswith("source:")
                and operation.status in {"not-executed", "blocked"}
            )
        )

    @property
    def ok(self) -> bool:
        """Whether every operation succeeded or was intentionally not executed."""
        return all(operation.status in {"succeeded", "not-executed"} for operation in self.operations)


@dataclass(frozen=True, slots=True)
class _ExecutionContext:
    config: EngineConfig
    repository: Repository
    adapters: AdapterRegistry
    validation: ValidationService
    plan: SyncPlan
    run_id: RunId


def _json_strings(values: Iterable[str]) -> JsonArray:
    items: JsonArray = []
    items.extend(values)
    return items


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
    if source.expected_integrity:
        expectations: JsonArray = []
        expectations.extend(item.to_dict() for item in source.expected_integrity)
        payload["expected_integrity"] = expectations
    return payload


def _source_by_id(config: EngineConfig, source_id: str) -> SourceDefinition:
    source = next((candidate for candidate in config.sources if candidate.id == source_id), None)
    if source is None:
        msg = f"Planned source is not configured: {source_id!r}"
        raise KeyError(msg)
    return source


def _operation_kind(operation: PlannedOperation, source: SourceDefinition | None) -> str:
    if operation.kind == "housekeeping":
        return "housekeeping"
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


def _housekeeping_result(context: _ExecutionContext, operation: PlannedOperation) -> RecordedOperation:
    action = operation.parameters.get("action")
    if action == "delete-http-caches":
        cache_root = Path(context.config.root) / context.config.cache_dir / context.config.http_cache_dir
        removed = delete_http_cache_files(cache_root)
        details: JsonObject = {"removed": _json_strings(removed)}
        return RecordedOperation("succeeded", details=details)
    if action == "prune-orphan-mirrors":
        raw_expected = operation.parameters.get("expected_subpaths")
        expected_subpaths = (
            tuple(value for value in raw_expected if isinstance(value, str)) if isinstance(raw_expected, list) else ()
        )
        mirrors_root = Path(context.config.root) / context.config.mirrors_dir
        keep_dirs = tuple(mirrors_root / subpath for subpath in expected_subpaths)
        removed = prune_orphan_mirrors(mirrors_root, keep_dirs)
        details = {"removed": _json_strings(removed)}
        return RecordedOperation("succeeded", details=details)
    return RecordedOperation("failed", details={"error": f"Unknown housekeeping action: {action!r}"})


async def _source_result(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
) -> RecordedOperation:
    if operation.source_id is None:
        return RecordedOperation("failed", details={"error": "Source operation has no source_id."})
    source = _source_by_id(context.config, operation.source_id)
    adapter = context.adapters.adapter_for(source)
    if adapter is None:
        return RecordedOperation("failed", details={"error": f"No adapter registered for {source.kind.value}."})
    acquisition = await adapter.acquire(
        AdapterExecutionContext(
            config=context.config,
            repository=context.repository,
            source=source,
            operation=operation,
        )
    )
    return record_source_acquisition(
        context.repository,
        context.validation,
        config=context.config,
        operation=operation,
        run_id=context.run_id,
        operation_id=operation_id,
        acquisition=acquisition,
    )


async def _recorded_result(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
) -> RecordedOperation:
    if operation.kind == "housekeeping":
        return _housekeeping_result(context, operation)
    if operation.kind == "source":
        return await _source_result(context, operation, operation_id)
    return await run_derived_operation(
        context.repository,
        config=context.config,
        operation=operation,
        run_id=context.run_id,
        operation_id=operation_id,
    )


async def _execute_operation(
    context: _ExecutionContext,
    operation: PlannedOperation,
) -> OperationExecutionResult:
    operation_id = _start_operation(context, operation)
    try:
        recorded = await _recorded_result(context, operation, operation_id)
    except asyncio.CancelledError:
        context.repository.finish_operation(
            operation_id,
            status="cancelled",
            details={"error": "operation cancelled"},
        )
        raise
    except Exception as exc:  # ruff: ignore[blind-except] - adapter/task extensions are isolated sibling failure domains.
        details: JsonObject = {"error": f"{type(exc).__name__}: {exc}"}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)

    context.repository.finish_operation(operation_id, status=recorded.status, details=recorded.details)
    return OperationExecutionResult(
        operation_key=operation.operation_key,
        status=recorded.status,
        observation_ids=recorded.observation_ids,
        details=recorded.details,
    )


def _blocked_operation(
    context: _ExecutionContext,
    operation: PlannedOperation,
    failed_dependencies: tuple[str, ...],
) -> OperationExecutionResult:
    operation_id = _start_operation(context, operation)
    details: JsonObject = {
        "error": "operation blocked by unsuccessful dependencies",
        "failed_dependencies": _json_strings(failed_dependencies),
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
                dependency for dependency in operation.dependencies if results[dependency].status != "succeeded"
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
    validators: ValidationRegistry

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
                    OperationExecutionResult(operation.operation_key, "not-executed")
                    for operation in plan.operations
                ),
            )

        selected_source_ids = tuple(
            sorted({operation.source_id for operation in plan.operations if operation.source_id is not None})
        )
        for source_id in selected_source_ids:
            source = _source_by_id(config, source_id)
            repository.register_source(SourceId(source.id), _source_definition_payload(source))
        run_id = repository.start_run(
            source_ids=selected_source_ids,
            metadata={"plan_id": plan.plan_id, "request": plan.request.to_dict(), "planner": "phase11-v1"},
        )
        context = _ExecutionContext(
            config=config,
            repository=repository,
            adapters=self.adapters,
            validation=ValidationService(repository, self.validators),
            plan=plan,
            run_id=run_id,
        )
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
        except Exception:  # ruff: ignore[blind-except] - executor closes lifecycle state before propagating failures.
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
