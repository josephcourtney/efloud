from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from efloud.builtin_adapters import builtin_adapter_registry
from efloud.executor import SyncExecutionResult, SyncExecutor
from efloud.models import EngineConfig
from efloud.planner import SyncPlanner
from efloud.repository import Repository
from efloud.validation import ValidationRegistry, builtin_validation_registry

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from types import TracebackType

    from efloud.adapters import AdapterRegistry
    from efloud.planning import SyncPlan, SyncRequest
    from efloud.registry import SourceDefinition
    from efloud.repository_models import ObservationId, RunId


@dataclass(frozen=True, slots=True)
class EngineSyncResult:
    """Canonical operation result independent of optional compatibility projections."""

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
    def __init__(
        self,
        root: Path,
        sources: Sequence[SourceDefinition],
        *,
        repository: Repository | None = None,
        adapters: AdapterRegistry | None = None,
        validators: ValidationRegistry | None = None,
    ) -> None:
        self.config = EngineConfig(root=root, sources=list(sources))
        self.repository = repository or Repository(root)
        self.adapters = adapters or builtin_adapter_registry()
        self.validators = validators or builtin_validation_registry()
        self.planner = SyncPlanner(self.adapters)
        self.executor = SyncExecutor(self.adapters, self.validators)
        self._owns_repository = repository is None

    @classmethod
    def from_config(
        cls,
        config: EngineConfig,
        *,
        repository: Repository | None = None,
        adapters: AdapterRegistry | None = None,
        validators: ValidationRegistry | None = None,
    ) -> Engine:
        engine = cls(
            config.root,
            config.sources,
            repository=repository,
            adapters=adapters,
            validators=validators,
        )
        engine.config = config
        return engine

    def __enter__(self) -> Self:
        """Return this engine for context-manager use."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close owned repository resources when leaving a context."""
        self.close()

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()

    def plan(self, request: SyncRequest | None = None) -> SyncPlan:
        """Build the deterministic plan for current repository state without mutation."""
        return self.planner.plan(config=self.config, repository=self.repository, request=request)

    @staticmethod
    def _skipped_source_ids(plan: SyncPlan, execution: SyncExecutionResult) -> tuple[str, ...]:
        skipped = {decision.source_id for decision in plan.decisions if not decision.selected}
        skipped.update(execution.blocked_source_ids)
        return tuple(sorted(skipped))

    async def sync(self, request: SyncRequest | None = None) -> EngineSyncResult:
        """Plan and execute typed repository operations."""
        plan = self.plan(request)
        execution = await self.executor.execute(plan=plan, config=self.config, repository=self.repository)
        return EngineSyncResult(
            root=self.config.root,
            plan=plan,
            execution=execution,
            repository_run_id=execution.run_id,
            observations=execution.observations,
            skipped_source_ids=self._skipped_source_ids(plan, execution),
        )


__all__ = ["Engine", "EngineSyncResult"]
