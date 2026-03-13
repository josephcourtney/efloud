from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from efloud.health import build_mirror_health_summary
from efloud.json_types import JsonMapping, JsonObject, JsonValue, json_mapping_or_none
from efloud.manifest import load_latest_manifest
from efloud.models import EngineConfig, NormalizedManifest, SyncResult
from efloud.registry import SourceDefinition, SourceKind
from efloud.source_results import manifest_entry_for_source, source_status_hint


def collect_status_payload(cfg: EngineConfig) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    root = Path(cfg.root)

    manifest, manifest_warnings, manifest_path = load_latest_manifest(
        root / cfg.log_dir,
        cfg.manifest_filename,
        expected_root=root,
    )
    warnings.extend(manifest_warnings)

    sync_res = (
        SyncResult(ok=True, root=root, manifest_path=manifest_path, manifest=manifest)
        if manifest is not None
        else None
    )

    mirror_roots = {
        source.id: (root / cfg.mirrors_dir / source.local_subpath) if source.local_subpath else None
        for source in cfg.sources
        if source.kind is SourceKind.RSYNC
    }

    payload = {
        "mirror_root": str(root),
        "manifest_path": str(sync_res.manifest_path)
        if sync_res is not None and sync_res.manifest_path
        else None,
        "source_count": len(cfg.sources),
        "index_count": len(cfg.index_registry.ids()) if cfg.index_registry is not None else 0,
        "health": build_mirror_health_summary(
            mirror_roots,
            manifest=manifest,
        ).to_dict(),
    }
    return payload, warnings


def describe_source_status(
    source: SourceDefinition,
    entry: JsonMapping | None,
) -> tuple[str, JsonObject]:
    status = source_status_hint(entry)
    details: JsonObject = {"description": source.description}

    if not entry:
        return status, details

    if source.kind in {SourceKind.HTTP, SourceKind.REST}:
        _add_http_source_details(entry, details)
    elif source.kind is SourceKind.RSYNC:
        _add_rsync_source_details(entry, details)
    elif source.kind is SourceKind.REST_BASE:
        _add_rest_base_details(entry, details)

    if isinstance(entry.get("error"), str):
        details["error"] = entry["error"]

    return status, details


def _add_http_source_details(entry: JsonMapping, details: JsonObject) -> None:
    if isinstance(entry.get("status_code"), int):
        details["status_code"] = entry["status_code"]
    if isinstance(entry.get("dest"), str):
        details["dest"] = entry["dest"]
        return
    request = json_mapping_or_none(entry.get("request"))
    request_url = request.get("url") if request is not None else None
    if isinstance(request_url, str):
        details["request_url"] = request_url


def _add_rsync_source_details(entry: JsonMapping, details: JsonObject) -> None:
    if isinstance(entry.get("local"), str):
        details["local"] = entry["local"]
    if isinstance(entry.get("mode"), str):
        details["mode"] = entry["mode"]
    updates = _rsync_updates(entry.get("results"))
    if updates:
        details["updates"] = updates


def _rsync_updates(results: JsonValue | None) -> list[JsonObject]:
    results_mapping = json_mapping_or_none(results)
    if results_mapping is None:
        return []
    updates: list[JsonObject] = []
    for key, value in results_mapping.items():
        value_mapping = json_mapping_or_none(value)
        if value_mapping is None:
            continue
        status_value = value_mapping.get("status")
        if status_value is not None:
            updates.append({"name": key, "status": status_value})
    return updates


def _add_rest_base_details(entry: JsonMapping, details: JsonObject) -> None:
    request = json_mapping_or_none(entry.get("request"))
    if request is None:
        return
    base_url = request.get("base_url")
    if isinstance(base_url, str):
        details["base_url"] = base_url
    fanout_root = request.get("fanout_root")
    if isinstance(fanout_root, str):
        details["fanout_root"] = fanout_root


def derived_summary(manifest: NormalizedManifest | None) -> list[JsonObject]:
    if manifest is None:
        return []

    derived = manifest.get("results", {}).get("derived", {})
    if not isinstance(derived, Mapping):
        return []

    out: list[JsonObject] = []
    for name, payload in derived.items():
        if not isinstance(payload, Mapping):
            continue
        out.append(_derived_summary_entry(name, payload))
    return out


def _derived_summary_entry(name: str, payload: JsonMapping) -> JsonObject:
    entry: JsonObject = {"name": name}
    _copy_str(payload, entry, "dest")
    _copy_int(payload, entry, "count")
    if isinstance(payload.get("ok"), (int, bool)):
        entry["ok"] = payload["ok"]
    _copy_int(payload, entry, "err")
    _copy_str(payload, entry, "manifest")
    request = json_mapping_or_none(payload.get("request"))
    if request is not None:
        _copy_str(request, entry, "base_url")
        _copy_str(request, entry, "fanout_root")
    return entry


def _copy_str(source: JsonMapping, dest: JsonObject, key: str) -> None:
    value = source.get(key)
    if isinstance(value, str):
        dest[key] = value


def _copy_int(source: JsonMapping, dest: JsonObject, key: str) -> None:
    value = source.get(key)
    if isinstance(value, int):
        dest[key] = value


def source_status_rows(
    manifest: NormalizedManifest | None,
    sources: list[SourceDefinition],
    *,
    aliases: Mapping[str, tuple[str, ...] | list[str]] | None = None,
) -> list[OrderedDict[str, Any]]:
    rows: list[OrderedDict[str, Any]] = []
    for source in sources:
        status, details = describe_source_status(
            source,
            manifest_entry_for_source(manifest, source, aliases=aliases),
        )
        row = OrderedDict(
            [
                ("source_id", source.id),
                ("kind", source.kind.value),
                ("status", status),
                ("details", details),
            ],
        )
        rows.append(row)
    return rows
