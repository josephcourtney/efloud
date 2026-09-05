from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import httpx

from efloud.derived import DerivedTask
from efloud.fs import atomic_write_bytes, atomic_write_text, safe_json_dump
from efloud.inventory import ChangeToken, IntegrityExpectation, InventoryCoverage, InventoryItem, SourceInventory
from efloud.repository_models import ArtifactKey, SourceId
from efloud.transport.http import HttpCache, HttpCacheConfig

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from efloud.json_types import JsonObject
    from efloud.manifest import NormalizedManifest
    from efloud.registry import SourceDefinition

ResponseMode = Literal["json", "bytes"]
MIN_BUCKET_SOURCE_LENGTH = 3
HTTP_NOT_FOUND = 404


@dataclass(frozen=True)
class FanoutItem:
    item_id: str
    request_path: str | None = None
    metadata: dict[str, object] | None = None
    change_token: ChangeToken | None = None
    expected_integrity: tuple[IntegrityExpectation, ...] = ()


@dataclass(frozen=True)
class FanoutEnumeration:
    """Membership evidence returned by a collection enumerator."""

    items: tuple[FanoutItem, ...]
    complete: bool = True
    upstream_identity: str | None = None

    def __post_init__(self) -> None:
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            msg = "Fanout enumeration contains duplicate item identifiers."
            raise ValueError(msg)


class FanoutEnumerator(Protocol):
    async def __call__(
        self,
        *,
        sync_root: Path,
        manifest: NormalizedManifest,
        sources: tuple[SourceDefinition, ...],
    ) -> Sequence[FanoutItem] | FanoutEnumeration: ...


class BucketStrategy(Protocol):
    def __call__(self, item_id: str) -> Path: ...


def normalize_fanout_enumeration(
    value: Sequence[FanoutItem] | FanoutEnumeration,
) -> FanoutEnumeration:
    if isinstance(value, FanoutEnumeration):
        return value
    return FanoutEnumeration(tuple(value))


def fanout_source_inventory(
    *,
    source_id: SourceId | str,
    base_url: str,
    enumeration: FanoutEnumeration,
    observed_at: float,
) -> SourceInventory:
    """Convert collection membership evidence into the generic source inventory model."""

    normalized_source = SourceId(str(source_id))
    items = tuple(
        InventoryItem(
            item_id=item.item_id,
            artifact_key=ArtifactKey(f"source:{normalized_source}:item:{item.item_id}"),
            locator=f"{base_url.rstrip('/')}/{(item.request_path or item.item_id).lstrip('/')}",
            change_token=item.change_token,
            expected_integrity=item.expected_integrity,
        )
        for item in sorted(enumeration.items, key=lambda candidate: candidate.item_id)
    )
    return SourceInventory(
        source_id=normalized_source,
        observed_at=observed_at,
        coverage=InventoryCoverage(complete=enumeration.complete),
        items=items,
        upstream_identity=enumeration.upstream_identity,
        metadata={"transport": "REST_BASE", "collection": True},
    )


def two_char_bucket(item_id: str, *, suffix: str = ".json") -> Path:
    text = item_id.lower()
    bucket = text[1:3] if len(text) >= MIN_BUCKET_SOURCE_LENGTH else "xx"
    return Path(bucket) / f"{text}{suffix}"


def _inventory_evidence(item: FanoutItem) -> JsonObject:
    payload: JsonObject = {
        "expected_integrity": [expectation.to_dict() for expectation in item.expected_integrity],
    }
    if item.change_token is not None:
        payload["change_token"] = item.change_token.to_dict()
    return payload


