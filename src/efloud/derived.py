from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from efloud.repository_models import ArtifactObservation

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.json_types import JsonObject
    from efloud.registry import SourceDefinition
    from efloud.repository_view import RepositoryView


@dataclass(frozen=True, slots=True)
class ExtensionContext:
    """Repository reads and exact dependencies supplied to an extension invocation.

    Outputs belong in the supplied workspace. The executor alone records them in
    the repository; extensions receive no acquisition or metadata-write capability.
    """

    repository: RepositoryView
    workspace: Path
    sources: tuple[SourceDefinition, ...]
    inputs: tuple[ArtifactObservation, ...] = ()


def source_inputs(repository: RepositoryView, source_ids: tuple[str, ...]) -> tuple[ArtifactObservation, ...]:
    """Bind current content states, respecting authoritative later absences."""
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


@dataclass(frozen=True, slots=True)
class DerivedOutput:
    """One explicitly named file to ingest after a successful task invocation."""

    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class DerivedResult:
    """Semantic task status, diagnostics, and declared artifact outputs."""

    ok: bool = True
    details: JsonObject = field(default_factory=dict)
    outputs: tuple[DerivedOutput, ...] = ()


class DerivedTask(Protocol):
    name: str

    async def run(self, *, context: ExtensionContext) -> DerivedResult: ...


@runtime_checkable
class RepositoryDerivedTask(Protocol):
    """Optional producer version, parameters, and source dependency declaration."""

    repository_version: str
    repository_input_source_ids: tuple[str, ...]

    def repository_parameters(self) -> JsonObject: ...


__all__ = ["DerivedOutput", "DerivedResult", "DerivedTask", "ExtensionContext", "RepositoryDerivedTask"]
