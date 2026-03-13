from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.models import EngineConfig, NormalizedManifest
    from efloud.registry import SourceDefinition


class SyncPolicy(Protocol):
    def should_refresh(self, source: SourceDefinition, cfg: EngineConfig) -> bool: ...

    def rsync_paths_for_source(
        self,
        *,
        source: SourceDefinition,
        cache_root: Path,
        manifest: NormalizedManifest | None,
    ) -> tuple[str, ...] | None: ...


class DefaultSyncPolicy:
    def should_refresh(self, source: SourceDefinition, cfg: EngineConfig) -> bool:
        if cfg.refresh_all:
            return True
        if source.kind.value in {"HTTP", "REST", "REST_BASE"}:
            return cfg.refresh_http
        if source.kind.value == "RSYNC":
            return cfg.refresh_rsync
        return False

    def rsync_paths_for_source(
        self, *, source: SourceDefinition, cache_root: Path, manifest: NormalizedManifest | None
    ) -> tuple[str, ...] | None:
        return source.mirror_paths if source.mirror_mode is not None else None
