from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from efloud.models import NormalizedManifest


def normalize_manifest(raw: object) -> NormalizedManifest:
    if not isinstance(raw, Mapping):
        msg = "manifest must be a JSON object"
        raise TypeError(msg)

    m = dict(raw)  # shallow copy
    m.setdefault("version", 1)
    m.setdefault("root", "")
    m.setdefault("errors", [])
    m.setdefault("results", {"rsync": {}, "http": {}, "derived": {}})

    # --- normalize results container
    results = m.get("results")
    if not isinstance(results, Mapping):
        results = {"rsync": {}, "http": {}, "derived": {}}
        m["results"] = results
    else:
        results = dict(results)
        m["results"] = results
        results.setdefault("rsync", {})
        results.setdefault("http", {})
        results.setdefault("derived", {})

        # Ensure each subsection is a dict-like object
        for key in ("rsync", "http", "derived"):
            sec = results.get(key)
            if not isinstance(sec, Mapping):
                results[key] = {}
            else:
                results[key] = dict(sec)

    # --- normalize http entries to always have top-level "url"
    http = results.get("http")
    if isinstance(http, Mapping):
        http = dict(http)
        results["http"] = http
        for k, rec in list(http.items()):
            if isinstance(rec, Mapping):
                entry = dict(rec)
                if "url" not in entry:
                    req = entry.get("request")
                    if isinstance(req, Mapping) and isinstance(req.get("url"), str):
                        entry["url"] = req["url"]
                http[k] = entry  # write back

    # You can add more migrations here if needed.

    return m  # type: ignore[return-value]


def merge_manifests(previous: object | None, new: object) -> NormalizedManifest:
    """
    Merge two manifests such that per-source results are retained across runs.

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

    out: dict[str, object] = dict(prev)

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
            out[key] = nxt[key]  # type: ignore[literal-required]

    out["errors"] = list(nxt.get("errors", []))

    merged = normalize_manifest(out)
    merged_results = merged["results"]
    prev_results = prev.get("results", {})
    nxt_results = nxt.get("results", {})

    # Merge per-section results.
    for section in ("rsync", "http", "derived"):
        prev_sec = prev_results.get(section, {}) if isinstance(prev_results, Mapping) else {}
        nxt_sec = nxt_results.get(section, {}) if isinstance(nxt_results, Mapping) else {}
        dst = merged_results.get(section)
        if not isinstance(dst, dict):
            dst = {}
            merged_results[section] = dst  # type: ignore[literal-required]

        if isinstance(prev_sec, Mapping):
            for k, v in prev_sec.items():
                dst.setdefault(str(k), v)
        if isinstance(nxt_sec, Mapping):
            for k, v in nxt_sec.items():
                dst[str(k)] = v

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
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
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
