from __future__ import annotations

import contextlib
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from anyio import Path as AnyioPath

from efloud.fs import (
    atomic_write_text,
    delete_http_cache_files,
    ensure_root_dirs,
    prune_orphan_mirrors,
    safe_json_dump,
)
from efloud.json_types import copy_json_mapping, json_mapping_or_none
from efloud.manifest import merge_manifests, normalize_manifest
from efloud.models import EngineConfig, ManifestError, NormalizedManifest, SyncResult
from efloud.policy import DefaultSyncPolicy
from efloud.registry import SourceDefinition, SourceKind
from efloud.state import (
    HASH_ALGORITHM,
    MirrorSourceState,
    MirrorState,
    MirrorStateNode,
    load_mirror_state,
    node_at_path,
    update_hash_tree_for_subdirs,
)
from efloud.transport.http import HttpCache, HttpCacheConfig
from efloud.transport.http_utils import (
    HttpFetchResult,
    cache_group_name,
    dest_for_http_source,
    fetch_json_to_file,
    fetch_to_file,
)
from efloud.transport.rsync import RsyncCommandConfig, RsyncMirror, RsyncMirrorConfig, read_rsync_mirror_meta

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)
_HASH_PROGRESS_MIN_SECONDS = 2.0
_HASH_PROGRESS_MIN_FILES = 10_000


