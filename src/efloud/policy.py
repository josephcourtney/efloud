from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from efloud.models import EngineConfig, NormalizedManifest
    from efloud.registry import MirrorMode, SourceDefinition


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
    @staticmethod
    def should_refresh(source: SourceDefinition, cfg: EngineConfig) -> bool:
        if cfg.refresh_all:
            return True
        if source.kind.value in {"HTTP", "REST", "REST_BASE"}:
            return cfg.refresh_http
        if source.kind.value == "RSYNC":
            return cfg.refresh_rsync
        return False

    @staticmethod
    def rsync_paths_for_source(
        *, source: SourceDefinition, cache_root: Path, manifest: NormalizedManifest | None
    ) -> tuple[str, ...] | None:
        del cache_root, manifest
        return source.mirror_paths if source.mirror_mode is not None else None


@dataclass(frozen=True)
class RoleDrivenSyncPolicy:
    """
    Generic sync policy with per-role refresh overrides.

    Applications can keep transport-level refresh flags in `EngineConfig` while
    supplying fine-grained role semantics from their own configuration layer.
    """

    http_role_refresh: Mapping[str, bool] = field(default_factory=dict)
    rest_base_refresh: bool | None = None
    rsync_mode: MirrorMode | None = None

    def should_refresh(self, source: SourceDefinition, cfg: EngineConfig) -> bool:
        if cfg.refresh_all:
            return True

        kind_name = source.kind.value
        role_override = (
            bool(self.http_role_refresh[source.role])
            if source.role is not None and source.role in self.http_role_refresh
            else None
        )
        if kind_name in {"HTTP", "REST"}:
            return role_override if role_override is not None else cfg.refresh_http
        if kind_name == "REST_BASE":
            return bool(self.rest_base_refresh) if self.rest_base_refresh is not None else cfg.refresh_http
        return cfg.refresh_rsync if kind_name == "RSYNC" else False

    def rsync_paths_for_source(
        self,
        *,
        source: SourceDefinition,
        cache_root: Path,
        manifest: NormalizedManifest | None,
    ) -> tuple[str, ...] | None:
        del cache_root, manifest
        if self.rsync_mode is None:
            return source.mirror_paths if source.mirror_mode is not None else None
        return source.mirror_paths if source.mirror_mode is self.rsync_mode else None
