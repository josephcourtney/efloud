from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import anyio

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    RsyncAcquisition,
    SourceAdapter,
)
from efloud.json_types import JsonObject, json_mapping_or_none
from efloud.registry import SourceDefinition, SourceKind
from efloud.transport.rsync import RsyncMirror, RsyncMirrorConfig
from efloud.transport.rsync_inventory import enumerate_rsync
from efloud.transport.rsync_runtime import (
    prepare_rsync_paths,
    rsync_command_for_source,
    rsync_failure_detail,
    rsync_results_ok,
    run_rsync_operation,
)


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _require_supported_source(descriptor: AdapterDescriptor, source: SourceDefinition) -> None:
    if source.kind not in descriptor.source_kinds:
        msg = f"Adapter {descriptor.adapter_id!r} does not support source kind {source.kind.value!r}."
        raise ValueError(msg)


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


def _rsync_mirror(context: AdapterExecutionContext, local_root: Path) -> RsyncMirror:
    source = context.source
    cfg = context.config
    return RsyncMirror(
        RsyncMirrorConfig(
            name=source.description,
            remote=source.url,
            local=local_root,
            meta_path=local_root / ".mirror_meta.json",
            delete=False,
            timeout_seconds=1200.0,
            port=source.port,
            include=source.include or (),
            exclude=source.exclude or ('"**/.DS_Store"',),
            rate_limit_storage=_sqlite_url(Path(cfg.root) / cfg.rate_limits_dir / "mirror_rate_limits.sqlite"),
            rate_limit_scope=None,
            raise_on_rate_limit=False,
            progress=cfg.runtime_progress and source.id != "pdb_mmcif",
            dry_run=False,
            cmd=rsync_command_for_source(source),
        )
    )


@dataclass(frozen=True, slots=True)
class RsyncSourceAdapter:
    descriptor: AdapterDescriptor

    async def acquire(self, context: AdapterExecutionContext) -> RsyncAcquisition:
        source = context.source
        _require_supported_source(self.descriptor, source)
        cfg = context.config
        local_root = Path(cfg.root) / cfg.mirrors_dir / (source.local_subpath or source.id)
        local_root.mkdir(parents=True, exist_ok=True)
        requested_scope = context.operation.scope
        mirror_paths, synthetic = await prepare_rsync_paths(
            source=source,
            mirror_paths=requested_scope or None,
            runtime_progress=cfg.runtime_progress,
        )
        mirror = _rsync_mirror(context, local_root)
        force = context.operation.refresh.refresh if context.operation.refresh is not None else False
        observed_at = time.time()
        try:
            results = await run_rsync_operation(
                source=source,
                mirror=mirror,
                mirror_paths=mirror_paths,
                force=force,
                synthetic_results=synthetic,
                runtime_progress=cfg.runtime_progress,
            )
            if cfg.remove_empty_dirs_after_rsync:
                await mirror.prune_local_empty_dirs()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return RsyncAcquisition(
                source_id=source.id,
                status="failed",
                local_root=local_root,
                scope=tuple(requested_scope),
                observed_at=observed_at,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not rsync_results_ok(results):
            return RsyncAcquisition(
                source_id=source.id,
                status="failed",
                local_root=local_root,
                scope=tuple(requested_scope),
                observed_at=observed_at,
                updated_paths=_updated_paths(results),
                transport_results=results,
                error=rsync_failure_detail(results) or "rsync acquisition failed",
            )

        inventory_cfg = RsyncMirrorConfig(
            name=source.id,
            remote=source.url,
            local=local_root,
            port=source.port,
            include=source.include or (),
            exclude=source.exclude or (),
        )
        inventory = await anyio.to_thread.run_sync(lambda: enumerate_rsync(inventory_cfg, scope=tuple(requested_scope)))
        return RsyncAcquisition(
            source_id=source.id,
            status="succeeded",
            local_root=local_root,
            scope=tuple(requested_scope),
            observed_at=observed_at,
            inventory=inventory,
            updated_paths=_updated_paths(results),
            transport_results=results,
        )


def rsync_source_adapter() -> SourceAdapter:
    """Built-in rsync adapter."""
    return RsyncSourceAdapter(
        AdapterDescriptor(
            adapter_id="efloud:rsync",
            version="1",
            source_kinds=(SourceKind.RSYNC,),
            capabilities=AdapterCapabilities(inventory=True, fetch=True),
        )
    )


__all__ = ["RsyncSourceAdapter", "rsync_source_adapter"]
