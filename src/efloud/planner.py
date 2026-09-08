from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.adapters import AdapterRegistry
from efloud.derived import RepositoryDerivedTask
from efloud.fanout import RestBaseFanoutTask
from efloud.json_types import JsonObject
from efloud.planning import PlannedOperation, PlanningDecision, SyncPlan, SyncRequest, make_sync_plan
from efloud.policy import DefaultSyncPolicy
from efloud.registry import SourceKind
from efloud.repository_models import ProducerRef

if TYPE_CHECKING:
    from efloud.models import EngineConfig
    from efloud.registry import SourceDefinition
    from efloud.repository import Repository


def _task_version(task: object) -> str:
    if isinstance(task, RepositoryDerivedTask):
        return task.repository_version
    return "1"


def _task_input_source_ids(task: object) -> tuple[str, ...]:
    if isinstance(task, RepositoryDerivedTask):
        return tuple(sorted(set(task.repository_input_source_ids)))
    return ()


def _collection_task(config: EngineConfig, source_id: str) -> RestBaseFanoutTask | None:
    return next(
        (
            task
            for task in config.derived_tasks
            if isinstance(task, RestBaseFanoutTask) and task.source_id == source_id
        ),
        None,
    )


def _selected_source_ids(config: EngineConfig, request: SyncRequest) -> set[str]:
    configured = {source.id for source in config.sources}
    if request.source_ids is None:
        return configured
    unknown = set(request.source_ids) - configured
    if unknown:
        msg = f"Unknown requested source identifiers: {', '.join(sorted(unknown))}"
        raise ValueError(msg)
    return set(request.source_ids)


def _planned_dependency_keys(input_source_ids: tuple[str, ...], selected_source_ids: set[str]) -> tuple[str, ...]:
    return tuple(sorted(f"source:{source_id}" for source_id in input_source_ids if source_id in selected_source_ids))


def _source_operation_parameters(
    source: SourceDefinition,
    *,
    snapshot_id: str | None,
    capabilities: JsonObject,
) -> JsonObject:
    payload: JsonObject = {
        "source_kind": source.kind.value,
        "url": source.url,
        "adapter_capabilities": capabilities,
    }
    if snapshot_id is not None:
        payload["current_snapshot_id"] = snapshot_id
    return payload


@dataclass(frozen=True, slots=True)
class SyncPlanner:
    adapters: AdapterRegistry

    def _source_plan(
        self,
        *,
        source: SourceDefinition,
        config: EngineConfig,
        repository: Repository,
        selected_source_ids: set[str],
    ) -> tuple[PlanningDecision, PlannedOperation | None]:
        if source.id not in selected_source_ids:
            return PlanningDecision(source.id, False, "source not requested"), None
        if source.kind is SourceKind.RSYNC and config.skip_rsync:
            return PlanningDecision(source.id, False, "rsync disabled by configuration"), None

        adapter = self.adapters.adapter_for(source)
        if adapter is None:
            return PlanningDecision(source.id, False, f"no adapter registered for {source.kind.value}"), None
        collection_task = _collection_task(config, source.id) if source.kind is SourceKind.REST_BASE else None
        if source.kind is SourceKind.REST_BASE and collection_task is None:
            return PlanningDecision(
                source.id,
                False,
                "collection source has no configured RestBaseFanoutTask",
                adapter_id=adapter.descriptor.adapter_id,
                adapter_version=adapter.descriptor.version,
            ), None

        snapshot = repository.latest_source_snapshot(source.id)
        policy = config.sync_policy or DefaultSyncPolicy()
        refresh = policy.refresh_decision(source, config, snapshot=snapshot)
        scope = policy.source_scope(source, config)
        input_source_ids = _task_input_source_ids(collection_task) if collection_task is not None else ()
        dependencies = _planned_dependency_keys(input_source_ids, selected_source_ids)
        snapshot_id = str(snapshot.snapshot_id) if snapshot is not None else None
        operation = PlannedOperation(
            operation_key=f"source:{source.id}",
            kind="source",
            subject=source.id,
            source_id=source.id,
            producer=adapter.descriptor.producer,
            dependencies=dependencies,
            refresh=refresh,
            scope=scope,
            parameters=_source_operation_parameters(
                source,
                snapshot_id=snapshot_id,
                capabilities=adapter.descriptor.capabilities.to_dict(),
            ),
        )
        return (
            PlanningDecision(
                source_id=source.id,
                selected=True,
                reason="source selected for acquisition",
                adapter_id=adapter.descriptor.adapter_id,
                adapter_version=adapter.descriptor.version,
                refresh=refresh,
                scope=scope,
            ),
            operation,
        )

    @staticmethod
    def _derived_operations(
        *,
        config: EngineConfig,
        repository: Repository,
        request: SyncRequest,
        selected_source_ids: set[str],
    ) -> tuple[PlannedOperation, ...]:
        if not request.include_derived or config.skip_derived:
            return ()
        operations: list[PlannedOperation] = []
        for task in sorted(config.derived_tasks, key=lambda candidate: candidate.name):
            if isinstance(task, RestBaseFanoutTask):
                continue
            input_source_ids = _task_input_source_ids(task)
            input_snapshot_ids = [
                str(snapshot.snapshot_id)
                for source_id in input_source_ids
                for snapshot in [repository.latest_source_snapshot(source_id)]
                if snapshot is not None
            ]
            parameters: JsonObject = {
                "input_source_ids": list(input_source_ids),
                "input_snapshot_ids": input_snapshot_ids,
            }
            if isinstance(task, RepositoryDerivedTask):
                parameters["task_parameters"] = task.repository_parameters()
            operations.append(
                PlannedOperation(
                    operation_key=f"derived:{task.name}",
                    kind="derived",
                    subject=task.name,
                    producer=ProducerRef(f"efloud:derived:{task.name}", _task_version(task)),
                    dependencies=_planned_dependency_keys(input_source_ids, selected_source_ids),
                    parameters=parameters,
                )
            )
        return tuple(operations)

    def plan(
        self,
        *,
        config: EngineConfig,
        repository: Repository,
        request: SyncRequest | None = None,
    ) -> SyncPlan:
        """Build a deterministic plan without acquisition or repository mutation."""
        resolved_request = request or SyncRequest.from_config(config)
        selected_source_ids = _selected_source_ids(config, resolved_request)
        decisions: list[PlanningDecision] = []
        operations: list[PlannedOperation] = []
        for source in sorted(config.sources, key=lambda item: item.id):
            decision, operation = self._source_plan(
                source=source,
                config=config,
                repository=repository,
                selected_source_ids=selected_source_ids,
            )
            decisions.append(decision)
            if operation is not None:
                operations.append(operation)
        operations.extend(
            self._derived_operations(
                config=config,
                repository=repository,
                request=resolved_request,
                selected_source_ids=selected_source_ids,
            )
        )
        return make_sync_plan(
            request=resolved_request,
            decisions=tuple(decisions),
            operations=tuple(operations),
        )


__all__ = ["SyncPlanner"]
