"""Explicit compatibility projections attached to canonical engine results."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.models import SyncResult
from efloud.repository_compat import repository_manifest
from efloud.repository_outputs import publish_repository_outputs

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.engine import EngineSyncResult
    from efloud.models import EngineConfig, NormalizedManifest
    from efloud.repository import Repository
    from efloud.state import MirrorState


@dataclass(frozen=True, slots=True)
class CompatibilityOutputs:
    sync_result: SyncResult
    repository_manifest: NormalizedManifest | None = None
    repository_manifest_path: Path | None = None
    repository_mirror_state: MirrorState | None = None
    repository_mirror_state_path: Path | None = None

    @property
    def manifest(self) -> NormalizedManifest:
        return self.repository_manifest or self.sync_result.manifest

    @property
    def legacy_manifest(self) -> NormalizedManifest:
        return self.sync_result.manifest


def project_execution(
    repository: Repository, *, config: EngineConfig, result: EngineSyncResult
) -> CompatibilityOutputs:
    """Explicitly publish legacy outputs after canonical execution has finished."""
    current_manifest = repository_manifest(
        repository,
        cfg=config,
        run_id=result.repository_run_id,
    )
    manifest_path: Path | None = None
    mirror_state: MirrorState | None = None
    mirror_state_path: Path | None = None
    if result.repository_run_id is not None and not result.plan.request.dry_run:
        with contextlib.suppress(OSError):
            outputs = publish_repository_outputs(
                repository,
                cfg=config,
                run_id=result.repository_run_id,
            )
            current_manifest = outputs.manifest
            manifest_path = outputs.canonical_manifest_path
            mirror_state = outputs.mirror_state
            mirror_state_path = outputs.mirror_state_path

    sync_result = SyncResult(
        ok=result.ok,
        root=config.root,
        manifest_path=manifest_path,
        manifest=current_manifest,
    )
    return CompatibilityOutputs(
        sync_result=sync_result,
        repository_manifest=current_manifest,
        repository_manifest_path=manifest_path,
        repository_mirror_state=mirror_state,
        repository_mirror_state_path=mirror_state_path,
    )
