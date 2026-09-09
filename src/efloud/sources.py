from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from efloud.inventory import IntegrityExpectation
from efloud.registry import RsyncMode, SourceDefinition, SourceKind


@runtime_checkable
class Source(Protocol):
    """Declarative external data source understood by an Efloud adapter."""

    id: str
    adapter_id: str
    description: str
    role: str | None
    tags: tuple[str, ...]


def _require_text(value: str, *, field: str) -> None:
    if not value.strip():
        msg = f"{field} must not be empty"
        raise ValueError(msg)


def _normalize_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    if any(not tag.strip() for tag in tags):
        msg = "Source tags must not be empty"
        raise ValueError(msg)
    return tuple(sorted(set(tags)))


@dataclass(frozen=True, slots=True)
class HttpSource:
    id: str
    url: str
    description: str = ""
    role: str | None = None
    tags: tuple[str, ...] = ()
    expected_integrity: tuple[IntegrityExpectation, ...] = ()
    adapter_id: str = "efloud:http"

    def __post_init__(self) -> None:
        _require_text(self.id, field="Source id")
        _require_text(self.url, field="Source URL")
        object.__setattr__(self, "tags", _normalize_tags(self.tags))


@dataclass(frozen=True, slots=True)
class RestSource:
    id: str
    url: str
    description: str = ""
    role: str | None = None
    tags: tuple[str, ...] = ()
    expected_integrity: tuple[IntegrityExpectation, ...] = ()
    adapter_id: str = "efloud:rest"

    def __post_init__(self) -> None:
        _require_text(self.id, field="Source id")
        _require_text(self.url, field="Source URL")
        object.__setattr__(self, "tags", _normalize_tags(self.tags))


@dataclass(frozen=True, slots=True)
class RsyncSource:
    id: str
    url: str
    description: str = ""
    paths: tuple[str, ...] = ()
    port: int | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    role: str | None = None
    tags: tuple[str, ...] = ()
    adapter_id: str = "efloud:rsync"

    def __post_init__(self) -> None:
        _require_text(self.id, field="Source id")
        _require_text(self.url, field="Source URL")
        if self.port is not None and not 1 <= self.port <= 65535:
            msg = "Rsync port must be between 1 and 65535"
            raise ValueError(msg)
        object.__setattr__(self, "paths", tuple(sorted(set(self.paths))))
        object.__setattr__(self, "include", tuple(self.include))
        object.__setattr__(self, "exclude", tuple(self.exclude))
        object.__setattr__(self, "tags", _normalize_tags(self.tags))


@dataclass(frozen=True, slots=True)
class CollectionSource:
    """Declarative collection source; canonical execution is completed in TODO 2."""

    id: str
    url: str
    description: str = ""
    role: str | None = None
    tags: tuple[str, ...] = ()
    adapter_id: str = "efloud:collection"

    def __post_init__(self) -> None:
        _require_text(self.id, field="Source id")
        _require_text(self.url, field="Source URL")
        object.__setattr__(self, "tags", _normalize_tags(self.tags))


def legacy_source_definition(source: Source) -> SourceDefinition:
    """Bridge clean built-in source values onto the current canonical executor."""
    if isinstance(source, HttpSource):
        return SourceDefinition(
            id=source.id,
            description=source.description or source.id,
            url=source.url,
            kind=SourceKind.HTTP,
            role=source.role,
            tags=source.tags,
            expected_integrity=source.expected_integrity,
        )
    if isinstance(source, RestSource):
        return SourceDefinition(
            id=source.id,
            description=source.description or source.id,
            url=source.url,
            kind=SourceKind.REST,
            role=source.role,
            tags=source.tags,
            expected_integrity=source.expected_integrity,
        )
    if isinstance(source, RsyncSource):
        return SourceDefinition(
            id=source.id,
            description=source.description or source.id,
            url=source.url,
            kind=SourceKind.RSYNC,
            rsync_mode=RsyncMode.PATHS if source.paths else RsyncMode.FULL,
            rsync_paths=source.paths or None,
            port=source.port,
            include=source.include or None,
            exclude=source.exclude or None,
            role=source.role,
            tags=source.tags,
        )
    if isinstance(source, CollectionSource):
        return SourceDefinition(
            id=source.id,
            description=source.description or source.id,
            url=source.url,
            kind=SourceKind.REST_BASE,
            role=source.role,
            tags=source.tags,
        )
    msg = f"Adapter {source.adapter_id!r} is not yet connected to the canonical executor"
    raise ValueError(msg)


__all__ = ["CollectionSource", "HttpSource", "RestSource", "RsyncSource", "Source"]
