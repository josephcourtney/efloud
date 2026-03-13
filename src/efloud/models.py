from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, Required, TypedDict

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.derived import DerivedTask
    from efloud.indexing import IndexRegistry
    from efloud.json_types import JsonObject
    from efloud.policy import SyncPolicy
    from efloud.registry import SourceDefinition
    from efloud.source_aliases import AliasMap


class ManifestError(TypedDict):
    phase: str
    error: str
    name: NotRequired[str]
    source_id: NotRequired[str]
    url: NotRequired[str]


class ManifestResults(TypedDict):
    http: dict[str, JsonObject]
    rsync: dict[str, JsonObject]
    derived: dict[str, JsonObject]


class Manifest(TypedDict, total=False):
    version: int
    started_at_unix: int
    started_at_iso: str
    finished_at_unix: int
    finished_at_iso: str
    duration_seconds: float
    root: str
    config: JsonObject
    results: ManifestResults
    errors: list[ManifestError]


class NormalizedManifest(Manifest, total=False):
    """Canonical schema guaranteed by ``normalize_manifest``."""

    version: Required[int]
    root: Required[str]
    results: Required[ManifestResults]
    errors: Required[list[ManifestError]]


@dataclass(frozen=True)
class EngineConfig:
    root: Path
    sources: list[SourceDefinition]

    http_concurrency: int = 10
    http_dir: str = "http"
    cache_dir: str = "cache"
    mirrors_dir: str = "mirrors"
    rate_limits_dir: str = "rate_limits"
    http_cache_dir: str = "http_cache"
    log_dir: str = "log"

    manifest_filename: str = "sync-manifest.json"
    state_filename: str = "mirror-state.json"

    refresh_all: bool = False
    refresh_http: bool = False
    refresh_rsync: bool = False

    skip_rsync: bool = False
    skip_derived: bool = False

    delete_http_caches: bool = False
    prune_orphan_mirrors: bool = False
    remove_empty_dirs_after_rsync: bool = True
    dry_run: bool = False

    manifest_path: Path | None = None

    sync_policy: SyncPolicy | None = None
    derived_tasks: tuple[DerivedTask, ...] = ()
    source_aliases: AliasMap | None = None
    index_registry: IndexRegistry | None = None


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    root: Path
    manifest_path: Path | None
    manifest: NormalizedManifest
