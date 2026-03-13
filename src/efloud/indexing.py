from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from efloud.fs import atomic_write_text, safe_json_dump

if TYPE_CHECKING:
    from pathlib import Path

TIndex = TypeVar("TIndex", bound="CachedIndex")


class CachedIndex(Protocol):
    fetched_at: float
    ttl_seconds: int

    def to_dict(self) -> dict[str, object]: ...

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> CachedIndex: ...

    def is_expired(self) -> bool: ...


@dataclass(frozen=True)
class JsonTtlIndex:
    fetched_at: float
    ttl_seconds: int
    payload: dict[str, object]

    @property
    def expires_at(self) -> float:
        return self.fetched_at + self.ttl_seconds

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> dict[str, object]:
        return {
            "fetched_at": self.fetched_at,
            "ttl_seconds": self.ttl_seconds,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> JsonTtlIndex:
        payload = data.get("payload")
        if not isinstance(payload, Mapping):
            msg = "Index payload must be an object."
            raise TypeError(msg)
        return cls(
            fetched_at=float(data.get("fetched_at", 0.0)),
            ttl_seconds=int(data.get("ttl_seconds", 0)),
            payload=dict(payload),
        )


class IndexBuilder(Protocol[TIndex]):
    def __call__(self, *, root: Path) -> TIndex: ...


@dataclass(frozen=True)
class IndexDefinition[TIndex]:
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

    def to_dict(self) -> dict[str, object]:
        return {
            "index_id": self.index_id,
            "path": str(self.path),
            "present": self.present,
            "expired": self.expired,
            "loaded": self.loaded,
            "error": self.error,
        }


class IndexRegistry:
    def __init__(self, definitions: Sequence[IndexDefinition[Any]] = ()) -> None:
        self._definitions: dict[str, IndexDefinition[Any]] = {
            definition.index_id: definition for definition in definitions
        }

    def register(self, definition: IndexDefinition[Any]) -> None:
        self._definitions[definition.index_id] = definition

    def definition(self, index_id: str) -> IndexDefinition[Any] | None:
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
        except Exception as exc:  # pragma: no cover - defensive surface for callers
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


def load_index[TIndex](path: Path, parser: type[TIndex]) -> TIndex | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, Mapping):
        return None
    try:
        return parser.from_dict(raw)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


__all__ = [
    "CachedIndex",
    "IndexDefinition",
    "IndexRegistry",
    "IndexStatus",
    "JsonTtlIndex",
    "load_index",
    "write_index",
]
