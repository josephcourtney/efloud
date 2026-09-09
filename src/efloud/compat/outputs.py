"""Explicit compatibility projections attached to canonical engine results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.models import NormalizedManifest, SyncResult
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
