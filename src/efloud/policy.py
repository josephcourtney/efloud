from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from efloud.sources import CollectionSource, RsyncSource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from efloud.json_types import JsonObject
    from efloud.planning import SyncRequest
    from efloud.repository_models import SourceSnapshot
    from efloud.sources import Source


@dataclass(frozen=True, slots=True)
class RefreshDecision:
    """Serializable explanation of whether acquisition should bypass cached state."""

    refresh: bool
    reason: str
    forced: bool = False

    def to_dict(self) -> JsonObject:
        return {"refresh": self.refresh, "reason": self.reason, "forced": self.forced}


class SyncPolicy(Protocol):
    def refresh_decision(
        self,
        source: Source,
        request: SyncRequest,
        *,
        snapshot: SourceSnapshot | None,
    ) -> RefreshDecision: ...

    def source_scope(self, source: Source, request: SyncRequest) -> tuple[str, ...]: ...


def _ordinary_refresh_decision(snapshot: SourceSnapshot | None) -> RefreshDecision:
    if snapshot is None:
        return RefreshDecision(False, "no repository snapshot; normal acquisition/cache semantics apply")
    return RefreshDecision(False, "repository snapshot exists and no forced refresh was requested")


class DefaultSyncPolicy:
    @staticmethod
    def refresh_decision(
        source: Source,
        request: SyncRequest,
        *,
        snapshot: SourceSnapshot | None,
    ) -> RefreshDecision:
        if request.refresh:
            return RefreshDecision(True, "refresh requested for the sync", forced=True)
        if source.id in request.refresh_source_ids:
            return RefreshDecision(True, f"refresh requested for source {source.id!r}", forced=True)
        return _ordinary_refresh_decision(snapshot)

    @staticmethod
    def source_scope(source: Source, request: SyncRequest) -> tuple[str, ...]:
        del request
        return source.paths if isinstance(source, RsyncSource) else ()


@dataclass(frozen=True, slots=True)
class RoleDrivenSyncPolicy:
    """Optional semantic refresh overrides layered on caller sync intent."""

    role_refresh: Mapping[str, bool] = field(default_factory=dict)
    collection_refresh: bool | None = None

    def refresh_decision(
        self,
        source: Source,
        request: SyncRequest,
        *,
        snapshot: SourceSnapshot | None,
    ) -> RefreshDecision:
        explicit = DefaultSyncPolicy.refresh_decision(source, request, snapshot=snapshot)
        if explicit.forced:
            return explicit
        if source.role is not None and source.role in self.role_refresh:
            refresh = bool(self.role_refresh[source.role])
            return RefreshDecision(refresh, f"role override for {source.role!r}", forced=refresh)
        if isinstance(source, CollectionSource) and self.collection_refresh is not None:
            refresh = bool(self.collection_refresh)
            return RefreshDecision(refresh, "collection policy override", forced=refresh)
        return explicit

    @staticmethod
    def source_scope(source: Source, request: SyncRequest) -> tuple[str, ...]:
        return DefaultSyncPolicy.source_scope(source, request)


__all__ = ["DefaultSyncPolicy", "RefreshDecision", "RoleDrivenSyncPolicy", "SyncPolicy"]
