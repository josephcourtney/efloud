from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    HttpAcquisition,
    SourceAdapter,
)
from efloud.sources import HttpSource, RestSource
from efloud.transport.http import HttpCache, HttpCacheConfig
from efloud.transport.http_utils import (
    HttpFetchResult,
    cache_group_name,
    dest_for_http_source,
    fetch_json_to_file,
    fetch_to_file,
)

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.json_types import JsonObject


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _source(
    context: AdapterExecutionContext,
    descriptor: AdapterDescriptor,
) -> HttpSource | RestSource:
    source = context.source
    if (
        not isinstance(source, HttpSource | RestSource)
        or source.adapter_id != descriptor.adapter_id
        or context.operation.producer != descriptor.producer
    ):
        msg = f"Adapter {descriptor.adapter_id!r} cannot acquire {type(source).__name__}."
        raise TypeError(msg)
    return source


def _http_cache(context: AdapterExecutionContext, source: HttpSource | RestSource) -> HttpCache:
    runtime = context.runtime
    runtime.http_cache_root.mkdir(parents=True, exist_ok=True)
    runtime.rate_limits_root.mkdir(parents=True, exist_ok=True)
    group = cache_group_name(source.url, source.cache_name)
    return HttpCache(
        HttpCacheConfig(
            name=group,
            ttl_seconds=300,
            timeout=60.0,
            cache_db_path=str(runtime.http_cache_root / f"{group}.db"),
            enable_cache=True,
            rate_limit_storage=_sqlite_url(runtime.rate_limits_root / "rate_limits.sqlite"),
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
    source: HttpSource | RestSource,
    destination: Path,
    *,
    refresh: bool,
) -> tuple[HttpFetchResult, str | None]:
    if isinstance(source, RestSource):
        _, result = await fetch_json_to_file(cache, source.url, destination, refresh=refresh)
        return result, "application/json"
    return await fetch_to_file(cache, source.url, destination, refresh=refresh), None


@dataclass(frozen=True, slots=True)
class HttpSourceAdapter:
    descriptor: AdapterDescriptor

    async def acquire(
        self,
        context: AdapterExecutionContext,
    ) -> HttpAcquisition:
        source = _source(context, self.descriptor)
        destination = dest_for_http_source(
            context.runtime.http_root,
            url=source.url,
            description=source.description or source.id,
            kind="REST" if isinstance(source, RestSource) else "HTTP",
            cache_name=source.cache_name,
        )
        cache = _http_cache(context, source)
        refresh = context.operation.refresh.refresh if context.operation.refresh is not None else False
        try:
            result, media_type = await _fetch_http_result(cache, source, destination, refresh=refresh)
        except (OSError, httpx.HTTPError, TypeError, ValueError) as exc:
            return HttpAcquisition(
                source_id=source.id,
                status="failed",
                destination=destination,
                observed_at=time.time(),
                media_type="application/json" if isinstance(source, RestSource) else None,
                expected_integrity=source.expected_integrity,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            with contextlib.suppress(OSError, RuntimeError):
                await cache.aclose()

        request_headers: JsonObject = {str(key): str(value) for key, value in result.request_headers.items()}
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
    return (
        HttpSourceAdapter(AdapterDescriptor("efloud:http", "1", AdapterCapabilities(inventory=False, fetch=True))),
        HttpSourceAdapter(AdapterDescriptor("efloud:rest", "1", AdapterCapabilities(inventory=False, fetch=True))),
    )


__all__ = ["HttpSourceAdapter", "http_source_adapters"]
