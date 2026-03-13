from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.source_results import local_materialized_path, manifest_entry_for_source

if TYPE_CHECKING:
    from efloud.models import NormalizedManifest, SyncResult
    from efloud.registry import SourceDefinition
    from efloud.source_aliases import AliasMap


def mirror_dir(sync_root: Path, subdir: str) -> Path:
    return sync_root / "mirrors" / subdir


def mirror_root_subdir_for_source(source: SourceDefinition | None) -> str | None:
    if source is None or not source.local_subpath:
        return None
    return source.local_subpath.split("/", 1)[0]


def manifest_http_dest_for_url(sync_res: SyncResult, url: str) -> Path | None:
    http_results = sync_res.manifest.get("results", {}).get("http", {})
    if not isinstance(http_results, dict):
        return None

    for rec in http_results.values():
        if not isinstance(rec, Mapping):
            continue

        rec_url = rec.get("url")
        if not isinstance(rec_url, str):
            req = rec.get("request")
            rec_url = req.get("url") if isinstance(req, Mapping) else None

        if rec_url == url and isinstance(rec.get("dest"), str):
            return Path(rec["dest"])

    return None


def manifest_entry_for_source_aliasable(
    manifest: NormalizedManifest | None,
    source: SourceDefinition | None,
    *,
    aliases: AliasMap | None = None,
) -> Mapping[str, object] | None:
    if source is None:
        return None
    return manifest_entry_for_source(manifest, source, aliases=aliases)


def materialized_path_for_source(
    manifest: NormalizedManifest | None,
    source: SourceDefinition | None,
    *,
    aliases: AliasMap | None = None,
) -> Path | None:
    return local_materialized_path(manifest_entry_for_source_aliasable(manifest, source, aliases=aliases))


# Backward-compatible name retained for existing callers.
def manifest_entry_for_source(
    manifest: Mapping[str, object] | None,
    source: SourceDefinition | None,
) -> Mapping[str, object] | None:
    if source is None:
        return None
    from efloud.source_results import manifest_entry_for_source as _manifest_entry_for_source

    return _manifest_entry_for_source(manifest, source)