@dataclass(frozen=True)
class RestBaseFanoutTask(DerivedTask):
    """Materialize a REST collection as stable per-item artifacts."""

    name: str
    source_id: str
    base_url: str
    enumerator: FanoutEnumerator
    dest_subdir: str
    response_mode: ResponseMode = "json"
    bucket: BucketStrategy = two_char_bucket
    refresh: bool = False
    concurrency: int = 8
    cache_db_filename: str = "fanout_http_cache.sqlite"
    rate_limit_db_filename: str = "fanout_rate_limits.sqlite"
    timeout_seconds: float = 60.0
    retries: int = 5
    request_headers: Mapping[str, str] | None = None
    repository_version: str = "1"
    repository_input_source_ids: tuple[str, ...] = ()

    def repository_parameters(self) -> JsonObject:
        return {
            "source_id": self.source_id,
            "base_url": self.base_url,
            "dest_subdir": self.dest_subdir,
            "response_mode": self.response_mode,
            "refresh": self.refresh,
            "concurrency": self.concurrency,
            "timeout_seconds": self.timeout_seconds,
            "retries": self.retries,
            "request_headers": dict(self.request_headers or {}),
        }

    async def run(
        self,
        *,
        sync_root: Path,
        manifest: NormalizedManifest,
        sources: tuple[SourceDefinition, ...],
    ) -> dict[str, object]:
        source = _source_by_id(self.source_id, sources)
        if source is None:
            msg = f"Unknown source identifier for fanout task: {self.source_id!r}"
            raise ValueError(msg)

        raw_enumeration = await self.enumerator(sync_root=sync_root, manifest=manifest, sources=sources)
        enumeration = normalize_fanout_enumeration(raw_enumeration)
        items = list(enumeration.items)
        dest_root = sync_root / self.dest_subdir
        dest_root.mkdir(parents=True, exist_ok=True)

        cache_root = sync_root / "cache" / "http_cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        rate_root = sync_root / "rate_limits"
        rate_root.mkdir(parents=True, exist_ok=True)

        cache = HttpCache(
            HttpCacheConfig(
                name=self.name,
                headers=dict(self.request_headers or {}),
                timeout=self.timeout_seconds,
                cache_db_path=str(cache_root / self.cache_db_filename),
                rate_limit_storage=f"sqlite:///{
                    (rate_root / self.rate_limit_db_filename).resolve().as_posix()
                }",
                retries=self.retries,
            ),
        )
        try:
            statuses = await _materialize_fanout(
                cache=cache,
                base_url=self.base_url,
                items=items,
                dest_root=dest_root,
                response_mode=self.response_mode,
                bucket=self.bucket,
                refresh=self.refresh,
                concurrency=self.concurrency,
            )
        finally:
            await cache.aclose()

        ok_n = sum(1 for row in statuses.values() if row.get("status") == "ok")
        err_n = len(statuses) - ok_n
        enumeration_payload: dict[str, object] = {
            "complete": enumeration.complete,
            "item_count": len(items),
            "model": "source-inventory-v1",
        }
        if enumeration.upstream_identity is not None:
            enumeration_payload["upstream_identity"] = enumeration.upstream_identity
        return {
            "source_id": source.id,
            "kind": source.kind.value,
            "request": {
                "base_url": self.base_url,
                "fanout_root": str(dest_root),
                "refresh": self.refresh,
                "response_mode": self.response_mode,
                "concurrency": self.concurrency,
            },
            "enumeration": enumeration_payload,
            "entries": statuses,
            "ok": ok_n,
            "err": err_n,
        }


async def _fetch_and_write_fanout_item(
    *,
    cache: HttpCache,
    url: str,
    dest: Path,
    response_mode: ResponseMode,
    refresh: bool,
) -> int:
    resp = await cache.get(url, refresh=refresh)
    if resp.status_code == HTTP_NOT_FOUND:
        return HTTP_NOT_FOUND

    resp.raise_for_status()
    if response_mode == "json":
        atomic_write_text(dest, safe_json_dump(resp.json()))
    else:
        atomic_write_bytes(dest, resp.content)

    return resp.status_code


