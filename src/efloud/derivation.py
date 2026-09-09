from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NewType, Protocol

from efloud.repository_models import ArtifactObservation, ProducerRef, stable_id

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from efloud.json_types import JsonObject
    from efloud.repository_capabilities import ArtifactReader, ExtensionReader
    from efloud.repository_models import ArtifactKey

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


@dataclass(frozen=True, slots=True)
class DerivedContext:
    """Exact inputs and narrow read capability supplied to one derived invocation."""

    repository: ExtensionReader
    workspace: Path
    inputs: tuple[ArtifactObservation, ...]


@dataclass(frozen=True, slots=True)
class DerivedOutput:
    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class DerivedResult:
    ok: bool = True
    details: JsonObject = field(default_factory=dict)
    outputs: tuple[DerivedOutput, ...] = ()


class DerivedTask(Protocol):
    """Canonical exact-input, declared-output derived task contract."""

    @property
    def name(self) -> str: ...

    @property
    def spec(self) -> DerivedTaskSpec: ...

    @property
    def input_source_ids(self) -> tuple[str, ...]: ...

    @property
    def output_names(self) -> tuple[str, ...]: ...

    async def run(self, *, context: DerivedContext) -> DerivedResult: ...


def source_inputs(repository: ArtifactReader, source_ids: tuple[str, ...]) -> tuple[ArtifactObservation, ...]:
    """Bind exact current content states while respecting authoritative absences."""
    wanted = set(source_ids)
    return tuple(
        sorted(
            (
                state
                for key in repository.artifact_keys()
                if isinstance(state := repository.latest_state(key), ArtifactObservation) and state.source_id in wanted
            ),
            key=lambda state: str(state.observation_id),
        )
    )


def _input_identities(spec: DerivedTaskSpec, inputs: Iterable[ArtifactObservation]) -> list[str]:
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
    "DerivedContext",
    "DerivedOutput",
    "DerivedResult",
    "DerivedTask",
    "DerivedTaskSpec",
    "derivation_key_for",
    "source_inputs",
]
