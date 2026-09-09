from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from efloud.adapters import AdapterExecutionContext, AdapterRegistry
from efloud.derivation import source_inputs
from efloud.operation_recording import RecordedOperation, record_source_acquisition, run_derived_operation
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository_models import ObservationId, OperationId, RunId, SourceId
from efloud.sources import CollectionSource, source_definition
from efloud.validation import ValidationRegistry, ValidationService, builtin_validation_registry

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from efloud.derivation import DerivedTask
    from efloud.json_types import JsonArray, JsonObject
    from efloud.planning import PlannedOperation, SyncPlan
    from efloud.repository_capabilities import RepositoryWriter
    from efloud.runtime import EngineRuntime
    from efloud.sources import Source


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
    def blocked_source_ids(self) -> tuple[str, ...]:
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
    sources: tuple[Source, ...]
    derived_tasks: tuple[DerivedTask, ...]
    runtime: EngineRuntime
    repository: RepositoryWriter
    adapters: AdapterRegistry
    validation: ValidationService
    plan: SyncPlan
    run_id: RunId


def _json_strings(values: Iterable[str]) -> JsonArray:
    items: JsonArray = []
    items.extend(values)
    return items


def _string_tuple(parameters: JsonObject, key: str) -> tuple[str, ...]:
    value = parameters.get(key)
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _source_by_id(sources: Sequence[Source], source_id: str) -> Source:
    source = next((candidate for candidate in sources if candidate.id == source_id), None)
    if source is None:
        msg = f"Planned source is not configured: {source_id!r}"
        raise KeyError(msg)
    return source


def _derived_task(tasks: Sequence[DerivedTask], name: str) -> DerivedTask | None:
    return next((task for task in tasks if task.name == name), None)


def _operation_kind(operation: PlannedOperation, source: Source | None) -> str:
    if operation.kind == "derived":
        return "derived"
    if isinstance(source, CollectionSource):
        return "collection"
    if source is None:
        return "source"
    return source.adapter_id.rpartition(":")[2] or "source"


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
    source = _source_by_id(context.sources, operation.source_id) if operation.source_id is not None else None
    return context.repository.start_operation(
        run_id=context.run_id,
        source_id=operation.source_id,
        kind=_operation_kind(operation, source),
        subject=operation.subject,
        producer=operation.producer,
        parameters=_operation_parameters(context.plan, operation),
    )


async def _source_result(
    context: _ExecutionContext,
    operation: PlannedOperation,
    operation_id: OperationId,
) -> RecordedOperation:
    if operation.source_id is None:
        return RecordedOperation("failed", details={"error": "Source operation has no source_id."})
    source = _source_by_id(context.sources, operation.source_id)
    adapter = context.adapters.adapter_for(source)
    if adapter is None:
        return RecordedOperation("failed", details={"error": f"No adapter registered for {source.adapter_id}."})
    input_source_ids = _string_tuple(operation.parameters, "input_source_ids")
    with ReadOnlyRepository(context.repository.root) as view:
        inputs = source_inputs(view, input_source_ids)
        acquisition = await adapter.acquire(
            AdapterExecutionContext(
                runtime=context.runtime,
                repository=view,
                source=source,
                operation=operation,
                inputs=inputs,
            )
        )
    return record_source_acquisition(
        context.repository,
        context.validation,
        source=source,
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
    if operation.kind == "source":
        return await _source_result(context, operation, operation_id)
    task = _derived_task(context.derived_tasks, operation.subject)
    if task is None:
        return RecordedOperation("failed", details={"error": f"Unknown derived task: {operation.subject}"})
    return await run_derived_operation(
        context.repository,
        runtime=context.runtime,
        task=task,
        operation=operation,
        run_id=context.run_id,
        operation_id=operation_id,
    )


async def _execute_operation(context: _ExecutionContext, operation: PlannedOperation) -> OperationExecutionResult:
    operation_id = _start_operation(context, operation)
    try:
        recorded = await _recorded_result(context, operation, operation_id)
    except asyncio.CancelledError:
        context.repository.finish_operation(operation_id, status="cancelled", details={"error": "operation cancelled"})
        raise
    except Exception as exc:  # ruff: ignore[blind-except] - adapter/task extensions are isolated sibling failure domains.
        details: JsonObject = {"error": f"{type(exc).__name__}: {exc}"}
        context.repository.finish_operation(operation_id, status="failed", details=details)
        return OperationExecutionResult(operation.operation_key, "failed", details=details)
    context.repository.finish_operation(operation_id, status=recorded.status, details=recorded.details)
    return OperationExecutionResult(operation.operation_key, recorded.status, recorded.observation_ids, recorded.details)


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
    validators: ValidationRegistry = field(default_factory=builtin_validation_registry)

    async def execute(
        self,
        *,
        plan: SyncPlan,
        sources: Sequence[Source],
        runtime: EngineRuntime,
        derived_tasks: Sequence[DerivedTask],
        repository: RepositoryWriter,
    ) -> SyncExecutionResult:
        """Execute exactly one typed plan; dry-run performs no authoritative mutation."""
        if plan.request.dry_run:
            return SyncExecutionResult(
                plan.plan_id,
                None,
                tuple(OperationExecutionResult(operation.operation_key, "not-executed") for operation in plan.operations),
            )
        selected_source_ids = tuple(sorted({operation.source_id for operation in plan.operations if operation.source_id is not None}))
        for source_id in selected_source_ids:
            source = _source_by_id(sources, source_id)
            repository.register_source(SourceId(source.id), source_definition(source))
        run_id = repository.start_run(
            source_ids=selected_source_ids,
            metadata={"plan_id": plan.plan_id, "request": plan.request.to_dict(), "planner": "canonical-v1"},
        )
        context = _ExecutionContext(
            tuple(sources),
            tuple(derived_tasks),
            runtime,
            repository,
            self.adapters,
            ValidationService(repository, self.validators),
            plan,
            run_id,
        )
        try:
            results = await _execute_operations(context)
        except asyncio.CancelledError:
            for operation in repository.operations_for_run(run_id):
                if operation.status == "running":
                    repository.finish_operation(operation.operation_id, status="cancelled", details={"error": "sync execution cancelled"})
            repository.finish_run(run_id, status="cancelled")
            raise
        except Exception:
            for operation in repository.operations_for_run(run_id):
                if operation.status == "running":
                    repository.finish_operation(operation.operation_id, status="failed", details={"error": "sync executor aborted"})
            repository.finish_run(run_id, status="failed")
            raise
        repository.finish_run(run_id, status=_run_status(results))
        return SyncExecutionResult(plan.plan_id, run_id, results)


__all__ = ["ExecutionStatus", "OperationExecutionResult", "SyncExecutionResult", "SyncExecutor"]