async def _materialize_fanout_item(
    *,
    cache: HttpCache,
    base_url: str,
    item: FanoutItem,
    dest_root: Path,
    response_mode: ResponseMode,
    bucket: BucketStrategy,
    refresh: bool,
) -> dict[str, object]:
    request_path = item.request_path or item.item_id
    url = f"{base_url.rstrip('/')}/{request_path.lstrip('/')}"
    dest = dest_root / bucket(item.item_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "url": url,
        "base_url": base_url,
        "item_id": item.item_id,
        "request_path": request_path,
        "fanout_path": str(dest.relative_to(dest_root)),
    }
    inventory = _inventory_evidence(item)

    try:
        status_code = await _fetch_and_write_fanout_item(
            cache=cache,
            url=url,
            dest=dest,
            response_mode=response_mode,
            refresh=refresh,
        )
        if status_code == HTTP_NOT_FOUND:
            return {
                "status": "error",
                "error": str(HTTP_NOT_FOUND),
                "request": request,
                "dest": str(dest),
                "item_id": item.item_id,
                "metadata": dict(item.metadata or {}),
                "inventory": inventory,
            }
    except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "request": request,
            "dest": str(dest),
            "item_id": item.item_id,
            "metadata": dict(item.metadata or {}),
            "inventory": inventory,
        }

    return {
        "status": "ok",
        "request": request,
        "dest": str(dest),
        "item_id": item.item_id,
        "metadata": dict(item.metadata or {}),
        "inventory": inventory,
    }


async def _run_fanout_item(
    *,
    cache: HttpCache,
    base_url: str,
    item: FanoutItem,
    dest_root: Path,
    response_mode: ResponseMode,
    bucket: BucketStrategy,
    refresh: bool,
) -> dict[str, object]:
    try:
        return await _materialize_fanout_item(
            cache=cache,
            base_url=base_url,
            item=item,
            dest_root=dest_root,
            response_mode=response_mode,
            bucket=bucket,
            refresh=refresh,
        )
    except Exception as exc:  # ruff: ignore[blind-except] - fanout items are isolated failure domains; one extension/bucket failure must not terminate sibling work.
        return {
            "status": "error",
            "error": f"UNCAUGHT {type(exc).__name__}: {exc}",
            "item_id": item.item_id,
            "metadata": dict(item.metadata or {}),
            "inventory": _inventory_evidence(item),
        }


async def _materialize_fanout(
    *,
    cache: HttpCache,
    base_url: str,
    items: Sequence[FanoutItem],
    dest_root: Path,
    response_mode: ResponseMode,
    bucket: BucketStrategy,
    refresh: bool,
    concurrency: int,
) -> dict[str, dict[str, object]]:
    work_queue: asyncio.Queue[FanoutItem | None] = asyncio.Queue()
    statuses: dict[str, dict[str, object]] = {}

    async def worker() -> None:
        while True:
            item = await work_queue.get()
            try:
                if item is None:
                    return
                statuses[item.item_id] = await _run_fanout_item(
                    cache=cache,
                    base_url=base_url,
                    item=item,
                    dest_root=dest_root,
                    response_mode=response_mode,
                    bucket=bucket,
                    refresh=refresh,
                )
            finally:
                work_queue.task_done()

    n_workers = max(1, int(concurrency))
    workers = [asyncio.create_task(worker()) for _ in range(n_workers)]
    try:
        for item in items:
            await work_queue.put(item)
        for _ in range(n_workers):
            await work_queue.put(None)

        await asyncio.gather(*workers)
    finally:
        for task in workers:
            if not task.done():
                task.cancel()

    return statuses


def _source_by_id(source_id: str, sources: Iterable[SourceDefinition]) -> SourceDefinition | None:
    for source in sources:
        if source.id == source_id:
            return source
    return None


__all__ = [
    "BucketStrategy",
    "FanoutEnumeration",
    "FanoutEnumerator",
    "FanoutItem",
    "ResponseMode",
    "RestBaseFanoutTask",
    "fanout_source_inventory",
    "normalize_fanout_enumeration",
    "two_char_bucket",
]
