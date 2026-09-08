from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    HttpAcquisition,
    SourceAdapter,
)
from efloud.registry import SourceDefinition, SourceKind
from efloud.transport.http import HttpCache, HttpCacheConfig
from efloud.transport.http_utils import (
    HttpFetchResult,
    cache_group_name,
    dest_for_http_source,
    fetch_json_to_file,
    fetch_to_file,
)

if TYPE_CHECKING:
    from efloud.json_types import JsonObject


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _require_supported_source(descriptor: AdapterDescriptor, source: SourceDefinition) -> None:
    if source.kind not in descriptor.source_kinds:
        msg = f"Adapter {descriptor.adapter_id!r} does not support source kind {source.kind.value!r}."
        raise ValueError(msg)


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


async def _fetch_http_result(
    cache: HttpCache,
    source: SourceDefinition,
    destination: Path,
    *,
    refresh: bool,
) -> tuple[HttpFetchResult, str | None]:
    if source.kind is SourceKind.REST:
        _, result = await fetch_json_to_file(cache, source.url, destination, refresh=refresh)
        return result, "application/json"
    return await fetch_to_file(cache, source.url, destination, refresh=refresh), None


@dataclass(frozen=True, slots=True)
class HttpSourceAdapter:
    descriptor: AdapterDescriptor

    async def acquire(self, context: AdapterExecutionContext) -> HttpAcquisition:
        source = context.source
        _require_supported_source(self.descriptor, source)
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
            result, media_type = await _fetch_http_result(cache, source, destination, refresh=refresh)
        except (OSError, httpx.HTTPError, TypeError, ValueError) as exc:
            return HttpAcquisition(
                source_id=source.id,
                status="failed",
                destination=destination,
                observed_at=time.time(),
                media_type="application/json" if source.kind is SourceKind.REST else None,
                expected_integrity=source.expected_integrity,
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
            expected_integrity=source.expected_integrity,
        )


def http_source_adapters() -> tuple[SourceAdapter, ...]:
    """Built-in HTTP and REST adapters."""
    return (
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
    )


__all__ = ["HttpSourceAdapter", "http_source_adapters"]
