from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import anyio
import httpx

from efloud.fanout import RestBaseFanoutTask
from efloud.json_types import JsonObject, copy_json_mapping, json_mapping_or_none
from efloud.planning import PlannedOperation
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository_compat import repository_manifest
from efloud.repository_models import ProducerRef
from efloud.transport.http import HttpCache, HttpCacheConfig
from efloud.transport.http_utils import cache_group_name, dest_for_http_source, fetch_json_to_file, fetch_to_file
from efloud.transport.rsync import RsyncMirror, RsyncMirrorConfig
from efloud.transport.rsync_inventory import RsyncInventory, enumerate_rsync
from efloud.transport.rsync_runtime import (
    prepare_rsync_paths,
    rsync_command_for_source,
    rsync_failure_detail,
    rsync_results_ok,
    run_rsync_operation,
)

if TYPE_CHECKING:
    from efloud.models import EngineConfig
    from efloud.repository import Repository


type AcquisitionStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Protocol capabilities exposed to deterministic planning."""

    inventory: bool
    fetch: bool

    def to_dict(self) -> JsonObject:
        return {"inventory": self.inventory, "fetch": self.fetch}


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    """Stable adapter identity, version, supported source kinds, and capabilities."""

    adapter_id: str
    version: str
    source_kinds: tuple[SourceKind, ...]
    capabilities: AdapterCapabilities

    def __post_init__(self) -> None:
        """Validate producer identity and reject empty source-kind declarations."""
        ProducerRef(self.adapter_id, self.version)
        if not self.source_kinds:
            msg = "AdapterDescriptor.source_kinds must not be empty."
            raise ValueError(msg)

    @property
    def producer(self) -> ProducerRef:
        """Producer identity persisted for operations executed by this adapter."""
        return ProducerRef(self.adapter_id, self.version)

    def to_dict(self) -> JsonObject:
        return {
            "adapter_id": self.adapter_id,
            "version": self.version,
            "source_kinds": [kind.value for kind in self.source_kinds],
            "capabilities": self.capabilities.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AdapterExecutionContext:
    """Read/configuration context supplied to one source-adapter operation."""

    config: EngineConfig
    repository: Repository
    source: SourceDefinition
    operation: PlannedOperation


@dataclass(frozen=True, slots=True)
class HttpAcquisition:
    source_id: str
    status: AcquisitionStatus
    destination: Path | None
    observed_at: float
    status_code: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    request_headers: JsonObject | None = None
    media_type: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RsyncAcquisition:
    source_id: str
    status: AcquisitionStatus
    local_root: Path
    scope: tuple[str, ...]
    observed_at: float
    inventory: RsyncInventory | None = None
    updated_paths: tuple[str, ...] = ()
    transport_results: JsonObject | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionAcquisition:
    source_id: str
    status: AcquisitionStatus
    task_name: str
    observed_at: float
    payload: JsonObject | None = None
    error: str | None = None


type SourceAcquisition = HttpAcquisition | RsyncAcquisition | CollectionAcquisition


class SourceAdapter(Protocol):
    descriptor: AdapterDescriptor

    async def acquire(self, context: AdapterExecutionContext) -> SourceAcquisition: ...


class AdapterRegistry:
    """Direct registry of runtime adapters keyed by declarative source kind."""

    def __init__(self, adapters: tuple[SourceAdapter, ...] = ()) -> None:
        self._adapters: dict[SourceKind, SourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: SourceAdapter) -> None:
        for source_kind in adapter.descriptor.source_kinds:
            if source_kind in self._adapters:
                existing = self._adapters[source_kind]
                msg = (
                    f"Source kind {source_kind.value!r} already has adapter "
                    f"{existing.descriptor.adapter_id!r}."
                )
                raise ValueError(msg)
            self._adapters[source_kind] = adapter

    def adapter_for(self, source: SourceDefinition) -> SourceAdapter | None:
        return self._adapters.get(source.kind)

    def descriptors(self) -> tuple[AdapterDescriptor, ...]:
        unique = {adapter.descriptor.adapter_id: adapter.descriptor for adapter in self._adapters.values()}
        return tuple(sorted(unique.values(), key=lambda descriptor: descriptor.adapter_id))


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _http_cache(context: AdapterExecutionContext) -> HttpCache:
    cfg = context.config
    source = context.source
    cache_root = Path(cfg.root) / cfg.cache_dir / cfg.http_cache_dir
    rate_root = Path(cfg.root) / cfg.rate_limits_dir
    cache_root.mkdir(parents=True, exist_ok=True)
    rate_root.mkdir(parents=True, exist_ok=True)
    group = cache_group_name(source.url, source.cache_name)
    return HttpCache(
        HttpCacheConfig(
            name=group,
            ttl_seconds=300,
            timeout=60.0,
            cache_db_path=str(cache_root / f"{group}.db"),
            enable_cache=True,
            rate_limit_storage=_sqlite_url(rate_root / "rate_limits.sqlite"),
            rate_limit_scope=None,
            raise_on_rate_limit=False,
            retries=5,
            retry_wait_multiplier=1.0,
            retry_wait_min=1.0,
            retry_wait_max=30.0,
        )
    )


@dataclass(frozen=True, slots=True)
class HttpSourceAdapter:
    descriptor: AdapterDescriptor

    async def acquire(self, context: AdapterExecutionContext) -> HttpAcquisition:
        source = context.source
        cfg = context.config
        destination = dest_for_http_source(
            Path(cfg.root) / cfg.http_dir,
            url=source.url,
            description=source.description,
            kind=source.kind.value,
            cache_name=source.cache_name,
        )
        cache = _http_cache(context)
        refresh = context.operation.refresh.refresh if context.operation.refresh is not None else False
        try:
            if source.kind is SourceKind.REST:
                _, result = await fetch_json_to_file(cache, source.url, destination, refresh=refresh)
                media_type = "application/json"
            else:
                result = await fetch_to_file(cache, source.url, destination, refresh=refresh)
                media_type = None
        except (OSError, httpx.HTTPError, TypeError, ValueError) as exc:
            return HttpAcquisition(
                source_id=source.id,
                status="failed",
                destination=destination,
                observed_at=time.time(),
                media_type="application/json" if source.kind is SourceKind.REST else None,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            with contextlib.suppress(OSError, RuntimeError):
                await cache.aclose()

        request_headers: JsonObject = {}
        for key, value in result.request_headers.items():
            request_headers[str(key)] = str(value)
        headers = result.headers or {}
        return HttpAcquisition(
            source_id=source.id,
            status="succeeded",
            destination=destination,
            observed_at=result.fetched_at,
            status_code=result.status_code,
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
            checksum=result.checksum,
            size_bytes=result.size_bytes,
            request_headers=request_headers,
            media_type=media_type,
        )


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


def builtin_adapter_registry() -> AdapterRegistry:
    """Directly register the built-in adapters; external discovery is intentionally deferred."""
    return AdapterRegistry(
        (
            HttpSourceAdapter(
                AdapterDescriptor(
                    adapter_id="efloud:http",
                    version="1",
                    source_kinds=(SourceKind.HTTP,),
                    capabilities=AdapterCapabilities(inventory=False, fetch=True),
                )
            ),
            HttpSourceAdapter(
                AdapterDescriptor(
                    adapter_id="efloud:rest",
                    version="1",
                    source_kinds=(SourceKind.REST,),
                    capabilities=AdapterCapabilities(inventory=False, fetch=True),
                )
            ),
            RsyncSourceAdapter(
                AdapterDescriptor(
                    adapter_id="efloud:rsync",
                    version="1",
                    source_kinds=(SourceKind.RSYNC,),
                    capabilities=AdapterCapabilities(inventory=True, fetch=True),
                )
            ),
            CollectionSourceAdapter(
                AdapterDescriptor(
                    adapter_id="efloud:collection",
                    version="1",
                    source_kinds=(SourceKind.REST_BASE,),
                    capabilities=AdapterCapabilities(inventory=True, fetch=True),
                )
            ),
        )
    )


__all__ = [
    "AcquisitionStatus",
    "AdapterCapabilities",
    "AdapterDescriptor",
    "AdapterExecutionContext",
    "AdapterRegistry",
    "CollectionAcquisition",
    "CollectionSourceAdapter",
    "HttpAcquisition",
    "HttpSourceAdapter",
    "RsyncAcquisition",
    "RsyncSourceAdapter",
    "SourceAcquisition",
    "SourceAdapter",
    "builtin_adapter_registry",
]
