from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.derivation import DerivedTaskSpec
    from efloud.json_types import JsonObject
    from efloud.models import NormalizedManifest
    from efloud.registry import SourceDefinition


class DerivedTask(Protocol):
    name: str

    async def run(
        self,
        *,
        sync_root: Path,
        manifest: NormalizedManifest,
        sources: tuple[SourceDefinition, ...],
    ) -> dict[str, object]: ...


@runtime_checkable
class RepositoryDerivedTask(Protocol):
    """Optional metadata contract for provenance-complete derived-task recording."""

    repository_version: str
    repository_input_source_ids: tuple[str, ...]

    def repository_parameters(self) -> JsonObject: ...


@runtime_checkable
class SpecifiedDerivedTask(Protocol):
    """Optional deterministic derivation contract for repository-backed reuse."""

    def repository_spec(self) -> DerivedTaskSpec: ...


__all__ = ["DerivedTask", "RepositoryDerivedTask", "SpecifiedDerivedTask"]
