from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from efloud.adapters import AdapterRegistry
from efloud.builtin_adapters import builtin_adapter_registry
from efloud.executor import SyncExecutionResult, SyncExecutor
from efloud.models import EngineConfig, NormalizedManifest, SyncResult
from efloud.planner import SyncPlanner
from efloud.planning import SyncPlan, SyncRequest
from efloud.repository import Repository
from efloud.repository_compat import repository_manifest
from efloud.repository_outputs import publish_repository_outputs

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from types import TracebackType

    from efloud.registry import SourceDefinition
    from efloud.repository_models import ObservationId, RunId
    from efloud.state import MirrorState


@dataclass(frozen=True, slots=True)
class EngineSyncResult:
    sync_result: SyncResult
    plan: SyncPlan
    execution: SyncExecutionResult
    repository_run_id: RunId | None
    observations: tuple[ObservationId, ...]
    skipped_source_ids: tuple[str, ...]
    repository_manifest: NormalizedManifest | None = None
    repository_manifest_path: Path | None = None
    repository_mirror_state: MirrorState | None = None
    repository_mirror_state_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.sync_result.ok

    @property
    def root(self) -> Path:
        return self.sync_result.root

    @property
    def manifest(self) -> NormalizedManifest:
        return self.repository_manifest or self.sync_result.manifest

    @property
    def manifest_path(self) -> Path | None:
        return self.repository_manifest_path or self.sync_result.manifest_path

    @property
    def legacy_manifest(self) -> NormalizedManifest:
        """Compatibility manifest projection of authoritative repository state."""
        return self.sync_result.manifest


class Engine:
    def __init__(
        self,
        root: Path,
        sources: Sequence[SourceDefinition],
        *,
        repository: Repository | None = None,
        adapters: AdapterRegistry | None = None,
    ) -> None:
        self.config = EngineConfig(root=root, sources=list(sources))
        self.repository = repository or Repository(root)
        self.adapters = adapters or builtin_adapter_registry()
        self.planner = SyncPlanner(self.adapters)
        self.executor = SyncExecutor(self.adapters)
        self._owns_repository = repository is None

    @classmethod
    def from_config(
        cls,
        config: EngineConfig,
        *,
        repository: Repository | None = None,
        adapters: AdapterRegistry | None = None,
    ) -> Engine:
        engine = cls(config.root, config.sources, repository=repository, adapters=adapters)
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
        """Plan, execute typed operations, then publish repository-derived compatibility views."""
        plan = self.plan(request)
        execution = await self.executor.execute(plan=plan, config=self.config, repository=self.repository)
        current_manifest = repository_manifest(
            self.repository,
            cfg=self.config,
            run_id=execution.run_id,
        )
        manifest_path: Path | None = None
        mirror_state: MirrorState | None = None
        mirror_state_path: Path | None = None
        if execution.run_id is not None and not plan.request.dry_run:
            with contextlib.suppress(OSError):
                outputs = publish_repository_outputs(
                    self.repository,
                    cfg=self.config,
                    run_id=execution.run_id,
                )
                current_manifest = outputs.manifest
                manifest_path = outputs.canonical_manifest_path
                mirror_state = outputs.mirror_state
                mirror_state_path = outputs.mirror_state_path

        sync_result = SyncResult(
            ok=execution.ok,
            root=self.config.root,
            manifest_path=manifest_path,
            manifest=current_manifest,
        )
        return EngineSyncResult(
            sync_result=sync_result,
            plan=plan,
            execution=execution,
            repository_run_id=execution.run_id,
            observations=execution.observations,
            skipped_source_ids=self._skipped_source_ids(plan, execution),
            repository_manifest=current_manifest,
            repository_manifest_path=manifest_path,
            repository_mirror_state=mirror_state,
            repository_mirror_state_path=mirror_state_path,
        )


__all__ = ["Engine", "EngineSyncResult"]