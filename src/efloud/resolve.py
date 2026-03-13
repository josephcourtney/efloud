from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from efloud.json_types import JsonMapping, JsonValue, json_mapping_or_none
from efloud.manifest import normalize_manifest
from efloud.source_results import (
    local_materialized_path,
)
from efloud.source_results import (
    manifest_entry_for_source as _manifest_entry_for_source,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

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
        rec_mapping = json_mapping_or_none(rec)
        if rec_mapping is None:
            continue

        rec_url = rec_mapping.get("url")
        if not isinstance(rec_url, str):
            req = json_mapping_or_none(rec_mapping.get("request"))
            req_url = req.get("url") if req is not None else None
            rec_url = req_url if isinstance(req_url, str) else None

        dest = rec_mapping.get("dest")
        if rec_url == url and isinstance(dest, str):
            return Path(dest)

    return None


def manifest_entry_for_source_aliasable(
    manifest: NormalizedManifest | None,
    source: SourceDefinition | None,
    *,
    aliases: AliasMap | None = None,
) -> JsonMapping | None:
    if source is None:
        return None
    return _manifest_entry_for_source(manifest, source, aliases=aliases)


def materialized_path_for_source(
    manifest: NormalizedManifest | None,
    source: SourceDefinition | None,
    *,
    aliases: AliasMap | None = None,
) -> Path | None:
    return local_materialized_path(manifest_entry_for_source_aliasable(manifest, source, aliases=aliases))


# Backward-compatible name retained for existing callers.
def manifest_entry_for_source(
    manifest: Mapping[str, JsonValue] | None,
    source: SourceDefinition | None,
) -> JsonMapping | None:
    if source is None:
        return None
    normalized_manifest = normalize_manifest(manifest) if manifest is not None else None
    return _manifest_entry_for_source(normalized_manifest, source)
