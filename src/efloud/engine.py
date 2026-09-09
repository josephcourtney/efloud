from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from efloud.builtin_adapters import builtin_adapter_registry
from efloud.executor import SyncExecutionResult, SyncExecutor
from efloud.planner import SyncPlanner
from efloud.runtime import EngineRuntime
from efloud.validation import ValidationRegistry, builtin_validation_registry

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from types import TracebackType

    from efloud.adapters import AdapterRegistry
    from efloud.collections import CollectionDefinition
    from efloud.derivation import DerivedTask
    from efloud.planning import SyncPlan, SyncRequest
    from efloud.policy import SyncPolicy
    from efloud.repository_capabilities import RepositoryWriter
    from efloud.repository_models import ObservationId, RunId
    from efloud.sources import Source


@dataclass(frozen=True, slots=True)
class EngineSyncResult:
    """Detailed advanced execution result behind the ordinary public SyncResult."""

    root: Path
    plan: SyncPlan
    execution: SyncExecutionResult
    repository_run_id: RunId | None
    observations: tuple[ObservationId, ...]
    skipped_source_ids: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.execution.ok


class Engine:
    """Canonical orchestration over clean sources, request intent, and an internal writer."""

    def __init__(
        self,
        repository: RepositoryWriter,
        sources: Sequence[Source],
        *,
        runtime: EngineRuntime | None = None,
        adapters: AdapterRegistry | None = None,
        validators: ValidationRegistry | None = None,
        policy: SyncPolicy | None = None,
        derived_tasks: Sequence[DerivedTask] = (),
        collections: Sequence[CollectionDefinition] = (),
    ) -> None:
        self.repository = repository
        self.sources = tuple(sources)
        self.runtime = runtime or EngineRuntime.for_root(repository.root)
        self.collections = tuple(collections)
        self.derived_tasks = tuple(derived_tasks)
        self.policy = policy
        self.adapters = adapters or builtin_adapter_registry(self.collections)
        self.validators = validators or builtin_validation_registry()
        self.planner = SyncPlanner(self.adapters)
        self.executor = SyncExecutor(self.adapters, self.validators)

    def __enter__(self) -> Self:
        """Return the orchestrator; repository lifetime is owned by its caller."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Do not close the caller-owned repository."""

    def close(self) -> None:
        """Compatibility no-op; repository lifetime is caller-owned."""

    def plan(self, request: SyncRequest | None = None) -> SyncPlan:
        return self.planner.plan(
            sources=self.sources,
            repository=self.repository,
            request=request,
            policy=self.policy,
            derived_tasks=self.derived_tasks,
            collections=self.collections,
        )

    @staticmethod
    def _skipped_source_ids(plan: SyncPlan, execution: SyncExecutionResult) -> tuple[str, ...]:
        skipped = {decision.source_id for decision in plan.decisions if not decision.selected}
        skipped.update(execution.blocked_source_ids)
        return tuple(sorted(skipped))

    async def sync(self, request: SyncRequest | None = None) -> EngineSyncResult:
        """Plan and execute against the exact same canonical contracts."""
        plan = self.plan(request)
        execution = await self.executor.execute(
            plan=plan,
            sources=self.sources,
            runtime=self.runtime,
            derived_tasks=self.derived_tasks,
            repository=self.repository,
        )
        return EngineSyncResult(
            root=self.runtime.root,
            plan=plan,
            execution=execution,
            repository_run_id=execution.run_id,
            observations=execution.observations,
            skipped_source_ids=self._skipped_source_ids(plan, execution),
        )


__all__ = ["Engine", "EngineSyncResult"]
