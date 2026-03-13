from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path

from efloud.health import build_mirror_health_summary
from efloud.manifest import load_latest_manifest
from efloud.models import EngineConfig, NormalizedManifest, SyncResult
from efloud.registry import SourceDefinition, SourceKind
from efloud.source_results import manifest_entry_for_source, source_status_hint


def collect_status_payload(cfg: EngineConfig) -> tuple[dict[str, object], list[str]]:
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
    entry: Mapping[str, object] | None,
) -> tuple[str, dict[str, object]]:
    status = source_status_hint(entry)
    details: dict[str, object] = {
        "description": source.description,
    }

    if not entry:
        return status, details

    if source.kind in {SourceKind.HTTP, SourceKind.REST}:
        if isinstance(entry.get("status_code"), int):
            details["status_code"] = entry["status_code"]
        if isinstance(entry.get("dest"), str):
            details["dest"] = entry["dest"]
        else:
            request = entry.get("request")
            if isinstance(request, Mapping) and isinstance(request.get("url"), str):
                details["request_url"] = request["url"]

    elif source.kind is SourceKind.RSYNC:
        if isinstance(entry.get("local"), str):
            details["local"] = entry["local"]
        if isinstance(entry.get("mode"), str):
            details["mode"] = entry["mode"]
        results = entry.get("results")
        if isinstance(results, Mapping):
            updates = [
                {
                    "name": key,
                    "status": value.get("status"),
                }
                for key, value in results.items()
                if isinstance(value, Mapping) and value.get("status")
            ]
            if updates:
                details["updates"] = updates

    elif source.kind is SourceKind.REST_BASE:
        request = entry.get("request")
        if isinstance(request, Mapping):
            if isinstance(request.get("base_url"), str):
                details["base_url"] = request["base_url"]
            if isinstance(request.get("fanout_root"), str):
                details["fanout_root"] = request["fanout_root"]

    if isinstance(entry.get("error"), str):
        details["error"] = entry["error"]

    return status, details


def derived_summary(manifest: NormalizedManifest | None) -> list[dict[str, object]]:
    if manifest is None:
        return []

    derived = manifest.get("results", {}).get("derived", {})
    if not isinstance(derived, Mapping):
        return []

    out: list[dict[str, object]] = []
    for name, payload in derived.items():
        if not isinstance(payload, Mapping):
            continue
        entry: dict[str, object] = {"name": name}
        if isinstance(payload.get("dest"), str):
            entry["dest"] = payload["dest"]
        if isinstance(payload.get("count"), int):
            entry["count"] = payload["count"]
        if isinstance(payload.get("ok"), (int, bool)):
            entry["ok"] = payload["ok"]
        if isinstance(payload.get("err"), int):
            entry["err"] = payload["err"]
        if isinstance(payload.get("manifest"), str):
            entry["manifest"] = payload["manifest"]
        request = payload.get("request")
        if isinstance(request, Mapping):
            if isinstance(request.get("base_url"), str):
                entry["base_url"] = request["base_url"]
            if isinstance(request.get("fanout_root"), str):
                entry["fanout_root"] = request["fanout_root"]
        out.append(entry)
    return out


def source_status_rows(
    manifest: NormalizedManifest | None,
    sources: list[SourceDefinition],
    *,
    aliases: Mapping[str, tuple[str, ...] | list[str]] | None = None,
) -> list[OrderedDict[str, object]]:
    rows: list[OrderedDict[str, object]] = []
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
