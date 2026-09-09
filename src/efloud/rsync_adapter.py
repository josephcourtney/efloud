from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    RsyncAcquisition,
    SourceAdapter,
)
from efloud.json_types import JsonObject, json_mapping_or_none
from efloud.sources import RsyncSource
from efloud.transport.rsync import RsyncMirror, RsyncMirrorConfig
from efloud.transport.rsync_inventory import enumerate_rsync
from efloud.transport.rsync_runtime import (
    prepare_rsync_paths,
    rsync_command_for_source,
    rsync_failure_detail,
    rsync_results_ok,
    run_rsync_operation,
)

if TYPE_CHECKING:
    from pathlib import Path


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _source(
    context: AdapterExecutionContext,
    descriptor: AdapterDescriptor,
) -> RsyncSource:
    source = context.source
    if not isinstance(source, RsyncSource):
        msg = f"Adapter {descriptor.adapter_id!r} cannot acquire {type(source).__name__}."
        raise TypeError(msg)
    return context.source


def _updated_paths(results: JsonObject) -> tuple[str, ...]:
    updated: set[str] = set()
    for raw in results.values():
        mapping = json_mapping_or_none(raw)
        if mapping is None or mapping.get("status") in {"failed", "timed_out"}:
            continue
        raw_paths = mapping.get("updated")
        if not isinstance(raw_paths, list):
            continue
        for value in raw_paths:
            if not isinstance(value, str):
                continue
            normalized = value.strip().replace("\\", "/")
            if normalized.startswith("deleting "):
                continue
            normalized = normalized.strip("/")
            if normalized and normalized != ".mirror_meta.json":
                updated.add(normalized)
    return tuple(sorted(updated))


def _rsync_mirror(context: AdapterExecutionContext, source: RsyncSource, local_root: Path) -> RsyncMirror:
    runtime = context.runtime
    runtime.rate_limits_root.mkdir(parents=True, exist_ok=True)
    return RsyncMirror(
        RsyncMirrorConfig(
            name=source.description or source.id,
            remote=source.url,
            local=local_root,
            meta_path=local_root / ".mirror_meta.json",
            delete=False,
            timeout_seconds=1200.0,
            port=source.port,
            include=source.include,
            exclude=source.exclude or ('"**/.DS_Store"',),
            rate_limit_storage=_sqlite_url(runtime.rate_limits_root / "mirror_rate_limits.sqlite"),
            rate_limit_scope=None,
            raise_on_rate_limit=False,
            progress=runtime.runtime_progress and source.id != "pdb_mmcif",
            dry_run=False,
            cmd=rsync_command_for_source(source),
        )
    )


@dataclass(frozen=True, slots=True)
class RsyncSourceAdapter:
    descriptor: AdapterDescriptor

    async def acquire(self, context: AdapterExecutionContext) -> RsyncAcquisition:
        source = _source(context, self.descriptor)
        runtime = context.runtime
        local_root = runtime.mirrors_root / (source.local_subpath or source.id)
        local_root.mkdir(parents=True, exist_ok=True)
        requested_scope = context.operation.scope
        rsync_paths, synthetic = await prepare_rsync_paths(
            source=source,
            rsync_paths=requested_scope or None,
            runtime_progress=runtime.runtime_progress,
        )
        mirror = _rsync_mirror(context, source, local_root)
        force = context.operation.refresh.refresh if context.operation.refresh is not None else False
        observed_at = time.time()
        try:
            results = await run_rsync_operation(
                source=source,
                mirror=mirror,
                rsync_paths=rsync_paths,
                force=force,
                synthetic_results=synthetic,
                runtime_progress=runtime.runtime_progress,
            )
            if runtime.remove_empty_dirs_after_rsync:
                await mirror.prune_local_empty_dirs()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return RsyncAcquisition(
                source.id,
                "failed",
                local_root,
                tuple(requested_scope),
                observed_at,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not rsync_results_ok(results):
            return RsyncAcquisition(
                source.id,
                "failed",
                local_root,
                tuple(requested_scope),
                observed_at,
                updated_paths=_updated_paths(results),
                transport_results=results,
                error=rsync_failure_detail(results) or "rsync acquisition failed",
            )

        inventory_cfg = RsyncMirrorConfig(
            name=source.id,
            remote=source.url,
            local=local_root,
            port=source.port,
            include=source.include,
            exclude=source.exclude,
        )
        inventory = await anyio.to_thread.run_sync(lambda: enumerate_rsync(inventory_cfg, scope=tuple(requested_scope)))
        return RsyncAcquisition(
            source.id,
            "succeeded",
            local_root,
            tuple(requested_scope),
            observed_at,
            inventory=inventory,
            updated_paths=_updated_paths(results),
            transport_results=results,
        )


def rsync_source_adapter() -> SourceAdapter:
    return RsyncSourceAdapter(AdapterDescriptor("efloud:rsync", "1", AdapterCapabilities(inventory=True, fetch=True)))


__all__ = ["RsyncSourceAdapter", "rsync_source_adapter"]
