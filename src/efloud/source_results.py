from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from efloud.json_types import JsonMapping, json_mapping_or_none
from efloud.registry import SourceDefinition, SourceKind
from efloud.source_aliases import AliasMap, SourceAliasResolver

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from efloud.models import NormalizedManifest


def manifest_section_for_kind(kind: SourceKind) -> str:
    kind_value = _kind_name(kind)
    if kind_value in {SourceKind.HTTP.value, SourceKind.REST.value}:
        return "http"
    if kind_value == SourceKind.RSYNC.value:
        return "rsync"
    return "derived"


def _kind_name(kind: object) -> str:
    value = getattr(kind, "value", kind)
    return str(value)


def manifest_entry_for_source_id(
    manifest: Mapping[str, Any] | None,
    source_id: str,
    *,
    kind: SourceKind | None = None,
    aliases: AliasMap | None = None,
) -> JsonMapping | None:
    if manifest is None:
        return None

    results = json_mapping_or_none(manifest.get("results"))
    if results is None:
        return None

    resolver = SourceAliasResolver(aliases)
    candidate_ids = resolver.candidates(source_id)

    for section_name in _candidate_sections(kind):
        section = json_mapping_or_none(results.get(section_name))
        if section is None:
            continue

        entry = _entry_for_candidate_ids(section, candidate_ids)
        if entry is not None:
            return entry

        if section_name == "derived":
            derived_entry = _derived_entry_for_candidate_ids(section, candidate_ids)
            if derived_entry is not None:
                return derived_entry

    return None


def _candidate_sections(kind: SourceKind | None) -> tuple[str, ...]:
    return ("http", "rsync", "derived") if kind is None else (manifest_section_for_kind(kind),)


def _entry_for_candidate_ids(
    section: JsonMapping,
    candidate_ids: tuple[str, ...],
) -> JsonMapping | None:
    for candidate_id in candidate_ids:
        entry_mapping = json_mapping_or_none(section.get(candidate_id))
        if entry_mapping is not None:
            return entry_mapping
    return None


def _derived_entry_for_candidate_ids(section: JsonMapping, candidate_ids: tuple[str, ...]) -> JsonMapping | None:
    for value in section.values():
        value_mapping = json_mapping_or_none(value)
        if value_mapping is None:
            continue
        source_value = value_mapping.get("source_id")
        if isinstance(source_value, str) and source_value in candidate_ids:
            return value_mapping
    return None


def manifest_entry_for_source(
    manifest: NormalizedManifest | None,
    source: SourceDefinition,
    *,
    aliases: AliasMap | None = None,
) -> JsonMapping | None:
    return manifest_entry_for_source_id(
        manifest,
        source.id,
        kind=source.kind,
        aliases=aliases,
    )


def local_materialized_path(entry: JsonMapping | None) -> Path | None:
    if entry is None:
        return None

    for key in ("dest", "local"):
        value = entry.get(key)
        if isinstance(value, str):
            return Path(value)

    request = json_mapping_or_none(entry.get("request"))
    fanout_root = request.get("fanout_root") if request is not None else None
    if isinstance(fanout_root, str):
        return Path(fanout_root)

    return None


def source_status_hint(entry: JsonMapping | None) -> str:
    if entry is None:
        return "missing"
    if entry.get("ok") is True:
        return "ok"
    if entry.get("ok") is False:
        return "error"
    err_value = entry.get("err")
    if isinstance(err_value, int):
        return "error" if err_value > 0 else "ok"
    if entry.get("error"):
        return "error"
    return "present"


def iter_manifest_entries(
    manifest: NormalizedManifest | None,
    sources: Sequence[SourceDefinition],
    *,
    aliases: AliasMap | None = None,
) -> list[tuple[SourceDefinition, JsonMapping | None]]:
    return [(source, manifest_entry_for_source(manifest, source, aliases=aliases)) for source in sources]


__all__ = [
    "iter_manifest_entries",
    "local_materialized_path",
    "manifest_entry_for_source",
    "manifest_entry_for_source_id",
    "manifest_section_for_kind",
    "source_status_hint",
]
