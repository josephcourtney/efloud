"""Explicit adapters for extensions written against the legacy manifest contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import anyio

from efloud.derived import DerivedOutput, DerivedResult, RepositoryDerivedTask
from efloud.json_types import copy_json_mapping, json_mapping_or_none
from efloud.models import EngineConfig
from efloud.repository_compat import repository_manifest

if TYPE_CHECKING:
    from collections.abc import Sequence

    from efloud.derived import ExtensionContext
    from efloud.fanout import FanoutEnumeration, FanoutItem
    from efloud.json_types import JsonObject
    from efloud.models import NormalizedManifest
    from efloud.registry import SourceDefinition


class LegacyTask(Protocol):
    name: str

    async def run(
        self, *, sync_root: Path, manifest: NormalizedManifest, sources: tuple[SourceDefinition, ...]
    ) -> dict[str, object]: ...


class LegacyEnumerator(Protocol):
    async def __call__(
        self, *, sync_root: Path, manifest: NormalizedManifest, sources: tuple[SourceDefinition, ...]
    ) -> Sequence[FanoutItem] | FanoutEnumeration: ...


def _manifest(context: ExtensionContext) -> NormalizedManifest:
    return repository_manifest(
        context.repository, cfg=EngineConfig(root=context.workspace, sources=list(context.sources))
    )


@dataclass(frozen=True)
class LegacyTaskAdapter:
    """Opt into legacy manifest construction for one task."""

    task: LegacyTask

    @property
    def name(self) -> str:
        return self.task.name

    @property
    def repository_version(self) -> str:
        return self.task.repository_version if isinstance(self.task, RepositoryDerivedTask) else "1"

    @property
    def repository_input_source_ids(self) -> tuple[str, ...]:
        return self.task.repository_input_source_ids if isinstance(self.task, RepositoryDerivedTask) else ()

    def repository_parameters(self) -> JsonObject:
        return self.task.repository_parameters() if isinstance(self.task, RepositoryDerivedTask) else {}

    async def run(self, *, context: ExtensionContext) -> DerivedResult:
        raw = await self.task.run(sync_root=context.workspace, manifest=_manifest(context), sources=context.sources)
        mapping = json_mapping_or_none(raw)
        if mapping is None:
            msg = "Legacy task returned a non-JSON result."
            raise TypeError(msg)
        details = copy_json_mapping(mapping)
        destination = details.get("dest")
        outputs = (
            (DerivedOutput("output", Path(destination)),)
            if isinstance(destination, str) and await anyio.to_thread.run_sync(Path(destination).is_file)
            else ()
        )
        error_count = details.get("err")
        failed = details.get("ok") is False or (
            isinstance(error_count, int) and not isinstance(error_count, bool) and error_count > 0
        )
        return DerivedResult(ok=not failed, details=details, outputs=outputs)


@dataclass(frozen=True)
class LegacyEnumeratorAdapter:
    """Opt into the manifest signature for an existing collection enumerator."""

    enumerator: LegacyEnumerator

    async def __call__(self, *, context: ExtensionContext) -> Sequence[FanoutItem] | FanoutEnumeration:
        return await self.enumerator(sync_root=context.workspace, manifest=_manifest(context), sources=context.sources)
