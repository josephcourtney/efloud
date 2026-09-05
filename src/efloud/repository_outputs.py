from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.fs import atomic_write_text, safe_json_dump
from efloud.repository_compat import repository_manifest
from efloud.repository_state import write_repository_mirror_state

if TYPE_CHECKING:
    from efloud.models import EngineConfig, NormalizedManifest
    from efloud.repository import Repository
    from efloud.repository_models import RunId
    from efloud.state import MirrorState


@dataclass(frozen=True, slots=True)
class RepositoryOutputs:
    manifest: NormalizedManifest
    canonical_manifest_path: Path
    timestamped_manifest_path: Path
    requested_manifest_path: Path | None
    mirror_state: MirrorState | None
    mirror_state_path: Path | None


def _timestamped_manifest_path(cfg: EngineConfig, *, timestamp: float) -> Path:
    root = Path(cfg.root)
    base = Path(cfg.manifest_filename)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(timestamp))
    return root / cfg.log_dir / f"{base.stem}-{stamp}{base.suffix or ''}"


def _write_manifest(path: Path, manifest: NormalizedManifest) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, safe_json_dump(manifest))
    return path.resolve()


def publish_repository_outputs(
    repository: Repository,
    *,
    cfg: EngineConfig,
    run_id: RunId,
) -> RepositoryOutputs:
    """Publish all compatibility state as projections of authoritative repository state."""
    manifest = repository_manifest(repository, cfg=cfg, run_id=run_id)
    run = repository.metadata.run(run_id)
    output_time = (
        run.finished_at
        if run is not None and run.finished_at is not None
        else run.started_at if run is not None else time.time()
    )

    canonical_path = _write_manifest(
        Path(cfg.root) / cfg.log_dir / cfg.manifest_filename,
        manifest,
    )
    timestamped_path = _write_manifest(
        _timestamped_manifest_path(cfg, timestamp=output_time),
        manifest,
    )
    requested_path: Path | None = None
    if cfg.manifest_path is not None:
        target = Path(cfg.manifest_path)
        if target.resolve(strict=False) not in {
            canonical_path,
            timestamped_path,
        }:
            requested_path = _write_manifest(target, manifest)
        else:
            requested_path = target.resolve(strict=False)

    mirror_state, mirror_state_path = write_repository_mirror_state(
        repository,
        cfg=cfg,
        manifest_path=canonical_path,
        generated_at=output_time,
    )
    return RepositoryOutputs(
        manifest=manifest,
        canonical_manifest_path=canonical_path,
        timestamped_manifest_path=timestamped_path,
        requested_manifest_path=requested_path,
        mirror_state=mirror_state,
        mirror_state_path=mirror_state_path,
    )


__all__ = ["RepositoryOutputs", "publish_repository_outputs"]