class ManifestRecorder:
    def __init__(self, *, root: Path, cfg: EngineConfig) -> None:
        now = int(time.time())
        self._started_at_unix = now
        self._manifest: NormalizedManifest = {
            "version": 1,
            "started_at_unix": now,
            "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "root": str(root),
            "config": {
                "http_concurrency": cfg.http_concurrency,
                "refresh_all": cfg.refresh_all,
                "refresh_http": cfg.refresh_http,
                "refresh_rsync": cfg.refresh_rsync,
                "skip_rsync": cfg.skip_rsync,
                "skip_derived": cfg.skip_derived,
                "delete_http_caches": cfg.delete_http_caches,
                "prune_orphan_mirrors": cfg.prune_orphan_mirrors,
                "dry_run": cfg.dry_run,
            },
            "results": {"rsync": {}, "http": {}, "derived": {}},
            "errors": [],
        }

    @property
    def manifest(self) -> NormalizedManifest:
        return self._manifest

    def error(self, *, phase: str, error: str, **fields: str) -> None:
        payload: ManifestError = {"phase": phase, "error": error, **fields}
        self._manifest["errors"].append(payload)

    def record_http(self, *, manifest_key: str, entry: dict[str, Any]) -> None:
        self._manifest["results"]["http"][manifest_key] = entry

    def record_rsync(self, *, manifest_key: str, entry: dict[str, Any]) -> None:
        self._manifest["results"]["rsync"][manifest_key] = entry

    def record_derived(self, *, name: str, payload: dict[str, Any]) -> None:
        self._manifest["results"]["derived"][name] = payload

    def record_http_cache_deleted(self, removed: list[str]) -> None:
        self._manifest["results"]["http"]["cache_deleted"] = {"removed": removed}

    def record_pruned_orphan_mirrors(self, removed: list[str]) -> None:
        self._manifest["results"]["rsync"]["pruned_orphan_mirrors"] = {"removed": removed}

    def finish(self) -> None:
        end = int(time.time())
        self._manifest["finished_at_unix"] = end
        self._manifest["finished_at_iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end))
        self._manifest["duration_seconds"] = round(end - self._started_at_unix, 3)

    async def write_if_requested(self, path: Path | None) -> Path | None:
        if path is None:
            return None
        resolved = await AnyioPath(path).resolve()
        await resolved.parent.mkdir(parents=True, exist_ok=True)
        await resolved.write_text(safe_json_dump(self._manifest))
        return Path(str(resolved))


def _iso_from_unix(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _manifest_key_for_source(source: SourceDefinition) -> str:
    return source.id


def _http_freshness_record(result: HttpFetchResult) -> dict[str, Any]:
    headers = result.headers or {}
    return {
        "status_code": result.status_code,
        "checksum": result.checksum,
        "size_bytes": result.size_bytes,
        "fetched_at_unix": result.fetched_at,
        "fetched_at_iso": _iso_from_unix(result.fetched_at),
        "etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
    }


def _http_manifest_entry(
    source: SourceDefinition,
    dest: Path,
    *,
    refresh: bool,
    result: HttpFetchResult | None = None,
    ok: bool = True,
    error: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "source_id": source.id,
        "description": source.description,
        "ok": ok,
        "kind": source.kind.value,
        "dest": str(dest),
        "url": source.url,
        "request": {
            "url": source.url,
            "method": "GET",
            "headers": dict(result.request_headers) if result else {},
            "refresh": bool(refresh),
        },
    }
    if result:
        entry["status_code"] = result.status_code
        entry["freshness"] = _http_freshness_record(result)
    if error:
        entry["error"] = error
    return entry


def _rsync_manifest_entry(
    source: SourceDefinition,
    local: Path,
    mode: str,
    results: dict[str, Any] | None,
    *,
    force: bool,
    paths: list[str] | None = None,
    freshness: dict[str, Any] | None = None,
    ok: bool = True,
    error: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "source_id": source.id,
        "description": source.description,
        "ok": ok,
        "remote": source.url,
        "local": str(local),
        "mode": mode,
        "request": {
            "remote": source.url,
            "local": str(local),
            "paths": paths,
            "force": force,
            "update_paths": mode == "update_paths",
        },
    }
    if results is not None:
        entry["results"] = results
    if freshness is not None:
        entry["freshness"] = freshness
    if error:
        entry["error"] = error
    return entry


def _rsync_freshness_record(root: Path) -> dict[str, Any]:
    meta = read_rsync_mirror_meta(root)
    if meta is None or not isinstance(meta.paths, dict):
        return {}

    paths: dict[str, dict[str, Any]] = {}
    for rel, info in meta.paths.items():
        if not isinstance(info, dict):
            continue
        ts = info.get("updated_at_unix")
        updated = info.get("updated")
        if not isinstance(ts, (int, float)):
            continue
        entry: dict[str, Any] = {"last_updated_unix": float(ts)}
        if isinstance(updated, list):
            entry["updated"] = list(updated)
        paths[rel] = entry

    if not paths:
        return {}

    freshness: dict[str, Any] = {"paths": paths}
    root_info = paths.get(".")
    if root_info:
        freshness["root_last_updated_unix"] = root_info["last_updated_unix"]
    return freshness


def _rsync_results_ok(results_payload: dict[str, Any]) -> bool:
    for result in results_payload.values():
        if not isinstance(result, dict):
            continue
        if result.get("status") in {"failed", "timed_out"}:
            return False
    return True


def _rsync_failure_detail(results_payload: dict[str, Any]) -> str | None:
    for name, result in results_payload.items():
        if not isinstance(result, dict):
            continue
        status = result.get("status")
        if status not in {"failed", "timed_out"}:
            continue
        detail = result.get("detail")
        if isinstance(detail, str) and detail:
            return f"{name}: {detail}"
        return f"{name}: {status}"
    return None


def should_refresh(source: SourceDefinition, cfg: EngineConfig) -> bool:
    return (cfg.sync_policy or DefaultSyncPolicy()).should_refresh(source, cfg)


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _emit_sync_runtime_message(cfg: EngineConfig, text: str) -> None:
    if not cfg.runtime_progress:
        return
    with contextlib.suppress(OSError):
        sys.stderr.write(f"{text}\n")
        sys.stderr.flush()


@dataclass(frozen=True)
class SyncPaths:
    root: Path
    http: Path
    cache: Path
    mirrors: Path
    rate: Path
    http_cache: Path
    log: Path


def prepare_paths(root: Path, cfg: EngineConfig) -> SyncPaths:
    dir_names = {
        "http": cfg.http_dir,
        "cache": cfg.cache_dir,
        "mirrors": cfg.mirrors_dir,
        "rate": cfg.rate_limits_dir,
        "log": cfg.log_dir,
    }
    paths = ensure_root_dirs(root, dir_names)
    http_cache = paths["cache"] / cfg.http_cache_dir
    http_cache.mkdir(parents=True, exist_ok=True)
    return SyncPaths(
        root=paths["root"],
        http=paths["http"],
        cache=paths["cache"],
        mirrors=paths["mirrors"],
        rate=paths["rate"],
        http_cache=http_cache,
        log=paths["log"],
    )


def _default_manifest_path(paths: SyncPaths, filename: str) -> Path:
    return paths.log / filename


def _timestamped_manifest_path(log_dir: Path, filename: str, *, when: float | None = None) -> Path:
    base = Path(filename)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(when if when is not None else time.time()))
    return log_dir / f"{base.stem}-{timestamp}{base.suffix or ''}"


def build_http_caches(
    *,
    sources: list[SourceDefinition],
    cache_root: Path,
    rate_root: Path,
) -> dict[str, HttpCache]:
    http_caches: dict[str, HttpCache] = {}
    cache_root.mkdir(parents=True, exist_ok=True)

    for source in sources:
        if source.kind not in {SourceKind.HTTP, SourceKind.REST, SourceKind.REST_BASE}:
            continue

        group = cache_group_name(source.url, source.cache_name)
        if group in http_caches:
            continue

        http_caches[group] = HttpCache(
            HttpCacheConfig(
                name=group,
                ttl_seconds=300,
                timeout=60.0,
                cache_db_path=str(cache_root / f"{group}.db"),
                enable_cache=True,
                rate_limit_storage=_sqlite_url(rate_root / "rate_limits.sqlite"),
                rate_limit_scope=None,
                raise_on_rate_limit=False,
                retries=5,
                retry_wait_multiplier=1.0,
                retry_wait_min=1.0,
                retry_wait_max=30.0,
            ),
        )

    return http_caches


async def run_http_phase(
    *,
    cfg: EngineConfig,
    paths: SyncPaths,
    http_caches: dict[str, HttpCache],
    recorder: ManifestRecorder,
) -> None:
    if cfg.dry_run:
        return

    for source in cfg.sources:
        if source.kind not in {SourceKind.HTTP, SourceKind.REST}:
            continue

        group = cache_group_name(source.url, source.cache_name)
        cache = http_caches[group]
        dest = dest_for_http_source(
            paths.http,
            url=source.url,
            description=source.description,
            kind=source.kind.value,
            cache_name=source.cache_name,
        )
        refresh = (cfg.sync_policy or DefaultSyncPolicy()).should_refresh(source, cfg)
        manifest_key = _manifest_key_for_source(source)

        try:
            if source.kind is SourceKind.REST:
                _, http_result = await fetch_json_to_file(cache, source.url, dest, refresh=refresh)
            else:
                http_result = await fetch_to_file(cache, source.url, dest, refresh=refresh)

            recorder.record_http(
                manifest_key=manifest_key,
                entry=_http_manifest_entry(source, dest, refresh=refresh, result=http_result),
            )
        except (OSError, httpx.HTTPError, ValueError) as exc:
            recorder.error(
                phase="http",
                name=source.description,
                source_id=source.id,
                url=source.url,
                error=f"{type(exc).__name__}: {exc}",
            )
            recorder.record_http(
                manifest_key=manifest_key,
                entry=_http_manifest_entry(
                    source,
                    dest,
                    refresh=refresh,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )


async def run_rsync_phase(
    *,
    cfg: EngineConfig,
    paths: SyncPaths,
    recorder: ManifestRecorder,
) -> set[Path]:
    expected_mirror_dirs: set[Path] = set()

    if cfg.skip_rsync:
        return expected_mirror_dirs

    for source in cfg.sources:
        if source.kind is not SourceKind.RSYNC:
            continue

        manifest_key = _manifest_key_for_source(source)
        local_subdir = source.local_subpath or source.id
        local = paths.mirrors / local_subdir
        expected_mirror_dirs.add(local)

        mirror_cfg = RsyncMirrorConfig(
            name=source.description,
            remote=source.url,
            local=local,
            meta_path=(local / ".mirror_meta.json"),
            delete=False,
            timeout_seconds=1200.0,
            port=source.port,
            include=source.include or (),
            exclude=source.exclude or ("**/.DS_Store",),
            rate_limit_storage=_sqlite_url(paths.rate / "mirror_rate_limits.sqlite"),
            rate_limit_scope=None,
            raise_on_rate_limit=False,
            progress=cfg.runtime_progress,
            dry_run=cfg.dry_run,
            cmd=RsyncCommandConfig(
                rsync_bin="rsync",
                archive=True,
                compress=True,
                copy_links=True,
                delay_updates=True,
                itemize_changes=True,
            ),
        )
        mirror = RsyncMirror(mirror_cfg)

        policy = cfg.sync_policy or DefaultSyncPolicy()
        force = policy.should_refresh(source, cfg)
        mirror_paths = policy.rsync_paths_for_source(
            source=source,
            cache_root=paths.root,
            manifest=recorder.manifest,
        )
        mode = "update_paths" if mirror_paths else "update"

        try:
            if cfg.dry_run:
                results_payload: dict[str, Any]
                if mirror_paths:
                    results_payload = {
                        rel: {"status": "dry_run", "detail": "dry run (mirror skipped)", "returncode": 0}
                        for rel in mirror_paths
                    }
                else:
                    results_payload = {
                        "update": {
                            "status": "dry_run",
                            "detail": "dry run (mirror skipped)",
                            "returncode": 0,
                            "mode": mode,
                        },
                    }
                recorder.record_rsync(
                    manifest_key=manifest_key,
                    entry=_rsync_manifest_entry(
                        source,
                        local,
                        mode,
                        results_payload,
                        force=force,
                        paths=list(mirror_paths) if mirror_paths else None,
                    ),
                )
                continue

            if mirror_paths:
                per_path = await mirror.update_paths(list(mirror_paths), force=force)
                results_payload = {
                    rel: {
                        "status": r.status,
                        "detail": r.detail,
                        "phase": r.phase,
                        "returncode": r.returncode,
                        "timed_out": r.timed_out,
                        "attempt_count": r.attempt_count,
                        "max_attempts": r.max_attempts,
                        "attempt_errors": list(r.attempt_errors or []),
                        "stdout": r.stdout,
                        "stderr": r.stderr,
                        "updated": list(r.updated or []),
                    }
                    for rel, r in per_path.items()
                }
            else:
                res = await mirror.update(force=force)
                results_payload = {
                    "update": {
                        "status": res.status,
                        "detail": res.detail,
                        "phase": res.phase,
                        "returncode": res.returncode,
                        "timed_out": res.timed_out,
                        "attempt_count": res.attempt_count,
                        "max_attempts": res.max_attempts,
                        "attempt_errors": list(res.attempt_errors or []),
                        "stdout": res.stdout,
                        "stderr": res.stderr,
                        "updated": list(res.updated or []),
                    },
                }
            source_ok = _rsync_results_ok(results_payload)
            failure_detail = _rsync_failure_detail(results_payload)
            if not source_ok:
                recorder.error(
                    phase="rsync",
                    name=source.description,
                    source_id=source.id,
                    error=failure_detail or "rsync failed",
                )

            recorder.record_rsync(
                manifest_key=manifest_key,
                entry=_rsync_manifest_entry(
                    source,
                    local,
                    mode,
                    results_payload,
                    force=force,
                    paths=list(mirror_paths) if mirror_paths else None,
                    freshness=_rsync_freshness_record(local) or None,
                    ok=source_ok,
                    error=failure_detail,
                ),
            )

            if cfg.remove_empty_dirs_after_rsync:
                with contextlib.suppress(OSError, RuntimeError):
                    await mirror.prune_local_empty_dirs()

        except (OSError, RuntimeError) as exc:
            recorder.error(
                phase="rsync",
                name=source.description,
                source_id=source.id,
                error=f"{type(exc).__name__}: {exc}",
            )
            recorder.record_rsync(
                manifest_key=manifest_key,
                entry=_rsync_manifest_entry(
                    source,
                    local,
                    mode,
                    results=None,
                    force=force,
                    paths=list(mirror_paths) if mirror_paths else None,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )

    return expected_mirror_dirs


async def _run_derived_tasks(
    *,
    cfg: EngineConfig,
    paths: SyncPaths,
    recorder: ManifestRecorder,
) -> None:
    if cfg.skip_derived or cfg.dry_run:
        return
    for task in cfg.derived_tasks:
        try:
            payload = await task.run(
                sync_root=paths.root,
                manifest=recorder.manifest,
                sources=tuple(cfg.sources),
            )
            payload_mapping = json_mapping_or_none(payload)
            recorder.record_derived(
                name=task.name,
                payload=copy_json_mapping(payload_mapping) if payload_mapping is not None else {},
            )
        except (OSError, RuntimeError, TypeError, ValueError, httpx.HTTPError) as exc:
            recorder.error(
                phase="derived",
                error=f"{type(exc).__name__}: {exc}",
                name=task.name,
            )


async def _close_http_caches(http_caches: dict[str, HttpCache]) -> None:
    for cache in http_caches.values():
        with contextlib.suppress(OSError, RuntimeError):
            await cache.aclose()


async def _write_manifest_outputs(
    *,
    cfg: EngineConfig,
    paths: SyncPaths,
    recorder: ManifestRecorder,
) -> Path | None:
    log_manifest_target = _timestamped_manifest_path(paths.log, cfg.manifest_filename)
    try:
        manifest_path = await recorder.write_if_requested(log_manifest_target)
        if cfg.manifest_path and Path(cfg.manifest_path) != log_manifest_target:
            with contextlib.suppress(OSError, RuntimeError, TypeError, ValueError):
                await recorder.write_if_requested(Path(cfg.manifest_path))
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return manifest_path


def _update_canonical_manifest(
    *,
    cfg: EngineConfig,
    paths: SyncPaths,
    recorder: ManifestRecorder,
) -> None:
    if cfg.dry_run:
        return
    canonical_manifest_target = _default_manifest_path(paths, cfg.manifest_filename)
    try:
        prev_raw: Any | None = None
        if canonical_manifest_target.exists():
            prev_raw = json.loads(canonical_manifest_target.read_text(encoding="utf-8"))
        merged = merge_manifests(prev_raw, recorder.manifest)
        merged = normalize_manifest(merged)
        atomic_write_text(canonical_manifest_target, safe_json_dump(merged))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning(
            "failed to update canonical manifest file %s",
            canonical_manifest_target,
            exc_info=True,
        )


def _mirror_source_info(cfg: EngineConfig) -> list[tuple[str, str]]:
    return [
        (source.id, source.local_subpath or "") for source in cfg.sources if source.local_subpath is not None
    ]


def _normalized_subdir(path: str) -> str:
    return path.strip().strip("/").replace("\\", "/")


def _manifest_request_paths(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    request = payload.get("request")
    request_paths = request.get("paths") if isinstance(request, dict) else None
    if not isinstance(request_paths, list):
        return []
    return [rel for rel in request_paths if isinstance(rel, str)]


def _incremental_rsync_subdirs(
    *,
    cfg: EngineConfig,
    manifest: NormalizedManifest,
) -> list[str]:
    rsync_results = manifest.get("results", {}).get("rsync", {})
    if not isinstance(rsync_results, dict):
        return []

    source_by_id = {source.id: source for source in cfg.sources if source.kind is SourceKind.RSYNC}
    touched: set[str] = set()

    for source_id, payload in rsync_results.items():
        if not isinstance(source_id, str) or not isinstance(payload, dict):
            continue
        if payload.get("ok") is False:
            continue
        source = source_by_id.get(source_id)
        if source is None or source.local_subpath is None:
            continue
        local_subpath = _normalized_subdir(source.local_subpath)
        request_paths = _manifest_request_paths(payload)
        if request_paths:
            for rel in request_paths:
                rel_subpath = _normalized_subdir(rel)
                if rel_subpath:
                    touched.add(f"{local_subpath}/{rel_subpath}")
            continue
        if local_subpath:
            touched.add(local_subpath)

    return sorted(touched)


def _build_source_states(
    previous_state: MirrorState,
    tree: MirrorStateNode,
    source_info: list[tuple[str, str]],
) -> tuple[MirrorSourceState, ...]:
    source_states: dict[tuple[str | None, str], MirrorSourceState] = {
        (src_state.source_id, src_state.local_subdir): src_state for src_state in previous_state.sources
    }
    for source_id, subdir in source_info:
        node = node_at_path(tree, subdir)
        source_states[source_id, subdir] = MirrorSourceState(
            source_id=source_id,
            local_subdir=subdir,
            hash=node.hash if node is not None else None,
        )
    return tuple(sorted(source_states.values(), key=lambda item: (item.local_subdir, item.source_id or "")))


def _build_incremental_state(
    *,
    cfg: EngineConfig,
    paths: SyncPaths,
    manifest_path: Path,
    previous_state: MirrorState,
    touched_subdirs: list[str] | None = None,
    progress: Callable[[str, int, int, Path], None] | None = None,
) -> MirrorState:
    source_info = _mirror_source_info(cfg)
    source_subdirs = (
        touched_subdirs
        if touched_subdirs is not None
        else sorted({subdir for _, subdir in source_info if subdir})
    )
    tree = previous_state.tree
    if source_subdirs:
        tree = update_hash_tree_for_subdirs(tree, paths.mirrors, source_subdirs, on_progress=progress)
    return MirrorState(
        version=1,
        generated_at_unix=time.time(),
        cache_root=str(paths.root.resolve()),
        mirrors_root=str(paths.mirrors.resolve()),
        hash_algo=HASH_ALGORITHM,
        manifest_path=str(manifest_path),
        tree=tree,
        sources=_build_source_states(previous_state, tree, source_info),
    )


def _update_mirror_state(*, cfg: EngineConfig, paths: SyncPaths, manifest_path: Path) -> None:
    if cfg.dry_run:
        return
    state_path = paths.root / cfg.state_filename
    source_info = _mirror_source_info(cfg)
    try:
        previous_state = load_mirror_state(state_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        can_reuse_tree = (
            previous_state is not None
            and Path(previous_state.mirrors_root) == paths.mirrors.resolve()
            and previous_state.hash_algo == HASH_ALGORITHM
        )
        progress_state: dict[str, float | int | str] = {
            "last_emit_at": 0.0,
            "last_emit_files": 0,
        }

        def emit_hash_progress(rel: str, files: int, dirs: int, current_path: Path) -> None:
            if not cfg.runtime_progress:
                return
            now = time.perf_counter()
            if (now - float(progress_state["last_emit_at"])) < _HASH_PROGRESS_MIN_SECONDS and (
                files - int(progress_state["last_emit_files"])
            ) < _HASH_PROGRESS_MIN_FILES:
                return
            progress_state["last_emit_at"] = now
            progress_state["last_emit_files"] = files
            _emit_sync_runtime_message(
                cfg,
                (f"mirror-state: hashing {rel} scanned {files} files ({dirs} dirs); latest {current_path}"),
            )

        if can_reuse_tree and previous_state is not None:
            source_subdirs = _incremental_rsync_subdirs(cfg=cfg, manifest=manifest)
            _emit_sync_runtime_message(
                cfg,
                (
                    f"mirror-state: updating {len(source_subdirs)} touched "
                    f"subtree{'s' if len(source_subdirs) != 1 else ''}..."
                ),
            )
            state = _build_incremental_state(
                cfg=cfg,
                paths=paths,
                manifest_path=manifest_path,
                previous_state=previous_state,
                touched_subdirs=source_subdirs,
                progress=emit_hash_progress,
            )
        else:
            _emit_sync_runtime_message(cfg, "mirror-state: rebuilding full mirror hash tree...")
            state = MirrorState.build(
                cache_root=paths.root,
                mirrors_root=paths.mirrors,
                manifest_path=manifest_path,
                sources_info=source_info,
                on_progress=lambda files, dirs, current_path: emit_hash_progress(
                    ".",
                    files,
                    dirs,
                    current_path,
                ),
            )
        atomic_write_text(state_path, safe_json_dump(state.to_dict()))
        _emit_sync_runtime_message(cfg, f"mirror-state: wrote {state_path}")
    except (OSError, RuntimeError, TypeError, ValueError):
        logger.warning("failed to write mirror state file %s", state_path)


async def sync(cfg: EngineConfig) -> SyncResult:
    logger.info("Starting sync run root=%s sources=%d", cfg.root, len(cfg.sources))
    paths = prepare_paths(Path(cfg.root), cfg)
    recorder = ManifestRecorder(root=paths.root, cfg=cfg)

    http_caches: dict[str, HttpCache] = {}
    manifest_path: Path | None = None

    try:
        if cfg.delete_http_caches and not cfg.dry_run:
            removed = delete_http_cache_files(paths.http_cache)
            recorder.record_http_cache_deleted(removed)

        http_caches = build_http_caches(
            sources=cfg.sources,
            cache_root=paths.http_cache,
            rate_root=paths.rate,
        )

        await run_http_phase(cfg=cfg, paths=paths, http_caches=http_caches, recorder=recorder)
        expected_mirror_dirs = await run_rsync_phase(cfg=cfg, paths=paths, recorder=recorder)

        if cfg.prune_orphan_mirrors and not cfg.dry_run:
            removed = prune_orphan_mirrors(paths.mirrors, expected_mirror_dirs)
            recorder.record_pruned_orphan_mirrors(removed)

        await _run_derived_tasks(cfg=cfg, paths=paths, recorder=recorder)

    finally:
        await _close_http_caches(http_caches)
        recorder.finish()
        manifest_path = await _write_manifest_outputs(cfg=cfg, paths=paths, recorder=recorder)
        _update_canonical_manifest(cfg=cfg, paths=paths, recorder=recorder)
        if manifest_path is not None:
            _emit_sync_runtime_message(cfg, "mirror-state: updating manifest-backed hash state...")
            _update_mirror_state(cfg=cfg, paths=paths, manifest_path=manifest_path)

    ok = len(recorder.manifest["errors"]) == 0
    return SyncResult(
        ok=ok,
        root=paths.root,
        manifest_path=manifest_path,
        manifest=recorder.manifest,
    )
