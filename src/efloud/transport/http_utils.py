from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from efloud.fs import atomic_write_bytes, atomic_write_text, safe_json_dump

if TYPE_CHECKING:
    from efloud.transport.http import HttpCache


@dataclass(frozen=True)
class HttpFetchResult:
    status_code: int
    headers: dict[str, str]
    checksum: str
    size_bytes: int
    fetched_at: float
    request_headers: dict[str, str]


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def human_name_from_url(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"rsync://{url}")
    host = parsed.netloc or parsed.path.split("/")[0] or "unknown"
    path = parsed.path.strip("/") or ""
    tail = path.split("/")[-1] if path else "root"
    return f"{host}:{tail}"


def slugify(value: str) -> str:
    candidate = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return candidate or "x"


def cache_group_name(url: str, cache_name: str | None) -> str:
    if cache_name:
        return cache_name
    parsed = urlparse(url)
    host = parsed.netloc or "http"
    return slugify(host)


def rel_dest_name(description: str, url: str, kind: str) -> str:
    short = sha256_hex(url)[:12]
    parsed = urlparse(url if "://" in url else f"rsync://{url}")
    path = parsed.path.strip("/")
    tail = path.split("/")[-1] if path else "x"
    ext = Path(tail).suffix
    if not ext:
        ext = ".json" if kind == "REST" else ".bin"
    human = slugify(description)[:48] or slugify(human_name_from_url(url))[:48]
    return f"{human}.{short}{ext}"


def dest_for_http_source(
    http_root: Path,
    *,
    url: str,
    description: str,
    kind: str,
    cache_name: str | None = None,
) -> Path:
    group = cache_group_name(url, cache_name)
    name = rel_dest_name(description, url, kind)
    return http_root / group / name


async def fetch_to_file(cache: HttpCache, url: str, dest: Path, *, refresh: bool) -> HttpFetchResult:
    resp = await cache.get(url, refresh=refresh)
    resp.raise_for_status()
    body = resp.content
    atomic_write_bytes(dest, body)
    checksum = hashlib.sha256(body).hexdigest()
    request_headers = dict(resp.request.headers) if resp.request is not None else {}
    return HttpFetchResult(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        checksum=checksum,
        size_bytes=len(body),
        fetched_at=time.time(),
        request_headers=request_headers,
    )


async def fetch_json_to_file(
    cache: HttpCache,
    url: str,
    dest: Path,
    *,
    refresh: bool,
) -> tuple[object, HttpFetchResult]:
    resp = await cache.get(url, refresh=refresh)
    resp.raise_for_status()
    data = resp.json()
    payload = safe_json_dump(data)
    atomic_write_text(dest, payload)
    payload_bytes = payload.encode("utf-8")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    request_headers = dict(resp.request.headers) if resp.request is not None else {}
    return data, HttpFetchResult(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        checksum=checksum,
        size_bytes=len(payload_bytes),
        fetched_at=time.time(),
        request_headers=request_headers,
    )
