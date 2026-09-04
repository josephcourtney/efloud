from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from efloud.models import EngineConfig, NormalizedManifest, SyncResult
from efloud.registry import SourceDefinition
from efloud.repository import Repository
from efloud.repository_models import ObservationId, RunId
from efloud.repository_recording import RepositorySyncRecorder
from efloud.sync import sync as legacy_sync


@dataclass(frozen=True, slots=True)
class EngineSyncResult:
    sync_result: SyncResult
    repository_run_id: RunId
    observations: tuple[ObservationId, ...]
    skipped_source_ids: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.sync_result.ok

    @property
    def root(self) -> Path:
        return self.sync_result.root

    @property
    def manifest(self) -> NormalizedManifest:
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
        engine = cls.__new__(cls)
        engine.config = config
        engine.repository = repository or Repository(config.root)
        engine._owns_repository = repository is None
        return engine

    def __enter__(self) -> Engine:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()

    async def sync(self) -> EngineSyncResult:
        recorder = RepositorySyncRecorder(self.repository, self.config)
        try:
            sync_result = await legacy_sync(self.config)
            recorder.import_result(sync_result)
        except BaseException:
            recorder.finish(ok=False)
            raise
        recorder.finish(ok=sync_result.ok)
        return EngineSyncResult(
            sync_result=sync_result,
            repository_run_id=recorder.run_id,
            observations=tuple(recorder.observations),
            skipped_source_ids=tuple(recorder.skipped_source_ids),
        )


__all__ = ["Engine", "EngineSyncResult"]
