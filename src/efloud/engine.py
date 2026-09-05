from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from efloud.acquisition import acquire as legacy_sync
from efloud.models import EngineConfig, NormalizedManifest, SyncResult
from efloud.repository import Repository
from efloud.repository_compat import repository_manifest
from efloud.repository_outputs import publish_repository_outputs
from efloud.repository_recording import RepositorySyncRecorder

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
    repository_run_id: RunId
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
        """Return transient acquisition evidence retained for compatibility/debugging."""
        return self.sync_result.manifest


class Engine:
    def __init__(
        self,
        root: Path,
        sources: Sequence[SourceDefinition],
        *,
        repository: Repository | None = None,
    ) -> None:
        self.config = EngineConfig(root=root, sources=list(sources))
        self.repository = repository or Repository(root)
        self._owns_repository = repository is None

    @classmethod
    def from_config(
        cls,
        config: EngineConfig,
        *,
        repository: Repository | None = None,
    ) -> Engine:
        engine = cls(config.root, config.sources, repository=repository)
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

    def _fail_running_operations(self, run_id: RunId) -> None:
        for operation in self.repository.metadata.operations_for_run(run_id):
            if operation.status != "running":
                continue
            self.repository.finish_operation(
                operation.operation_id,
                status="failed",
                details={"error": "repository import aborted before operation completion"},
            )

    async def sync(self) -> EngineSyncResult:
        """Acquire transient evidence, commit it, then publish repository-derived views."""
        recorder = RepositorySyncRecorder(self.repository, self.config)
        try:
            sync_result = await legacy_sync(self.config)
            await recorder.import_result(sync_result)
        except BaseException:
            self._fail_running_operations(recorder.run_id)
            recorder.finish(ok=False)
            raise
        recorder.finish(ok=sync_result.ok)

        current_manifest: NormalizedManifest | None = None
        manifest_path: Path | None = None
        mirror_state: MirrorState | None = None
        mirror_state_path: Path | None = None
        if not self.config.dry_run:
            current_manifest = repository_manifest(
                self.repository,
                cfg=self.config,
                run_id=recorder.run_id,
            )
            with contextlib.suppress(OSError):
                outputs = publish_repository_outputs(
                    self.repository,
                    cfg=self.config,
                    run_id=recorder.run_id,
                )
                current_manifest = outputs.manifest
                manifest_path = outputs.canonical_manifest_path
                mirror_state = outputs.mirror_state
                mirror_state_path = outputs.mirror_state_path

        return EngineSyncResult(
            sync_result=sync_result,
            repository_run_id=recorder.run_id,
            observations=tuple(recorder.observations),
            skipped_source_ids=tuple(recorder.skipped_source_ids),
            repository_manifest=current_manifest,
            repository_manifest_path=manifest_path,
            repository_mirror_state=mirror_state,
            repository_mirror_state_path=mirror_state_path,
        )


__all__ = ["Engine", "EngineSyncResult"]
