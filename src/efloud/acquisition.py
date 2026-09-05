from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import httpx

from efloud.fs import delete_http_cache_files, prune_orphan_mirrors
from efloud.json_types import copy_json_mapping, json_mapping_or_none
from efloud.models import SyncResult
from efloud.sync import (
    ManifestRecorder,
    SyncPaths,
    build_http_caches,
    prepare_paths,
    run_http_phase,
    run_rsync_phase,
)

if TYPE_CHECKING:
    from efloud.models import EngineConfig
    from efloud.transport.http import HttpCache


async def _run_derived_phase(
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
        except (OSError, RuntimeError, TypeError, ValueError, httpx.HTTPError) as exc:
            recorder.error(
                phase="derived",
                error=f"{type(exc).__name__}: {exc}",
                name=task.name,
            )
            continue
        mapping = json_mapping_or_none(payload)
        recorder.record_derived(
            name=task.name,
            payload=copy_json_mapping(mapping) if mapping is not None else {},
        )


async def _run_acquisition_phases(
    *,
    cfg: EngineConfig,
    paths: SyncPaths,
    recorder: ManifestRecorder,
    http_caches: dict[str, HttpCache],
) -> None:
    if cfg.delete_http_caches and not cfg.dry_run:
        recorder.record_http_cache_deleted(delete_http_cache_files(paths.http_cache))

    http_caches.update(
        build_http_caches(
            sources=cfg.sources,
            cache_root=paths.http_cache,
            rate_root=paths.rate,
        )
    )
    await run_http_phase(cfg=cfg, paths=paths, http_caches=http_caches, recorder=recorder)
    expected_mirror_dirs = await run_rsync_phase(cfg=cfg, paths=paths, recorder=recorder)

    if cfg.prune_orphan_mirrors and not cfg.dry_run:
        recorder.record_pruned_orphan_mirrors(prune_orphan_mirrors(paths.mirrors, expected_mirror_dirs))

    await _run_derived_phase(cfg=cfg, paths=paths, recorder=recorder)


async def _close_http_caches(http_caches: dict[str, HttpCache]) -> None:
    for cache in http_caches.values():
        with contextlib.suppress(OSError, RuntimeError):
            await cache.aclose()


async def acquire(cfg: EngineConfig) -> SyncResult:
    """Run acquisition and return transient evidence without publishing state files.

    This is the Phase 10 compatibility seam. The legacy transport/fanout machinery
    still produces the in-memory result consumed by ``RepositorySyncRecorder``, but
    authoritative persistence is left to the repository and its serializers.
    """
    paths = prepare_paths(cfg.root, cfg)
    recorder = ManifestRecorder(root=paths.root, cfg=cfg)
    http_caches: dict[str, HttpCache] = {}

    try:
        await _run_acquisition_phases(
            cfg=cfg,
            paths=paths,
            recorder=recorder,
            http_caches=http_caches,
        )
    finally:
        await _close_http_caches(http_caches)
        recorder.finish()

    return SyncResult(
        ok=len(recorder.manifest["errors"]) == 0,
        root=paths.root,
        manifest_path=None,
        manifest=recorder.manifest,
    )


__all__ = ["acquire"]
