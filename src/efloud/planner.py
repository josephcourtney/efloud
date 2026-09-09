from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.planning import PlannedOperation, PlanningDecision, SyncPlan, SyncRequest, make_sync_plan
from efloud.policy import DefaultSyncPolicy
from efloud.sources import CollectionSource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from efloud.adapters import AdapterRegistry
    from efloud.collections import CollectionDefinition
    from efloud.derivation import DerivedTask
    from efloud.json_types import JsonArray, JsonObject
    from efloud.policy import SyncPolicy
    from efloud.repository_capabilities import SourceReader
    from efloud.sources import Source


def _json_strings(values: Sequence[str]) -> JsonArray:
    items: JsonArray = []
    items.extend(values)
    return items


def _collection_by_source(collections: Sequence[CollectionDefinition], source_id: str) -> CollectionDefinition | None:
    return next((definition for definition in collections if definition.source_id == source_id), None)


def _selected_source_ids(sources: Sequence[Source], request: SyncRequest) -> set[str]:
    configured = {source.id for source in sources}
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
    source: Source,
    *,
    snapshot_id: str | None,
    capabilities: JsonObject,
    input_source_ids: tuple[str, ...],
) -> JsonObject:
    payload: JsonObject = {
        "adapter_id": source.adapter_id,
        "source_definition": source.definition(),
        "adapter_capabilities": capabilities,
        "input_source_ids": _json_strings(input_source_ids),
    }
    if snapshot_id is not None:
        payload["current_snapshot_id"] = snapshot_id
    return payload


def _validate_task(task: DerivedTask) -> None:
    declared = task.output_names
    if len(set(declared)) != len(declared) or any(not name for name in declared):
        msg = f"Derived task {task.name!r} must declare unique nonempty output names."
        raise ValueError(msg)
    if task.spec.task_id != f"efloud:derived:{task.name}" and not task.spec.task_id:
        msg = f"Derived task {task.name!r} has an invalid task identity."
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SyncPlanner:
    adapters: AdapterRegistry

    def _source_plan(
        self,
        *,
        source: Source,
        repository: SourceReader,
        request: SyncRequest,
        policy: SyncPolicy,
        collections: Sequence[CollectionDefinition],
        selected_source_ids: set[str],
    ) -> tuple[PlanningDecision, PlannedOperation | None]:
        if source.id not in selected_source_ids:
            return PlanningDecision(
                source_id=source.id,
                selected=False,
                reason="source not requested",
            ), None

        adapter = self.adapters.adapter_for(source)
        if adapter is None:
            return PlanningDecision(
                source_id=source.id,
                selected=False,
                reason=f"no adapter registered for {source.adapter_id}",
                adapter_id=source.adapter_id,
            ), None

        collection = _collection_by_source(collections, source.id) if isinstance(source, CollectionSource) else None
        if isinstance(source, CollectionSource) and collection is None:
            return PlanningDecision(
                source_id=source.id,
                selected=False,
                reason="collection source has no configured CollectionDefinition",
                adapter_id=adapter.descriptor.adapter_id,
                adapter_version=adapter.descriptor.version,
            ), None

        snapshot = repository.latest_source_snapshot(source.id)
        refresh = policy.refresh_decision(source, request, snapshot=snapshot)
        scope = policy.source_scope(source, request)
        input_source_ids = collection.input_source_ids if collection is not None else ()
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
                input_source_ids=input_source_ids,
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
        derived_tasks: Sequence[DerivedTask],
        repository: SourceReader,
        request: SyncRequest,
        selected_source_ids: set[str],
    ) -> tuple[PlannedOperation, ...]:
        if not request.include_derived:
            return ()
        operations: list[PlannedOperation] = []
        for task in sorted(derived_tasks, key=lambda candidate: candidate.name):
            _validate_task(task)
            input_source_ids = tuple(sorted(set(task.input_source_ids)))
            input_snapshot_ids = [
                str(snapshot.snapshot_id)
                for source_id in input_source_ids
                for snapshot in [repository.latest_source_snapshot(source_id)]
                if snapshot is not None
            ]
            parameters: JsonObject = {
                "input_source_ids": _json_strings(input_source_ids),
                "input_snapshot_ids": _json_strings(input_snapshot_ids),
                "declared_outputs": _json_strings(task.output_names),
                "task_spec": task.spec.to_dict(),
            }
            operations.append(
                PlannedOperation(
                    operation_key=f"derived:{task.name}",
                    kind="derived",
                    subject=task.name,
                    producer=task.spec.producer,
                    dependencies=_planned_dependency_keys(input_source_ids, selected_source_ids),
                    parameters=parameters,
                )
            )
        return tuple(operations)

    def plan(
        self,
        *,
        sources: Sequence[Source],
        repository: SourceReader,
        request: SyncRequest | None = None,
        policy: SyncPolicy | None = None,
        derived_tasks: Sequence[DerivedTask] = (),
        collections: Sequence[CollectionDefinition] = (),
    ) -> SyncPlan:
        """Build a deterministic plan from source intent and repository evidence."""
        resolved_request = request or SyncRequest()
        resolved_policy = policy or DefaultSyncPolicy()
        selected_source_ids = _selected_source_ids(sources, resolved_request)
        decisions: list[PlanningDecision] = []
        source_operations: list[PlannedOperation] = []
        for source in sorted(sources, key=lambda item: item.id):
            decision, operation = self._source_plan(
                source=source,
                repository=repository,
                request=resolved_request,
                policy=resolved_policy,
                collections=collections,
                selected_source_ids=selected_source_ids,
            )
            decisions.append(decision)
            if operation is not None:
                source_operations.append(operation)
        operations = [*source_operations]
        operations.extend(
            self._derived_operations(
                derived_tasks=derived_tasks,
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
