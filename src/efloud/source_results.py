from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.registry import SourceDefinition, SourceKind
from efloud.source_aliases import AliasMap, SourceAliasResolver

if TYPE_CHECKING:
    from efloud.models import NormalizedManifest


def manifest_section_for_kind(kind: SourceKind) -> str:
    if kind in {SourceKind.HTTP, SourceKind.REST}:
        return "http"
    if kind is SourceKind.RSYNC:
        return "rsync"
    return "derived"


def manifest_entry_for_source_id(
    manifest: Mapping[str, object] | None,
    source_id: str,
    *,
    kind: SourceKind | None = None,
    aliases: AliasMap | None = None,
) -> Mapping[str, object] | None:
    if manifest is None:
        return None

    results = manifest.get("results", {})
    if not isinstance(results, Mapping):
        return None

    sections: tuple[str, ...]
    sections = ("http", "rsync", "derived") if kind is None else (manifest_section_for_kind(kind),)

    resolver = SourceAliasResolver(aliases)
    candidate_ids = resolver.candidates(source_id)

    for section_name in sections:
        section = results.get(section_name)
        if not isinstance(section, Mapping):
            continue

        for candidate_id in candidate_ids:
            entry = section.get(candidate_id)
            if isinstance(entry, Mapping):
                return entry

        # derived results may carry source_id inside the payload instead of under the key
        if section_name == "derived":
            for value in section.values():
                if isinstance(value, Mapping) and value.get("source_id") in candidate_ids:
                    return value

    return None


def manifest_entry_for_source(
    manifest: NormalizedManifest | None,
    source: SourceDefinition,
    *,
    aliases: AliasMap | None = None,
) -> Mapping[str, object] | None:
    return manifest_entry_for_source_id(
        manifest,
        source.id,
        kind=source.kind,
        aliases=aliases,
    )


def local_materialized_path(entry: Mapping[str, object] | None) -> Path | None:
    if entry is None:
        return None

    for key in ("dest", "local"):
        value = entry.get(key)
        if isinstance(value, str):
            return Path(value)

    request = entry.get("request")
    if isinstance(request, Mapping):
        fanout_root = request.get("fanout_root")
        if isinstance(fanout_root, str):
            return Path(fanout_root)

    return None


def source_status_hint(entry: Mapping[str, object] | None) -> str:
    if entry is None:
        return "missing"
    if entry.get("ok") is True:
        return "ok"
    if entry.get("ok") is False:
        return "error"
    if isinstance(entry.get("err"), int):
        return "error" if int(entry["err"]) > 0 else "ok"
    if entry.get("error"):
        return "error"
    return "present"


def iter_manifest_entries(
    manifest: NormalizedManifest | None,
    sources: Sequence[SourceDefinition],
    *,
    aliases: AliasMap | None = None,
) -> list[tuple[SourceDefinition, Mapping[str, object] | None]]:
    return [(source, manifest_entry_for_source(manifest, source, aliases=aliases)) for source in sources]


__all__ = [
    "iter_manifest_entries",
    "local_materialized_path",
    "manifest_entry_for_source",
    "manifest_entry_for_source_id",
    "manifest_section_for_kind",
    "source_status_hint",
]
