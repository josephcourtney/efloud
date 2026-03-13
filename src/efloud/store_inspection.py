from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from efloud.state import load_mirror_state

if TYPE_CHECKING:
    from efloud.json_types import JsonObject

StorePathKind = Literal["file", "dir"]
StoreMetadataProvider = Callable[[Path, list[str]], dict[str, Any]]


@dataclass(frozen=True)
class StoreSpec:
    store_id: str
    label: str
    path: Path
    category: str
    path_kind: StorePathKind
    description: str
    metadata_provider: StoreMetadataProvider | None = None


def store_summary_entries(specs: Sequence[StoreSpec]) -> list[dict[str, str]]:
    return [
        {
            "store_id": spec.store_id,
            "category": spec.category,
            "label": spec.label,
            "path": str(spec.path),
        }
        for spec in specs
    ]


def store_payload_for_specs(
    store_id: str,
    *,
    root: Path,
    specs: Sequence[StoreSpec],
    relative_path_key: str = "root_relative_path",
) -> dict[str, Any]:
    spec = next((candidate for candidate in specs if candidate.store_id == store_id), None)
    if spec is None:
        msg = f"Unknown store identifier: {store_id!r}"
        raise ValueError(msg)

    path = spec.path
    exists = path.exists()
    warnings: list[str] = []
    payload = _base_store_payload(
        spec,
        root=root,
        exists=exists,
        warnings=warnings,
        relative_path_key=relative_path_key,
    )
    if not exists:
        return payload

    if not _populate_store_stat_payload(path, payload, warnings):
        return payload

    if spec.path_kind == "dir":
        _populate_directory_payload(path, payload, warnings)
        return payload

    metadata_provider = spec.metadata_provider or generic_store_metadata
    metadata = metadata_provider(path, warnings)
    if metadata:
        payload["metadata"] = metadata
    if warnings and payload["store_status"] == "present":
        payload["store_status"] = "degraded"
    return payload


def generic_store_metadata(path: Path, warnings: list[str]) -> dict[str, Any]:
    if path.suffix == ".sqlite":
        return sqlite_store_metadata(path, warnings)
    shape = json_shape(path)
    return {"json_shape": shape} if shape is not None else {}


def mirror_state_metadata(path: Path, warnings: list[str]) -> dict[str, Any]:
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


def sync_manifest_metadata(path: Path, warnings: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"Sync manifest unreadable: {exc}")
        return metadata
    if not isinstance(raw, dict):
        warnings.append("Sync manifest is not a JSON object.")
        return metadata
    results = raw.get("results")
    metadata["results_sections"] = sorted(str(key) for key in results) if isinstance(results, dict) else []
    if isinstance(raw.get("errors"), list):
        metadata["errors_count"] = len(raw["errors"])
    if "ok" in raw:
        metadata["ok"] = bool(raw["ok"])
    return metadata


def sqlite_store_metadata(path: Path, warnings: list[str]) -> JsonObject:
    meta, err = sqlite_meta(path)
    if err is not None:
        warnings.append(f"SQLite metadata unreadable: {err}")
        return {}
    return dict((meta or {}).items())


def json_shape(path: Path) -> str | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(raw, dict):
        return "object"
    if isinstance(raw, list):
        return "array"
    return type(raw).__name__


def sqlite_meta(path: Path) -> tuple[dict[str, str] | None, str | None]:
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
    return {str(key): str(value) for key, value in rows}, None


def rel_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _base_store_payload(
    spec: StoreSpec,
    *,
    root: Path,
    exists: bool,
    warnings: list[str],
    relative_path_key: str,
) -> dict[str, Any]:
    return {
        "target_kind": "store",
        "store_id": spec.store_id,
        "category": spec.category,
        "label": spec.label,
        "description": spec.description,
        "path_kind": spec.path_kind,
        "path": str(spec.path),
        relative_path_key: rel_to_root(spec.path, root),
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


__all__ = [
    "StoreMetadataProvider",
    "StorePathKind",
    "StoreSpec",
    "generic_store_metadata",
    "json_shape",
    "mirror_state_metadata",
    "rel_to_root",
    "sqlite_meta",
    "sqlite_store_metadata",
    "store_payload_for_specs",
    "store_summary_entries",
    "sync_manifest_metadata",
]
