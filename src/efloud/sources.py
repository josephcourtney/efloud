from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from os import PathLike

    from efloud.inventory import IntegrityExpectation
    from efloud.json_types import JsonObject

_MIN_RSYNC_PORT = 1
_MAX_RSYNC_PORT = 65535


@runtime_checkable
class Source(Protocol):
    """Open declarative source contract dispatched by namespaced adapter identity."""

    @property
    def id(self) -> str: ...

    @property
    def adapter_id(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def role(self) -> str | None: ...

    @property
    def tags(self) -> tuple[str, ...]: ...

    def definition(self) -> JsonObject: ...


def _require_text(value: str, *, field: str) -> None:
    if not value.strip():
        msg = f"{field} must not be empty"
        raise ValueError(msg)


def _normalize_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    if any(not tag.strip() for tag in tags):
        msg = "Source tags must not be empty"
        raise ValueError(msg)
    return tuple(sorted(set(tags)))


def _common_definition(source: Source) -> JsonObject:
    payload: JsonObject = {
        "adapter_id": source.adapter_id,
        "description": source.description,
        "tags": list(source.tags),
    }
    if source.role is not None:
        payload["role"] = source.role
    return payload


@dataclass(frozen=True, slots=True)
class LocalSource:
    """One explicit local file imported as an immutable source observation."""

    id: str
    path: str | PathLike[str]
    description: str = ""
    artifact_key: str | None = None
    media_type: str | None = None
    role: str | None = None
    tags: tuple[str, ...] = ()
    expected_integrity: tuple[IntegrityExpectation, ...] = ()
    adapter_id: str = field(default="efloud:local", init=False)

    def __post_init__(self) -> None:
        """Validate and normalize the local acquisition declaration."""
        _require_text(self.id, field="Source id")
        normalized_path = Path(self.path).expanduser().resolve(strict=False)
        _require_text(normalized_path.as_posix(), field="Source path")
        if self.artifact_key is not None:
            _require_text(self.artifact_key, field="Artifact key")
        object.__setattr__(self, "path", normalized_path)
        object.__setattr__(self, "tags", _normalize_tags(self.tags))

    @property
    def resolved_artifact_key(self) -> str:
        return self.artifact_key or f"source:{self.id}"

    def definition(self) -> JsonObject:
        payload = _common_definition(self)
        payload.update({
            "path": Path(self.path).as_posix(),
            "protocol": "local",
            "artifact_key": self.resolved_artifact_key,
        })
        if self.media_type is not None:
            payload["media_type"] = self.media_type
        if self.expected_integrity:
            payload["expected_integrity"] = [item.to_dict() for item in self.expected_integrity]
        return payload


@dataclass(frozen=True, slots=True)
class HttpSource:
    id: str
    url: str
    description: str = ""
    cache_name: str | None = None
    role: str | None = None
    tags: tuple[str, ...] = ()
    expected_integrity: tuple[IntegrityExpectation, ...] = ()
    adapter_id: str = field(default="efloud:http", init=False)

    def __post_init__(self) -> None:
        """Validate and normalize the declarative source."""
        _require_text(self.id, field="Source id")
        _require_text(self.url, field="Source URL")
        object.__setattr__(self, "tags", _normalize_tags(self.tags))

    def definition(self) -> JsonObject:
        payload = _common_definition(self)
        payload.update({"url": self.url, "protocol": "http"})
        if self.cache_name is not None:
            payload["cache_name"] = self.cache_name
        if self.expected_integrity:
            payload["expected_integrity"] = [item.to_dict() for item in self.expected_integrity]
        return payload


@dataclass(frozen=True, slots=True)
class RestSource:
    id: str
    url: str
    description: str = ""
    cache_name: str | None = None
    role: str | None = None
    tags: tuple[str, ...] = ()
    expected_integrity: tuple[IntegrityExpectation, ...] = ()
    adapter_id: str = field(default="efloud:rest", init=False)

    def __post_init__(self) -> None:
        """Validate and normalize the declarative source."""
        _require_text(self.id, field="Source id")
        _require_text(self.url, field="Source URL")
        object.__setattr__(self, "tags", _normalize_tags(self.tags))

    def definition(self) -> JsonObject:
        payload = _common_definition(self)
        payload.update({"url": self.url, "protocol": "rest"})
        if self.cache_name is not None:
            payload["cache_name"] = self.cache_name
        if self.expected_integrity:
            payload["expected_integrity"] = [item.to_dict() for item in self.expected_integrity]
        return payload


@dataclass(frozen=True, slots=True)
class RsyncSource:
    id: str
    url: str
    description: str = ""
    paths: tuple[str, ...] = ()
    local_subpath: str | None = None
    port: int | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    role: str | None = None
    tags: tuple[str, ...] = ()
    adapter_id: str = field(default="efloud:rsync", init=False)

    def __post_init__(self) -> None:
        """Validate and normalize the declarative source."""
        _require_text(self.id, field="Source id")
        _require_text(self.url, field="Source URL")
        if self.port is not None and not _MIN_RSYNC_PORT <= self.port <= _MAX_RSYNC_PORT:
            msg = f"Rsync port must be between {_MIN_RSYNC_PORT} and {_MAX_RSYNC_PORT}"
            raise ValueError(msg)
        object.__setattr__(self, "paths", tuple(sorted(set(self.paths))))
        object.__setattr__(self, "include", tuple(self.include))
        object.__setattr__(self, "exclude", tuple(self.exclude))
        object.__setattr__(self, "tags", _normalize_tags(self.tags))

    def definition(self) -> JsonObject:
        payload = _common_definition(self)
        payload.update({
            "url": self.url,
            "protocol": "rsync",
            "paths": list(self.paths),
            "include": list(self.include),
            "exclude": list(self.exclude),
        })
        if self.local_subpath is not None:
            payload["local_subpath"] = self.local_subpath
        if self.port is not None:
            payload["port"] = self.port
        return payload


@dataclass(frozen=True, slots=True)
class CollectionSource:
    """Declarative HTTP collection whose inventory/fetch behavior is supplied separately."""

    id: str
    url: str
    description: str = ""
    role: str | None = None
    tags: tuple[str, ...] = ()
    adapter_id: str = field(default="efloud:collection", init=False)

    def __post_init__(self) -> None:
        """Validate and normalize the declarative source."""
        _require_text(self.id, field="Source id")
        _require_text(self.url, field="Source URL")
        object.__setattr__(self, "tags", _normalize_tags(self.tags))

    def definition(self) -> JsonObject:
        payload = _common_definition(self)
        payload.update({"url": self.url, "protocol": "collection"})
        return payload


def source_definition(source: Source) -> JsonObject:
    """Return the canonical persisted source definition supplied by the source itself."""
    return source.definition()


__all__ = [
    "CollectionSource",
    "HttpSource",
    "LocalSource",
    "RestSource",
    "RsyncSource",
    "Source",
    "source_definition",
]
