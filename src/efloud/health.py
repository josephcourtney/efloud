from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from efloud.json_types import JsonObject, copy_json_mapping, json_mapping_or_none
from efloud.transport.rsync import read_rsync_mirror_meta

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from efloud.models import NormalizedManifest


@dataclass(frozen=True)
class MirrorHealthSummary:
    mirror_timestamps: dict[str, float | None]
    missing_roots: tuple[str, ...]
    manifest_errors: tuple[str, ...]
    rsync_results: dict[str, JsonObject]
    http_results: dict[str, JsonObject]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mirror_timestamps": self.mirror_timestamps,
            "missing_roots": list(self.missing_roots),
            "manifest_errors": list(self.manifest_errors),
            "rsync_results": self.rsync_results,
            "http_results": self.http_results,
        }


def _mirror_last_sync(root: Path | None) -> float | None:
    if root is None:
        return None
    meta = read_rsync_mirror_meta(root)
    if meta is None or not isinstance(meta.paths, dict):
        return None
    entry = meta.paths.get(".")
    if not isinstance(entry, dict):
        return None
    ts = entry.get("updated_at_unix")
    return float(ts) if isinstance(ts, (int, float)) else None


def _manifest_section(
    manifest: NormalizedManifest | None,
    section: Literal["rsync", "http"],
) -> dict[str, JsonObject]:
    if not manifest:
        return {}
    sec = manifest["results"][section]
    out: dict[str, JsonObject] = {}
    for name, value in sec.items():
        value_mapping = json_mapping_or_none(value)
        if value_mapping is not None:
            out[name] = copy_json_mapping(value_mapping)
    return out


def _manifest_errors(manifest: NormalizedManifest | None) -> tuple[str, ...]:
    if not manifest:
        return ()
    out: list[str] = []
    for entry in manifest["errors"]:
        err = entry.get("error")
        out.append(str(err) if err is not None else str(entry))
    return tuple(out)


def build_mirror_health_summary(
    mirror_roots: Mapping[str, Path | None],
    manifest: NormalizedManifest | None = None,
) -> MirrorHealthSummary:
    mirror_timestamps = {name: _mirror_last_sync(root) for name, root in mirror_roots.items()}
    missing = tuple(name for name, root in mirror_roots.items() if root is None or not root.exists())
    return MirrorHealthSummary(
        mirror_timestamps=mirror_timestamps,
        missing_roots=missing,
        manifest_errors=_manifest_errors(manifest),
        rsync_results=_manifest_section(manifest, "rsync"),
        http_results=_manifest_section(manifest, "http"),
    )
