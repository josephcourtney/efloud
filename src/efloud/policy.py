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


def _ordinary_refresh_decision(snapshot: SourceSnapshot | None) -> RefreshDecision:
    if snapshot is None:
        return RefreshDecision(
            refresh=False,
            reason="no repository snapshot; normal acquisition/cache semantics apply",
        )
    return RefreshDecision(
        refresh=False,
        reason="repository snapshot exists and no forced refresh was requested",
    )


class DefaultSyncPolicy:
    @staticmethod
    def refresh_decision(
        source: SourceDefinition,
        cfg: EngineConfig,
        *,
        snapshot: SourceSnapshot | None,
    ) -> RefreshDecision:
        if cfg.refresh_all:
            return RefreshDecision(refresh=True, reason="refresh_all requested", forced=True)
        if source.kind.value in {"HTTP", "REST", "REST_BASE"} and cfg.refresh_http:
            return RefreshDecision(refresh=True, reason="HTTP-family refresh requested", forced=True)
        if source.kind.value == "RSYNC" and cfg.refresh_rsync:
            return RefreshDecision(refresh=True, reason="rsync refresh requested", forced=True)
        return _ordinary_refresh_decision(snapshot)

    @classmethod
    def should_refresh(cls, source: SourceDefinition, cfg: EngineConfig) -> bool:
        return cls.refresh_decision(source, cfg, snapshot=None).refresh

    @staticmethod
    def source_scope(source: SourceDefinition, cfg: EngineConfig) -> tuple[str, ...]:
        del cfg
        return tuple(source.mirror_paths or ()) if source.mirror_mode is not None else ()

    @staticmethod
    def rsync_paths_for_source(
        *,
        source: SourceDefinition,
        cache_root: Path,
        manifest: NormalizedManifest | None,
    ) -> tuple[str, ...] | None:
        del cache_root, manifest
        return source.mirror_paths if source.mirror_mode is not None else None


@dataclass(frozen=True)
class RoleDrivenSyncPolicy:
    """Generic sync policy with per-role refresh and mirror-scope overrides."""

    http_role_refresh: Mapping[str, bool] = field(default_factory=dict)
    rest_base_refresh: bool | None = None
    rsync_mode: MirrorMode | None = None

    def _configured_refresh_decision(
        self,
        source: SourceDefinition,
        cfg: EngineConfig,
    ) -> RefreshDecision | None:
        if cfg.refresh_all:
            return RefreshDecision(refresh=True, reason="refresh_all requested", forced=True)

        kind_name = source.kind.value
        role_override = (
            bool(self.http_role_refresh[source.role])
            if source.role is not None and source.role in self.http_role_refresh
            else None
        )
        if kind_name in {"HTTP", "REST"} and role_override is not None:
            return RefreshDecision(
                refresh=role_override,
                reason=f"role override for {source.role!r}",
                forced=role_override,
            )
        if kind_name == "REST_BASE" and self.rest_base_refresh is not None:
            return RefreshDecision(
                refresh=bool(self.rest_base_refresh),
                reason="REST collection policy override",
                forced=bool(self.rest_base_refresh),
            )
        if kind_name in {"HTTP", "REST", "REST_BASE"} and cfg.refresh_http:
            return RefreshDecision(refresh=True, reason="HTTP-family refresh requested", forced=True)
        if kind_name == "RSYNC" and cfg.refresh_rsync:
            return RefreshDecision(refresh=True, reason="rsync refresh requested", forced=True)
        return None

    def refresh_decision(
        self,
        source: SourceDefinition,
        cfg: EngineConfig,
        *,
        snapshot: SourceSnapshot | None,
    ) -> RefreshDecision:
        configured = self._configured_refresh_decision(source, cfg)
        return configured if configured is not None else _ordinary_refresh_decision(snapshot)

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
        if self.rsync_mode is None:
            return source.mirror_paths if source.mirror_mode is not None else None
        return source.mirror_paths if source.mirror_mode is self.rsync_mode else None


__all__ = ["DefaultSyncPolicy", "RefreshDecision", "RoleDrivenSyncPolicy", "SyncPolicy"]