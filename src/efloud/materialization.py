from __future__ import annotations

from typing import TYPE_CHECKING

from efloud.resolve import SupportsManifestLookup, manifest_http_dest_for_url

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def http_dest_for_source_url(sync_res: SupportsManifestLookup, url: str) -> Path | None:
    """Return the local materialized HTTP artifact path for an exact source URL."""
    return manifest_http_dest_for_url(sync_res, url)


def http_dests_for_source_urls(
    sync_res: SupportsManifestLookup,
    urls: Iterable[str],
) -> tuple[Path | None, ...]:
    """Return local materialized HTTP artifact paths for exact source URLs."""
    return tuple(http_dest_for_source_url(sync_res, url) for url in urls)


__all__ = [
    "SupportsManifestLookup",
    "http_dest_for_source_url",
    "http_dests_for_source_urls",
]
