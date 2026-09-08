from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    CollectionAcquisition,
    SourceAdapter,
)
from efloud.fanout import RestBaseFanoutTask
from efloud.json_types import copy_json_mapping, json_mapping_or_none
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository_compat import repository_manifest


def _require_supported_source(descriptor: AdapterDescriptor, source: SourceDefinition) -> None:
    if source.kind not in descriptor.source_kinds:
        msg = f"Adapter {descriptor.adapter_id!r} does not support source kind {source.kind.value!r}."
        raise ValueError(msg)


def _collection_task(context: AdapterExecutionContext) -> RestBaseFanoutTask | None:
    return next(
        (
            task
            for task in context.config.derived_tasks
            if isinstance(task, RestBaseFanoutTask) and task.source_id == context.source.id
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class CollectionSourceAdapter:
    descriptor: AdapterDescriptor

    async def acquire(self, context: AdapterExecutionContext) -> CollectionAcquisition:
        _require_supported_source(self.descriptor, context.source)
        task = _collection_task(context)
        observed_at = time.time()
        if task is None:
            return CollectionAcquisition(
                source_id=context.source.id,
                status="failed",
                task_name=f"collection:{context.source.id}",
                observed_at=observed_at,
                error="No RestBaseFanoutTask is configured for this collection source.",
            )
        refresh = context.operation.refresh.refresh if context.operation.refresh is not None else False
        runtime_task = replace(task, refresh=task.refresh or refresh)
        manifest = repository_manifest(context.repository, cfg=context.config)
        try:
            raw_payload = await runtime_task.run(
                sync_root=Path(context.config.root),
                manifest=manifest,
                sources=tuple(context.config.sources),
            )
        except (OSError, RuntimeError, TypeError, ValueError, httpx.HTTPError) as exc:
            return CollectionAcquisition(
                source_id=context.source.id,
                status="failed",
                task_name=task.name,
                observed_at=observed_at,
                error=f"{type(exc).__name__}: {exc}",
            )
        mapping = json_mapping_or_none(raw_payload)
        if mapping is None:
            return CollectionAcquisition(
                source_id=context.source.id,
                status="failed",
                task_name=task.name,
                observed_at=observed_at,
                error="Collection task returned a non-JSON result.",
            )
        payload = copy_json_mapping(mapping)
        err = payload.get("err")
        failed = isinstance(err, int) and not isinstance(err, bool) and err > 0
        return CollectionAcquisition(
            source_id=context.source.id,
            status="failed" if failed else "succeeded",
            task_name=task.name,
            observed_at=observed_at,
            payload=payload,
            error="One or more collection items failed." if failed else None,
        )


def collection_source_adapter() -> SourceAdapter:
    """Built-in collection/fanout adapter."""
    return CollectionSourceAdapter(
        AdapterDescriptor(
            adapter_id="efloud:collection",
            version="1",
            source_kinds=(SourceKind.REST_BASE,),
            capabilities=AdapterCapabilities(inventory=True, fetch=True),
        )
    )


__all__ = ["CollectionSourceAdapter", "collection_source_adapter"]
