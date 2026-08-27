from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self

from efloud.fs import atomic_write_text, safe_json_dump
from efloud.json_types import JsonMapping, JsonObject, JsonValue, copy_json_mapping, json_mapping_or_none

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class CachedIndex(Protocol):
    fetched_at: float
    ttl_seconds: int

    @property
    def fetched_at(self) -> float: ...

    @property
    def ttl_seconds(self) -> int: ...

    def to_dict(self) -> JsonObject: ...

    @classmethod
    def from_dict(cls, data: JsonMapping) -> Self: ...

    def is_expired(self) -> bool: ...


@dataclass(frozen=True)
class JsonTtlIndex:
    fetched_at: float
    ttl_seconds: int
    payload: JsonObject

    @property
    def expires_at(self) -> float:
        return self.fetched_at + self.ttl_seconds

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> JsonObject:
        return {
            "fetched_at": self.fetched_at,
            "ttl_seconds": self.ttl_seconds,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: JsonMapping) -> JsonTtlIndex:
        payload = json_mapping_or_none(data.get("payload"))
        if payload is None:
            msg = "Index payload must be an object."
            raise TypeError(msg)
        return cls(
            fetched_at=_float_value(data.get("fetched_at"), default=0.0),
            ttl_seconds=_int_value(data.get("ttl_seconds"), default=0),
            payload=copy_json_mapping(payload),
        )


class IndexBuilder[TIndex: CachedIndex](Protocol):
    def __call__(self, *, root: Path) -> TIndex: ...


@dataclass(frozen=True)
class IndexDefinition[TIndex: CachedIndex]:
    index_id: str
    filename: str
    ttl_seconds: int
    build: IndexBuilder[TIndex]
    parser: type[TIndex]
    description: str = ""


@dataclass(frozen=True)
class IndexStatus:
    index_id: str
    path: Path
    present: bool
    expired: bool | None
    loaded: bool
    error: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "index_id": self.index_id,
            "path": str(self.path),
            "present": self.present,
            "expired": self.expired,
            "loaded": self.loaded,
            "error": self.error,
        }


class IndexRegistry:
    def __init__(self, definitions: Sequence[IndexDefinition[CachedIndex]] = ()) -> None:
        self._definitions: dict[str, IndexDefinition[CachedIndex]] = {
            definition.index_id: definition for definition in definitions
        }

    def register(self, definition: IndexDefinition[CachedIndex]) -> None:
        self._definitions[definition.index_id] = definition

    def definition(self, index_id: str) -> IndexDefinition[CachedIndex] | None:
        return self._definitions.get(index_id)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def path_for(self, index_id: str, *, root: Path) -> Path:
        definition = self.definition(index_id)
        if definition is None:
            msg = f"Unknown index identifier: {index_id!r}"
            raise ValueError(msg)
        return root / definition.filename

    def load(self, index_id: str, *, root: Path) -> CachedIndex | None:
        definition = self.definition(index_id)
        if definition is None:
            msg = f"Unknown index identifier: {index_id!r}"
            raise ValueError(msg)
        return load_index(root / definition.filename, definition.parser)

    def build(self, index_id: str, *, root: Path, write: bool = True) -> CachedIndex:
        definition = self.definition(index_id)
        if definition is None:
            msg = f"Unknown index identifier: {index_id!r}"
            raise ValueError(msg)

        path = root / definition.filename
        cached = load_index(path, definition.parser)
        if cached is not None and not cached.is_expired():
            return cached

        built = definition.build(root=root)
        if write:
            write_index(path, built)
        return built

    def status(self, index_id: str, *, root: Path) -> IndexStatus:
        definition = self.definition(index_id)
        if definition is None:
            msg = f"Unknown index identifier: {index_id!r}"
            raise ValueError(msg)

        path = root / definition.filename
        if not path.exists():
            return IndexStatus(index_id=index_id, path=path, present=False, expired=None, loaded=False)

        try:
            loaded = load_index(path, definition.parser)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:  # pragma: no cover
            return IndexStatus(
                index_id=index_id,
                path=path,
                present=True,
                expired=None,
                loaded=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        if loaded is None:
            return IndexStatus(
                index_id=index_id,
                path=path,
                present=True,
                expired=None,
                loaded=False,
                error="Index exists but could not be parsed.",
            )

        return IndexStatus(
            index_id=index_id,
            path=path,
            present=True,
            expired=loaded.is_expired(),
            loaded=True,
        )


def write_index(path: Path, index: CachedIndex) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, safe_json_dump(index.to_dict()))


def load_index[TIndex: CachedIndex](path: Path, parser: type[TIndex]) -> TIndex | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_mapping = json_mapping_or_none(raw)
    if raw_mapping is None:
        return None
    try:
        return parser.from_dict(raw_mapping)
    except (TypeError, ValueError):
        return None


def _float_value(value: JsonValue | None, *, default: float) -> float:
    return float(value) if isinstance(value, int | float) else default


def _int_value(value: JsonValue | None, *, default: int) -> int:
    return int(value) if isinstance(value, int | float) else default


__all__ = [
    "CachedIndex",
    "IndexDefinition",
    "IndexRegistry",
    "IndexStatus",
    "JsonTtlIndex",
    "load_index",
    "write_index",
]
