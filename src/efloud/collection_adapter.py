from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    CollectionAcquisition,
    CollectionItemAcquisition,
    SourceAdapter,
)
from efloud.collections import (
    CollectionContext,
    CollectionDefinition,
    CollectionInventory,
    CollectionItem,
    ResponseMode,
    collection_source_inventory,
    normalize_collection_inventory,
)
from efloud.fs import atomic_write_bytes, atomic_write_text, safe_json_dump
from efloud.sources import CollectionSource
from efloud.transport.http import HttpCache, HttpCacheConfig

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from efloud.inventory import SourceInventory

_HTTP_NOT_FOUND = 404

_COLLECTION_DESCRIPTOR = AdapterDescriptor(
    adapter_id="efloud:collection",
    version="1",
    capabilities=AdapterCapabilities(
        inventory=True,
        fetch=True,
    ),
)


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _definition(definitions: Sequence[CollectionDefinition], source_id: str) -> CollectionDefinition | None:
    return next((definition for definition in definitions if definition.source_id == source_id), None)


def _cache(context: AdapterExecutionContext, definition: CollectionDefinition) -> HttpCache:
    context.runtime.http_cache_root.mkdir(parents=True, exist_ok=True)
    context.runtime.rate_limits_root.mkdir(parents=True, exist_ok=True)
    return HttpCache(
        HttpCacheConfig(
            name=f"collection:{definition.source_id}",
            headers=dict(definition.request_headers or {}),
            timeout=definition.timeout_seconds,
            cache_db_path=str(context.runtime.http_cache_root / definition.cache_db_filename),
            rate_limit_storage=_sqlite_url(context.runtime.rate_limits_root / definition.rate_limit_db_filename),
            retries=definition.retries,
        )
    )


def _write_response(
    destination: Path,
    response: httpx.Response,
    *,
    response_mode: ResponseMode,
) -> None:
    if response_mode == "json":
        atomic_write_text(destination, safe_json_dump(response.json()))
    else:
        atomic_write_bytes(destination, response.content)


async def _fetch_collection_items(
    context: AdapterExecutionContext,
    source: CollectionSource,
    definition: CollectionDefinition,
    inventory: CollectionInventory,
    destination_root: Path,
) -> tuple[CollectionItemAcquisition, ...]:
    cache = _cache(context, definition)
    try:
        refresh = context.operation.refresh.refresh if context.operation.refresh is not None else False
        return await _fetch_items(
            cache=cache,
            source=source,
            definition=definition,
            items=inventory.items,
            destination_root=destination_root,
            refresh=refresh,
        )
    finally:
        await cache.aclose()


async def _acquire_collection(
    context: AdapterExecutionContext,
    source: CollectionSource,
    definition: CollectionDefinition,
    observed_at: float,
) -> tuple[SourceInventory, tuple[CollectionItemAcquisition, ...]]:
    raw_inventory = await definition.enumerator(
        context=CollectionContext(
            repository=context.repository,
            workspace=context.runtime.root,
            source=source,
            inputs=context.inputs,
        )
    )
    inventory = normalize_collection_inventory(raw_inventory)
    normalized = collection_source_inventory(
        source=source,
        definition=definition,
        inventory=inventory,
        observed_at=observed_at,
    )
    destination_root = context.runtime.root / (definition.dest_subdir or f"collection/{source.id}")
    destination_root.mkdir(parents=True, exist_ok=True)
    items = await _fetch_collection_items(
        context,
        source,
        definition,
        inventory,
        destination_root,
    )
    return normalized, items


async def _fetch_item(
    *,
    cache: HttpCache,
    source: CollectionSource,
    definition: CollectionDefinition,
    item: CollectionItem,
    destination_root: Path,
    refresh: bool,
) -> CollectionItemAcquisition:
    request_path = item.request_path or item.item_id
    url = f"{source.url.rstrip('/')}/{request_path.lstrip('/')}"
    destination = destination_root / definition.bucket(item.item_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = await cache.get(url, refresh=refresh)
        if response.status_code == _HTTP_NOT_FOUND:
            return CollectionItemAcquisition(
                item_id=item.item_id,
                status="error",
                status_code=_HTTP_NOT_FOUND,
                metadata=dict(item.metadata),
                error=str(_HTTP_NOT_FOUND),
            )
        response.raise_for_status()
        _write_response(
            destination,
            response,
            response_mode=definition.response_mode,
        )
    except (OSError, TypeError, ValueError, httpx.HTTPError) as exc:
        return CollectionItemAcquisition(
            item.item_id,
            "error",
            destination=destination,
            metadata=dict(item.metadata),
            error=f"{type(exc).__name__}: {exc}",
        )
    return CollectionItemAcquisition(
        item.item_id,
        "ok",
        destination=destination,
        status_code=response.status_code,
        metadata=dict(item.metadata),
    )


async def _fetch_items(
    *,
    cache: HttpCache,
    source: CollectionSource,
    definition: CollectionDefinition,
    items: tuple[CollectionItem, ...],
    destination_root: Path,
    refresh: bool,
) -> tuple[CollectionItemAcquisition, ...]:
    semaphore = asyncio.Semaphore(definition.concurrency)

    async def run(item: CollectionItem) -> CollectionItemAcquisition:
        async with semaphore:
            return await _fetch_item(
                cache=cache,
                source=source,
                definition=definition,
                item=item,
                destination_root=destination_root,
                refresh=refresh,
            )

    return tuple(await asyncio.gather(*(run(item) for item in items)))


@dataclass(frozen=True, slots=True)
class CollectionSourceAdapter:
    definitions: tuple[CollectionDefinition, ...] = ()
    descriptor: AdapterDescriptor = _COLLECTION_DESCRIPTOR

    async def acquire(
        self,
        context: AdapterExecutionContext,
    ) -> CollectionAcquisition:
        if not isinstance(context.source, CollectionSource):
            msg = f"Collection adapter cannot acquire {type(context.source).__name__}."
            raise TypeError(msg)

        source = context.source
        definition = _definition(self.definitions, source.id)
        observed_at = time.time()

        if definition is None:
            return CollectionAcquisition(
                source_id=source.id,
                status="failed",
                observed_at=observed_at,
                inventory=None,
                error="No CollectionDefinition is configured.",
            )

        try:
            inventory, items = await _acquire_collection(
                context,
                source,
                definition,
                observed_at,
            )
        except (OSError, RuntimeError, TypeError, ValueError, httpx.HTTPError) as exc:
            return CollectionAcquisition(
                source_id=source.id,
                status="failed",
                observed_at=observed_at,
                inventory=None,
                error=f"{type(exc).__name__}: {exc}",
            )

        failed = any(item.status == "error" and item.status_code != _HTTP_NOT_FOUND for item in items)

        return CollectionAcquisition(
            source_id=source.id,
            status="failed" if failed else "succeeded",
            observed_at=observed_at,
            inventory=inventory,
            items=items,
            media_type=("application/json" if definition.response_mode == "json" else None),
            input_observation_ids=tuple(item.observation_id for item in context.inputs),
            error="One or more collection items failed." if failed else None,
        )


def collection_source_adapter(definitions: Sequence[CollectionDefinition] = ()) -> SourceAdapter:
    return CollectionSourceAdapter(tuple(definitions))


__all__ = ["CollectionSourceAdapter", "collection_source_adapter"]
