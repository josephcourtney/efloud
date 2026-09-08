from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from efloud.json_types import JsonObject
    from efloud.models import EngineConfig, NormalizedManifest
    from efloud.registry import MirrorMode, SourceDefinition
    from efloud.repository_models import SourceSnapshot


@dataclass(frozen=True, slots=True)
class RefreshDecision:
    """Serializable explanation of whether acquisition should bypass cached state."""

    refresh: bool
    reason: str
    forced: bool = False

    def to_dict(self) -> JsonObject:
        return {
            "refresh": self.refresh,
            "reason": self.reason,
            "forced": self.forced,
        }


class SyncPolicy(Protocol):
    def refresh_decision(
        self,
        source: SourceDefinition,
        cfg: EngineConfig,
        *,
        snapshot: SourceSnapshot | None,
    ) -> RefreshDecision: ...

    def source_scope(self, source: SourceDefinition, cfg: EngineConfig) -> tuple[str, ...]: ...

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
    def refresh_decision(
        source: SourceDefinition,
        cfg: EngineConfig,
        *,
        snapshot: SourceSnapshot | None,
    ) -> RefreshDecision:
        if cfg.refresh_all:
            return RefreshDecision(True, "refresh_all requested", forced=True)
        if source.kind.value in {"HTTP", "REST", "REST_BASE"} and cfg.refresh_http:
            return RefreshDecision(True, "HTTP-family refresh requested", forced=True)
        if source.kind.value == "RSYNC" and cfg.refresh_rsync:
            return RefreshDecision(True, "rsync refresh requested", forced=True)
        if snapshot is None:
            return RefreshDecision(False, "no repository snapshot; normal acquisition/cache semantics apply")
        return RefreshDecision(False, "repository snapshot exists and no forced refresh was requested")

    @classmethod
    def should_refresh(cls, source: SourceDefinition, cfg: EngineConfig) -> bool:
        return cls.refresh_decision(source, cfg, snapshot=None).refresh

    @staticmethod
    def source_scope(source: SourceDefinition, cfg: EngineConfig) -> tuple[str, ...]:
        del cfg
        return tuple(source.mirror_paths or ()) if source.mirror_mode is not None else ()

    @classmethod
    def rsync_paths_for_source(
        cls,
        *,
        source: SourceDefinition,
        cache_root: Path,
        manifest: NormalizedManifest | None,
    ) -> tuple[str, ...] | None:
        del cache_root, manifest
        scope = cls.source_scope(source, _unused_engine_config(source))
        return scope or None


@dataclass(frozen=True)
class RoleDrivenSyncPolicy:
    """Generic sync policy with per-role refresh and mirror-scope overrides."""

    http_role_refresh: Mapping[str, bool] = field(default_factory=dict)
    rest_base_refresh: bool | None = None
    rsync_mode: MirrorMode | None = None

    def refresh_decision(
        self,
        source: SourceDefinition,
        cfg: EngineConfig,
        *,
        snapshot: SourceSnapshot | None,
    ) -> RefreshDecision:
        if cfg.refresh_all:
            return RefreshDecision(True, "refresh_all requested", forced=True)

        kind_name = source.kind.value
        role_override = (
            bool(self.http_role_refresh[source.role])
            if source.role is not None and source.role in self.http_role_refresh
            else None
        )
        if kind_name in {"HTTP", "REST"} and role_override is not None:
            return RefreshDecision(role_override, f"role override for {source.role!r}", forced=role_override)
        if kind_name in {"HTTP", "REST"} and cfg.refresh_http:
            return RefreshDecision(True, "HTTP-family refresh requested", forced=True)
        if kind_name == "REST_BASE" and self.rest_base_refresh is not None:
            return RefreshDecision(
                bool(self.rest_base_refresh),
                "REST collection policy override",
                forced=bool(self.rest_base_refresh),
            )
        if kind_name == "REST_BASE" and cfg.refresh_http:
            return RefreshDecision(True, "HTTP-family refresh requested", forced=True)
        if kind_name == "RSYNC" and cfg.refresh_rsync:
            return RefreshDecision(True, "rsync refresh requested", forced=True)
        if snapshot is None:
            return RefreshDecision(False, "no repository snapshot; normal acquisition/cache semantics apply")
        return RefreshDecision(False, "repository snapshot exists and no forced refresh was requested")

    def should_refresh(self, source: SourceDefinition, cfg: EngineConfig) -> bool:
        return self.refresh_decision(source, cfg, snapshot=None).refresh

    def source_scope(self, source: SourceDefinition, cfg: EngineConfig) -> tuple[str, ...]:
        del cfg
        if self.rsync_mode is None:
            return tuple(source.mirror_paths or ()) if source.mirror_mode is not None else ()
        return tuple(source.mirror_paths or ()) if source.mirror_mode is self.rsync_mode else ()

    def rsync_paths_for_source(
        self,
        *,
        source: SourceDefinition,
        cache_root: Path,
        manifest: NormalizedManifest | None,
    ) -> tuple[str, ...] | None:
        del cache_root, manifest
        scope = self.source_scope(source, _unused_engine_config(source))
        return scope or None


def _unused_engine_config(source: SourceDefinition) -> EngineConfig:
    """Minimal compatibility value for legacy policy methods whose cfg is unused."""
    from pathlib import Path

    from efloud.models import EngineConfig

    return EngineConfig(root=Path("."), sources=[source])


__all__ = ["DefaultSyncPolicy", "RefreshDecision", "RoleDrivenSyncPolicy", "SyncPolicy"]
