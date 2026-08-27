from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import httpx

from efloud.derived import DerivedTask
from efloud.fs import atomic_write_bytes, atomic_write_text, safe_json_dump
from efloud.transport.http import HttpCache, HttpCacheConfig

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

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


class FanoutEnumerator(Protocol):
    async def __call__(
        self,
        *,
        sync_root: Path,
        manifest: NormalizedManifest,
        sources: tuple[SourceDefinition, ...],
    ) -> Sequence[FanoutItem]: ...


class BucketStrategy(Protocol):
    def __call__(self, item_id: str) -> Path: ...


def two_char_bucket(item_id: str, *, suffix: str = ".json") -> Path:
    text = item_id.lower()
    bucket = text[1:3] if len(text) >= MIN_BUCKET_SOURCE_LENGTH else "xx"
    return Path(bucket) / f"{text}{suffix}"


@dataclass(frozen=True)
class RestBaseFanoutTask(DerivedTask):
    """
    Reusable REST_BASE fanout task.

    This closes the biggest gap between `bvp-resources` and `efloud`: a
    first-class, generic materialization pattern for sources whose true output
    is a collection of derived per-item artifacts rather than a single fetched
    file.
    """

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

        items = list(await self.enumerator(sync_root=sync_root, manifest=manifest, sources=sources))
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
            }
    except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "request": request,
            "dest": str(dest),
            "item_id": item.item_id,
            "metadata": dict(item.metadata or {}),
        }

    return {
        "status": "ok",
        "request": request,
        "dest": str(dest),
        "item_id": item.item_id,
        "metadata": dict(item.metadata or {}),
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
    "FanoutEnumerator",
    "FanoutItem",
    "ResponseMode",
    "RestBaseFanoutTask",
    "two_char_bucket",
]
