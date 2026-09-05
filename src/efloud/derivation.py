from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NewType

from efloud.repository_models import ProducerRef, stable_id

if TYPE_CHECKING:
    from collections.abc import Iterable

    from efloud.json_types import JsonObject
    from efloud.repository_models import ArtifactKey, ArtifactObservation

DerivationKey = NewType("DerivationKey", str)
type DependencySemantics = Literal["content", "observation"]


@dataclass(frozen=True, slots=True)
class DerivedTaskSpec:
    """Reproducibility contract for a derived task."""

    task_id: str
    task_version: str
    deterministic: bool
    dependency_semantics: DependencySemantics
    parameters: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate stable task identity and dependency semantics."""
        ProducerRef(self.task_id, self.task_version)

    @property
    def producer(self) -> ProducerRef:
        return ProducerRef(self.task_id, self.task_version)

    def to_dict(self) -> JsonObject:
        return {
            "task_id": self.task_id,
            "task_version": self.task_version,
            "deterministic": self.deterministic,
            "dependency_semantics": self.dependency_semantics,
            "parameters": dict(self.parameters),
        }


def _input_identities(
    spec: DerivedTaskSpec,
    inputs: Iterable[ArtifactObservation],
) -> list[str]:
    if spec.dependency_semantics == "content":
        return sorted(str(observation.content_id) for observation in inputs)
    return sorted(str(observation.observation_id) for observation in inputs)


def derivation_key_for(
    spec: DerivedTaskSpec,
    *,
    outputs: Iterable[ArtifactKey | str],
    inputs: Iterable[ArtifactObservation],
) -> DerivationKey:
    """Compute the canonical identity of one declared derivation."""

    return DerivationKey(
        stable_id(
            "derivation",
            {
                "task_id": spec.task_id,
                "task_version": spec.task_version,
                "parameters": dict(spec.parameters),
                "outputs": sorted(str(output) for output in outputs),
                "dependency_semantics": spec.dependency_semantics,
                "inputs": _input_identities(spec, inputs),
            },
        )
    )


__all__ = [
    "DependencySemantics",
    "DerivationKey",
    "DerivedTaskSpec",
    "derivation_key_for",
]
