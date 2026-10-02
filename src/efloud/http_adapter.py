from __future__ import annotations

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
from efloud.transport.http_utils import dest_for_http_source, fetch_json_to_file

if TYPE_CHECKING:
    from efloud.json_types import JsonObject


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


@dataclass(frozen=True, slots=True)
class HttpSourceAdapter:
    descriptor: AdapterDescriptor

    async def acquire(
        self,
        context: AdapterExecutionContext,
    ) -> HttpAcquisition:
        source = _source(context, self.descriptor)
        if isinstance(source, HttpSource):
            return HttpAcquisition(
                source_id=source.id,
                status="succeeded",
                destination=None,
                observed_at=time.time(),
                expected_integrity=source.expected_integrity,
            )

        destination = dest_for_http_source(
            context.runtime.http_root,
            url=source.url,
            description=source.description or source.id,
            kind="REST",
            cache_name=source.cache_name,
        )
        refresh = context.operation.refresh.refresh if context.operation.refresh is not None else False
        headers = {"Cache-Control": "no-cache"} if refresh else None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                _, result = await fetch_json_to_file(client, source.url, destination, headers=headers)
        except (OSError, httpx.HTTPError, TypeError, ValueError) as exc:
            return HttpAcquisition(
                source_id=source.id,
                status="failed",
                destination=destination,
                observed_at=time.time(),
                media_type="application/json",
                expected_integrity=source.expected_integrity,
                error=f"{type(exc).__name__}: {exc}",
            )

        request_headers: JsonObject = {str(key): str(value) for key, value in result.request_headers.items()}
        response_headers = result.headers or {}
        return HttpAcquisition(
            source_id=source.id,
            status="succeeded",
            destination=destination,
            observed_at=result.fetched_at,
            status_code=result.status_code,
            etag=response_headers.get("etag"),
            last_modified=response_headers.get("last-modified"),
            checksum=result.checksum,
            size_bytes=result.size_bytes,
            request_headers=request_headers,
            media_type="application/json",
            expected_integrity=source.expected_integrity,
        )


def http_source_adapters() -> tuple[SourceAdapter, ...]:
    return (
        HttpSourceAdapter(AdapterDescriptor("efloud:http", "1", AdapterCapabilities(inventory=False, fetch=True))),
        HttpSourceAdapter(AdapterDescriptor("efloud:rest", "1", AdapterCapabilities(inventory=False, fetch=True))),
    )


__all__ = ["HttpSourceAdapter", "http_source_adapters"]
