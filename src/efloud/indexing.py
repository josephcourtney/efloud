from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from efloud.derivation import DerivedTaskSpec, derivation_key_for
from efloud.json_types import JsonObject, copy_json_mapping, json_mapping_or_none
from efloud.repository_models import ArtifactKey, canonical_json_bytes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from efloud.derivation import DependencySemantics, DerivationKey
    from efloud.repository_capabilities import ExtensionReader, RepositoryWriter
    from efloud.repository_models import ArtifactObservation, OperationId, RunId


class DerivedIndexBuilder(Protocol):
    """Build one deterministic semantic index from exact repository inputs."""

    def __call__(
        self,
        *,
        repository: ExtensionReader,
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
    """Build semantic indexes as repository derivations without TTL invalidation."""

    def __init__(self, definitions: Sequence[DerivedIndexDefinition] = ()) -> None:
        self._definitions = {definition.index_id: definition for definition in definitions}

    def register(self, definition: DerivedIndexDefinition) -> None:
        self._definitions[definition.index_id] = definition

    def definition(self, index_id: str) -> DerivedIndexDefinition | None:
        return self._definitions.get(index_id)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    @staticmethod
    def _payload_for_observation(
        repository: ExtensionReader,
        observation: ArtifactObservation,
    ) -> JsonObject:
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
        repository: RepositoryWriter,
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
        repository: RepositoryWriter,
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


__all__ = [
    "DerivedIndexBuilder",
    "DerivedIndexDefinition",
    "DerivedIndexRegistry",
    "DerivedIndexResult",
]
