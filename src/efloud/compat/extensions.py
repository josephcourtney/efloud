"""Explicit adapters for extensions written against the legacy manifest contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import anyio

from efloud.collections import CollectionInventory, CollectionItem
from efloud.derivation import DerivedOutput, DerivedResult, DerivedTaskSpec
from efloud.derived import RepositoryDerivedTask
from efloud.json_types import copy_json_mapping, json_mapping_or_none
from efloud.models import EngineConfig
from efloud.repository_compat import repository_manifest

if TYPE_CHECKING:
    from collections.abc import Sequence

    from efloud.collections import CollectionContext
    from efloud.derivation import DerivedContext
    from efloud.fanout import FanoutEnumeration, FanoutItem
    from efloud.json_types import JsonObject
    from efloud.models import NormalizedManifest
    from efloud.registry import SourceDefinition
    from efloud.repository_capabilities import ExtensionReader


class LegacyTask(Protocol):
    name: str

    async def run(
        self,
        *,
        sync_root: Path,
        manifest: NormalizedManifest,
        sources: tuple[SourceDefinition, ...],
    ) -> dict[str, object]: ...


class LegacyEnumerator(Protocol):
    async def __call__(
        self,
        *,
        sync_root: Path,
        manifest: NormalizedManifest,
        sources: tuple[SourceDefinition, ...],
    ) -> Sequence[FanoutItem] | FanoutEnumeration: ...


def _manifest(
    repository: ExtensionReader,
    workspace: Path,
    sources: tuple[SourceDefinition, ...],
) -> NormalizedManifest:
    return repository_manifest(
        repository,
        cfg=EngineConfig(root=workspace, sources=list(sources)),
    )


def _task_parameters(task: LegacyTask) -> JsonObject:
    if isinstance(task, RepositoryDerivedTask):
        return task.repository_parameters()
    return {}


def _task_version(task: LegacyTask) -> str:
    return task.repository_version if isinstance(task, RepositoryDerivedTask) else "1"


def _task_inputs(task: LegacyTask) -> tuple[str, ...]:
    return task.repository_input_source_ids if isinstance(task, RepositoryDerivedTask) else ()


@dataclass(frozen=True)
class LegacyTaskAdapter:
    """Adapt one manifest-shaped task to the canonical derived-task contract."""

    task: LegacyTask
    sources: tuple[SourceDefinition, ...] = ()

    @property
    def name(self) -> str:
        return self.task.name

    @property
    def spec(self) -> DerivedTaskSpec:
        return DerivedTaskSpec(
            task_id=f"efloud:legacy-derived:{self.name}",
            task_version=_task_version(self.task),
            deterministic=False,
            dependency_semantics="observation",
            parameters={**_task_parameters(self.task), "compatibility_adapter": "legacy-manifest"},
        )

    @property
    def input_source_ids(self) -> tuple[str, ...]:
        return _task_inputs(self.task)

    @property
    def output_names(self) -> tuple[str, ...]:
        return ("output",)

    # Retain these accessors only for compatibility tests while the old extension
    # package remains. Canonical execution consumes ``spec`` and ``input_source_ids``.
    @property
    def repository_version(self) -> str:
        return _task_version(self.task)

    @property
    def repository_input_source_ids(self) -> tuple[str, ...]:
        return self.input_source_ids

    def repository_parameters(self) -> JsonObject:
        return _task_parameters(self.task)

    async def run(self, *, context: DerivedContext) -> DerivedResult:
        raw = await self.task.run(
            sync_root=context.workspace,
            manifest=_manifest(context.repository, context.workspace, self.sources),
            sources=self.sources,
        )
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


def _collection_item(item: FanoutItem) -> CollectionItem:
    metadata = json_mapping_or_none(item.metadata) if item.metadata is not None else None
    return CollectionItem(
        item_id=item.item_id,
        request_path=item.request_path,
        metadata=copy_json_mapping(metadata) if metadata is not None else {},
        change_token=item.change_token,
        expected_integrity=item.expected_integrity,
    )


@dataclass(frozen=True)
class LegacyEnumeratorAdapter:
    """Adapt a manifest-shaped enumerator to canonical collection inventory."""

    enumerator: LegacyEnumerator
    sources: tuple[SourceDefinition, ...] = ()

    async def __call__(self, *, context: CollectionContext) -> CollectionInventory:
        raw = await self.enumerator(
            sync_root=context.workspace,
            manifest=_manifest(context.repository, context.workspace, self.sources),
            sources=self.sources,
        )
        from efloud.fanout import FanoutEnumeration  # ruff: ignore[import-outside-top-level] - compatibility type is intentionally lazy.

        enumeration = raw if isinstance(raw, FanoutEnumeration) else FanoutEnumeration(tuple(raw))
        return CollectionInventory(
            items=tuple(_collection_item(item) for item in enumeration.items),
            complete=enumeration.complete,
            upstream_identity=enumeration.upstream_identity,
        )
