from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from efloud.locator import resolve_locator_from_file
from efloud.manifest import load_latest_manifest
from efloud.query_targets import parse_query_target
from efloud.source_aliases import source_by_id_or_alias
from efloud.source_results import local_materialized_path, manifest_entry_for_source
from efloud.state import load_mirror_state

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.models import EngineConfig
    from efloud.registry import SourceDefinition


@dataclass(frozen=True)
class StoreSpec:
    store_id: str
    label: str
    path: Path
    category: str
    path_kind: str  # "file" | "dir"
    description: str


def _rel_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _json_shape(path: Path) -> str | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(raw, dict):
        return "object"
    if isinstance(raw, list):
        return "array"
    return type(raw).__name__


def _sqlite_meta(path: Path) -> tuple[dict[str, str] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        con = sqlite3.connect(path)
    except sqlite3.Error as exc:
        return None, str(exc)
    try:
        rows = con.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.Error as exc:
        return None, str(exc)
    finally:
        con.close()
    return {str(k): str(v) for (k, v) in rows}, None


def store_specs(cfg: EngineConfig) -> tuple[StoreSpec, ...]:
    root = Path(cfg.root)
    return (
        StoreSpec(
            store_id="sync_manifest",
            label="sync manifest",
            path=root / cfg.log_dir / cfg.manifest_filename,
            category="derived",
            path_kind="file",
            description="Canonical merged sync manifest.",
        ),
        StoreSpec(
            store_id="mirror_state",
            label="mirror state",
            path=root / cfg.state_filename,
            category="derived",
            path_kind="file",
            description="Hash-tree snapshot of mirrored filesystem state.",
        ),
        StoreSpec(
            store_id="http_cache_dir",
            label="HTTP cache directory",
            path=root / cfg.cache_dir / cfg.http_cache_dir,
            category="cached",
            path_kind="dir",
            description="Persistent HTTP response cache storage.",
        ),
        StoreSpec(
            store_id="rate_limits_dir",
            label="rate limit state directory",
            path=root / cfg.rate_limits_dir,
            category="cached",
            path_kind="dir",
            description="Rate-limit and backoff state persisted across sync runs.",
        ),
        StoreSpec(
            store_id="sync_log_dir",
            label="sync log directory",
            path=root / cfg.log_dir,
            category="derived",
            path_kind="dir",
            description="Directory containing sync manifests and related run artifacts.",
        ),
    )


def _store_summary_entries(cfg: EngineConfig) -> list[dict[str, str]]:
    return [
        {
            "store_id": spec.store_id,
            "category": spec.category,
            "label": spec.label,
            "path": str(spec.path),
        }
        for spec in store_specs(cfg)
    ]


def _base_store_payload(
    spec: StoreSpec,
    *,
    root: Path,
    exists: bool,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "target_kind": "store",
        "store_id": spec.store_id,
        "category": spec.category,
        "label": spec.label,
        "description": spec.description,
        "path_kind": spec.path_kind,
        "path": str(spec.path),
        "root_relative_path": _rel_to_root(spec.path, root),
        "present": exists,
        "store_status": "present" if exists else "missing",
        "warnings": warnings,
    }


def _populate_store_stat_payload(path: Path, payload: dict[str, Any], warnings: list[str]) -> bool:
    try:
        stat = path.stat()
    except OSError as exc:
        payload["store_status"] = "unreadable"
        warnings.append(f"Unreadable path: {exc}")
        return False
    payload["size_bytes"] = int(stat.st_size)
    payload["modified_at_unix"] = float(stat.st_mtime)
    return True


def _populate_directory_payload(path: Path, payload: dict[str, Any], warnings: list[str]) -> None:
    try:
        payload["entry_count"] = sum(1 for _ in path.iterdir())
    except OSError as exc:
        payload["store_status"] = "unreadable"
        warnings.append(f"Unreadable directory: {exc}")


def _store_metadata(spec: StoreSpec, path: Path, warnings: list[str]) -> dict[str, Any]:
    if spec.store_id == "mirror_state":
        return _mirror_state_metadata(path, warnings)
    if spec.store_id == "sync_manifest":
        return _sync_manifest_metadata(path, warnings)
    if path.suffix == ".sqlite":
        return _sqlite_store_metadata(path, warnings)
    return _generic_store_metadata(path)


def _mirror_state_metadata(path: Path, warnings: list[str]) -> dict[str, Any]:
    state = load_mirror_state(path)
    if state is None:
        warnings.append("Mirror state exists but could not be parsed.")
        return {}
    return {
        "generated_at_unix": state.generated_at_unix,
        "hash_algo": state.hash_algo,
        "sources_count": len(state.sources),
        "manifest_path": state.manifest_path,
    }


def _sync_manifest_metadata(path: Path, warnings: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"Sync manifest unreadable: {exc}")
        return metadata
    if not isinstance(raw, Mapping):
        warnings.append("Sync manifest is not a JSON object.")
        return metadata
    results = raw.get("results")
    metadata["results_sections"] = sorted(str(key) for key in results) if isinstance(results, Mapping) else []
    metadata["errors_count"] = len(raw.get("errors", [])) if isinstance(raw.get("errors"), list) else 0
    return metadata


def _sqlite_store_metadata(path: Path, warnings: list[str]) -> JsonObject:
    meta, err = _sqlite_meta(path)
    if err is not None:
        warnings.append(f"SQLite metadata unreadable: {err}")
        return {}
    return dict((meta or {}).items())


def _generic_store_metadata(path: Path) -> dict[str, Any]:
    shape = _json_shape(path)
    return {"json_shape": shape} if shape is not None else {}


def store_payload(store_id: str, *, cfg: EngineConfig) -> dict[str, Any]:
    specs = {spec.store_id: spec for spec in store_specs(cfg)}
    spec = specs.get(store_id)
    if spec is None:
        msg = f"Unknown store identifier: {store_id!r}"
        raise ValueError(msg)

    root = Path(cfg.root)
    path = spec.path
    exists = path.exists()
    warnings: list[str] = []
    payload = _base_store_payload(spec, root=root, exists=exists, warnings=warnings)
    if not exists:
        return payload

    if not _populate_store_stat_payload(path, payload, warnings):
        return payload

    if spec.path_kind == "dir":
        _populate_directory_payload(path, payload, warnings)
        return payload

    metadata = _store_metadata(spec, path, warnings)
    if metadata:
        payload["metadata"] = metadata
    if warnings and payload["store_status"] == "present":
        payload["store_status"] = "degraded"
    return payload


def index_payload(index_id: str, *, cfg: EngineConfig) -> dict[str, Any]:
    if cfg.index_registry is None:
        msg = "No index registry configured for this engine instance."
        raise ValueError(msg)
    root = Path(cfg.root)
    status = cfg.index_registry.status(index_id, root=root)
    definition = cfg.index_registry.definition(index_id)
    payload: dict[str, Any] = {
        "target_kind": "index",
        "index_id": index_id,
        "description": definition.description if definition is not None else "",
        "status": status.to_dict(),
    }
    loaded = cfg.index_registry.load(index_id, root=root)
    if loaded is not None:
        payload["payload"] = loaded.to_dict()
    return payload


def root_payload(cfg: EngineConfig) -> dict[str, Any]:
    return {
        "target_kind": "root",
        "stores": _store_summary_entries(cfg),
        "indexes": list(cfg.index_registry.ids()) if cfg.index_registry is not None else [],
        "sources": [
            {
                "source_id": source.id,
                "kind": source.kind.value,
                "description": source.description,
                "url": source.url,
            }
            for source in cfg.sources
        ],
        "usage": [
            "query root",
            "query source:<source-id>",
            "query store:sync_manifest",
            "query index:<index-id>",
            "query source:<source-id>#/some/json/pointer",
        ],
    }


def query_target(raw: str, *, cfg: EngineConfig, fetch_requested: bool = False) -> dict[str, Any]:
    target = parse_query_target(raw)

    if target.kind == "root":
        if target.locator is not None:
            msg = "Locators are not supported for the root target."
            raise ValueError(msg)
        return root_payload(cfg)

    if target.kind == "store":
        if target.identifier is None:
            msg = "Store target missing identifier."
            raise ValueError(msg)
        if target.locator is not None:
            msg = "Locators are not supported for store targets."
            raise ValueError(msg)
        return store_payload(target.identifier, cfg=cfg)

    if target.kind == "index":
        if target.identifier is None:
            msg = "Index target missing identifier."
            raise ValueError(msg)
        if target.locator is not None:
            msg = "Locators are not supported for index targets."
            raise ValueError(msg)
        return index_payload(target.identifier, cfg=cfg)

    source = source_by_id_or_alias(target.identifier or "", cfg.sources, cfg.source_aliases)
    if source is None:
        msg = f"Unknown source identifier: {target.identifier!r}"
        raise ValueError(msg)
    return source_payload(
        source, source_query=None, locator=target.locator, fetch_requested=fetch_requested, cfg=cfg
    )


def source_payload(
    source: SourceDefinition,
    *,
    source_query: str | None,
    locator: str | None,
    fetch_requested: bool,
    cfg: EngineConfig,
) -> dict[str, Any]:
    root = Path(cfg.root)
    manifest, manifest_warnings, _ = load_latest_manifest(
        root / cfg.log_dir,
        cfg.manifest_filename,
        expected_root=root,
    )
    warnings = list(manifest_warnings)
    manifest_entry = manifest_entry_for_source(
        manifest if isinstance(manifest, Mapping) else None,
        source,
        aliases=cfg.source_aliases,
    )

    local_path = local_materialized_path(manifest_entry)

    payload: dict[str, Any] = {
        "target_kind": "source",
        "source_id": source.id,
        "kind": source.kind.value,
        "description": source.description,
        "url": source.url,
        "query": source_query,
        "local_path": str(local_path) if local_path is not None else None,
        "manifest_entry": dict(manifest_entry) if isinstance(manifest_entry, Mapping) else None,
        "warnings": warnings,
    }

    if source_query is not None and not fetch_requested:
        warnings.append("--fetch was not requested; query overrides are informational only.")

    if locator is None:
        return payload

    result: dict[str, Any] = {
        "path": locator,
        "resolved_locator": None,
        "value": None,
        "error": None,
    }

    if local_path is None:
        result["error"] = "No cached source artifact is available for locator evaluation."
    else:
        absolute = local_path
        if not absolute.is_absolute():
            absolute = root / absolute
        value, err, resolved_locator = resolve_locator_from_file(absolute, locator)
        result["value"] = value
        result["error"] = err
        result["resolved_locator"] = resolved_locator
        if err:
            warnings.append(err)

    payload["locator"] = result
    return payload
