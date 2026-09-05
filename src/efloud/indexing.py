from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, Self

from efloud.derivation import DerivedTaskSpec, derivation_key_for
from efloud.fs import atomic_write_text, safe_json_dump
from efloud.json_types import JsonMapping, JsonObject, JsonValue, copy_json_mapping, json_mapping_or_none
from efloud.repository_models import ArtifactKey, canonical_json_bytes

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from efloud.derivation import DependencySemantics, DerivationKey
    from efloud.repository import Repository
    from efloud.repository_models import ArtifactObservation, OperationId, RunId


class CachedIndex(Protocol):
    """Compatibility contract for wall-clock caches, not deterministic derivations."""

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
    """Legacy/source-refresh JSON cache whose validity is intentionally time based."""

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
    """Compatibility registry for TTL-backed external/source caches."""

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
        except (OSError, RuntimeError, TypeError, ValueError) as exc:  # pragma: no cover - defensive cache parse failures are environment-dependent.
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


class DerivedIndexBuilder(Protocol):
    def __call__(
        self,
        *,
        repository: Repository,
        inputs: tuple[ArtifactObservation, ...],
    ) -> JsonObject: ...


@dataclass(frozen=True, slots=True)
class DerivedIndexDefinition:
    """Repository-backed semantic index defined as a deterministic derivation."""

    index_id: str
    task_version: str
    build: DerivedIndexBuilder
    dependency_semantics: DependencySemantics = "content"
    parameters: JsonObject = field(default_factory=dict)
    description: str = ""

    @property
    def artifact_key(self) -> ArtifactKey:
        return ArtifactKey(f"index:{self.index_id}")

    @property
    def spec(self) -> DerivedTaskSpec:
        return DerivedTaskSpec(
            task_id=f"efloud:index:{self.index_id}",
            task_version=self.task_version,
            deterministic=True,
            dependency_semantics=self.dependency_semantics,
            parameters=self.parameters,
        )


@dataclass(frozen=True, slots=True)
class DerivedIndexResult:
    observation: ArtifactObservation
    payload: JsonObject
    reused: bool


class DerivedIndexRegistry:
    """Build semantic indexes as ordinary repository derived artifacts without TTL invalidation."""

    def __init__(self, definitions: Sequence[DerivedIndexDefinition] = ()) -> None:
        self._definitions = {definition.index_id: definition for definition in definitions}

    def register(self, definition: DerivedIndexDefinition) -> None:
        self._definitions[definition.index_id] = definition

    def definition(self, index_id: str) -> DerivedIndexDefinition | None:
        return self._definitions.get(index_id)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    @staticmethod
    def _payload_for_observation(repository: Repository, observation: ArtifactObservation) -> JsonObject:
        with repository.open_content(observation.content_id) as stream:
            decoded = json.loads(stream.read().decode("utf-8"))
        mapping = json_mapping_or_none(decoded)
        if mapping is None:
            msg = f"Derived index content is not a JSON object: {observation.content_id}"
            raise TypeError(msg)
        return copy_json_mapping(mapping)

    def _materialize(
        self,
        definition: DerivedIndexDefinition,
        *,
        repository: Repository,
        run_id: RunId,
        operation_id: OperationId,
        input_observations: tuple[ArtifactObservation, ...],
        derivation_key: DerivationKey,
        observed_at: float | None,
    ) -> DerivedIndexResult:
        reusable = repository.reusable_derived_content(derivation_key, definition.artifact_key)
        if reusable is None:
            payload = definition.build(repository=repository, inputs=input_observations)
            data = canonical_json_bytes(payload)
        else:
            payload = {}
            data = b""
        observation = repository.record_derived_bytes(
            definition.artifact_key,
            data,
            derivation_key=derivation_key,
            run_id=run_id,
            operation_id=operation_id,
            inputs=input_observations,
            observed_at=observed_at,
            media_type="application/json",
            metadata={"index_id": definition.index_id, "semantic_index": True},
        )
        if reusable is not None:
            payload = self._payload_for_observation(repository, observation)
        return DerivedIndexResult(
            observation=observation,
            payload=payload,
            reused=reusable is not None,
        )

    def build(
        self,
        index_id: str,
        *,
        repository: Repository,
        run_id: RunId,
        inputs: Sequence[ArtifactObservation] = (),
        observed_at: float | None = None,
    ) -> DerivedIndexResult:
        definition = self.definition(index_id)
        if definition is None:
            msg = f"Unknown derived index identifier: {index_id!r}"
            raise ValueError(msg)
        input_observations = tuple(inputs)
        spec = definition.spec
        derivation_key = derivation_key_for(
            spec,
            outputs=(definition.artifact_key,),
            inputs=input_observations,
        )
        operation_id = repository.start_operation(
            run_id=run_id,
            kind="derive-index",
            subject=index_id,
            producer=spec.producer,
            parameters={
                "derived_task_spec": spec.to_dict(),
                "derivation_key": str(derivation_key),
            },
        )
        try:
            result = self._materialize(
                definition,
                repository=repository,
                run_id=run_id,
                operation_id=operation_id,
                input_observations=input_observations,
                derivation_key=derivation_key,
                observed_at=observed_at,
            )
        except Exception as exc:
            repository.finish_operation(
                operation_id,
                status="failed",
                details={"error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        repository.finish_operation(
            operation_id,
            status="succeeded",
            details={
                "derivation_key": str(derivation_key),
                "reused": result.reused,
                "output_observation_id": str(result.observation.observation_id),
            },
        )
        return result


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
    "DerivedIndexDefinition",
    "DerivedIndexRegistry",
    "DerivedIndexResult",
    "IndexDefinition",
    "IndexRegistry",
    "IndexStatus",
    "JsonTtlIndex",
    "load_index",
    "write_index",
]
