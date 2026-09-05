from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from efloud.json_types import JsonMapping, JsonObject, JsonValue, copy_json_mapping, json_mapping_or_none

if TYPE_CHECKING:
    from efloud.models import NormalizedManifest


def normalize_manifest(raw: object) -> NormalizedManifest:
    """Normalize an arbitrary runtime payload into the canonical manifest shape."""
    raw_mapping = json_mapping_or_none(raw)
    if raw_mapping is None:
        msg = "manifest must be a JSON object"
        raise TypeError(msg)

    m: JsonObject = copy_json_mapping(raw_mapping)
    m.setdefault("version", 1)
    m.setdefault("root", "")
    m.setdefault("errors", [])
    m.setdefault("results", {"rsync": {}, "http": {}, "derived": {}})

    # --- normalize results container
    results = json_mapping_or_none(m.get("results"))
    if results is None:
        results: JsonObject = {"rsync": {}, "http": {}, "derived": {}}
        m["results"] = results
    else:
        results = copy_json_mapping(results)
        m["results"] = results
        results.setdefault("rsync", {})
        results.setdefault("http", {})
        results.setdefault("derived", {})

        # Ensure each subsection is a dict-like object
        for key in ("rsync", "http", "derived"):
            sec = json_mapping_or_none(results.get(key))
            if sec is None:
                results[key] = {}
            else:
                results[key] = copy_json_mapping(sec)

    # --- normalize http entries to always have top-level "url"
    http = json_mapping_or_none(results.get("http"))
    if http is not None:
        http = copy_json_mapping(http)
        results["http"] = http
        for k, rec in list(http.items()):
            rec_mapping = json_mapping_or_none(rec)
            if rec_mapping is not None:
                entry = copy_json_mapping(rec_mapping)
                if "url" not in entry:
                    req = json_mapping_or_none(entry.get("request"))
                    req_url = req.get("url") if req is not None else None
                    if isinstance(req_url, str):
                        entry["url"] = req_url
                http[k] = entry  # write back

    # You can add more migrations here if needed.

    return cast("NormalizedManifest", m)


def _merge_result_entries(
    destination: dict[str, JsonObject],
    previous: JsonMapping | None,
    current: JsonMapping | None,
) -> None:
    if previous is not None:
        for key, value in previous.items():
            value_mapping = json_mapping_or_none(value)
            if value_mapping is not None:
                destination.setdefault(str(key), copy_json_mapping(value_mapping))

    if current is not None:
        for key, value in current.items():
            value_mapping = json_mapping_or_none(value)
            if value_mapping is not None:
                destination[str(key)] = copy_json_mapping(value_mapping)


def merge_manifests(previous: object | None, new: object) -> NormalizedManifest:
    """
    Merge two manifest-like runtime payloads while retaining per-source results.

    This is primarily used to keep a canonical manifest (e.g. ``sync-manifest.json``)
    "complete" even when a sync run only targets a subset of sources.

    Policy:
    - Results are merged per subsection: rsync/http/derived.
      New keys overwrite old keys; missing keys in ``new`` do not delete old data.
    - Top-level metadata (started/finished/config/version/root) is taken from ``new``.
    - Errors are replaced with ``new`` run errors (do not accumulate historical errors).
    """
    try:
        prev = normalize_manifest(previous if previous is not None else {})
    except TypeError:
        prev = normalize_manifest({})
    nxt = normalize_manifest(new)

    out = dict(prev.items())

    # Prefer the most recent run metadata.
    for key in (
        "version",
        "root",
        "started_at_unix",
        "started_at_iso",
        "finished_at_unix",
        "finished_at_iso",
        "duration_seconds",
        "config",
    ):
        if key in nxt:
            out[key] = nxt[key]

    out["errors"] = list(nxt.get("errors", []))

    merged = normalize_manifest(out)
    merged_results = merged["results"]
    prev_results = prev.get("results", {})
    nxt_results = nxt.get("results", {})

    _merge_result_entries(
        merged_results["rsync"],
        json_mapping_or_none(prev_results.get("rsync")),
        json_mapping_or_none(nxt_results.get("rsync")),
    )
    _merge_result_entries(
        merged_results["http"],
        json_mapping_or_none(prev_results.get("http")),
        json_mapping_or_none(nxt_results.get("http")),
    )
    _merge_result_entries(
        merged_results["derived"],
        json_mapping_or_none(prev_results.get("derived")),
        json_mapping_or_none(nxt_results.get("derived")),
    )

    return merged


def _latest_manifest_path(log_dir: Path, base_filename: str) -> Path | None:
    if not log_dir.exists():
        return None
    base = Path(base_filename)
    suffix = base.suffix or ""
    pattern = f"{base.stem}-*{suffix}"
    candidates = list(log_dir.glob(pattern))
    pointer = log_dir / base
    if pointer.exists():
        candidates.append(pointer)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_latest_manifest(
    log_dir: Path,
    manifest_filename: str,
    *,
    expected_root: Path | None = None,
) -> tuple[NormalizedManifest | None, list[str], Path]:
    """
    Load the most recent sync manifest from ``log_dir``.

    Returns (manifest|None, warnings[], manifest_path_guess).
    """
    warnings: list[str] = []
    manifest_path = _latest_manifest_path(log_dir, manifest_filename)
    if manifest_path is None:
        candidate = log_dir / manifest_filename
        warnings.append(f"sync manifest missing: {candidate}")
        return None, warnings, candidate

    try:
        data: JsonValue = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"sync manifest unreadable: {exc}")
        return None, warnings, manifest_path

    manifest = normalize_manifest(data)
    if expected_root is not None:
        manifested_root = manifest.get("root")
        if isinstance(manifested_root, str):
            try:
                actual_root = Path(manifested_root).resolve()
                expected = expected_root.resolve()
                if actual_root != expected:
                    warnings.append(
                        f"sync manifest root {actual_root} conflicts with configured cache root {expected}",
                    )
            except OSError:
                pass

    return manifest, warnings, manifest_path
