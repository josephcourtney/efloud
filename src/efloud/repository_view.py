from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

    from efloud.metadata_store import SourceRecord
    from efloud.repository_capabilities import ExtensionReader
    from efloud.repository_models import (
        ArtifactKey,
        ArtifactObservation,
        ArtifactState,
        ContentId,
        ContentRef,
        ObservationId,
        SnapshotId,
        SourceId,
        SourceSnapshot,
        TreeEntry,
        TreeId,
        ValidationResult,
    )


@dataclass(frozen=True, slots=True)
class ExtensionRepositoryView:
    """Read-only extension capability over an already-open repository.

    This is a capability facade rather than a second repository connection: it
    exposes only the ExtensionReader vocabulary and therefore cannot be used by
    adapters or collection/derived extensions for authoritative mutation.
    """

    _repository: ExtensionReader

    @property
    def root(self) -> Path:
        return self._repository.root

    def latest_state(
        self,
        artifact_key: ArtifactKey | str,
        *,
        before: float | None = None,
    ) -> ArtifactState | None:
        return self._repository.latest_state(artifact_key, before=before)

    def observation(self, observation_id: ObservationId | str) -> ArtifactObservation | None:
        return self._repository.observation(observation_id)

    def observations_for(self, artifact_key: ArtifactKey | str) -> tuple[ArtifactObservation, ...]:
        return self._repository.observations_for(artifact_key)

    def latest_observation(
        self,
        artifact_key: ArtifactKey | str,
        *,
        before: float | None = None,
    ) -> ArtifactObservation | None:
        return self._repository.latest_observation(artifact_key, before=before)

    def artifact_keys(self) -> tuple[ArtifactKey, ...]:
        return self._repository.artifact_keys()

    def content(self, content_id: ContentId | str) -> ContentRef | None:
        return self._repository.content(content_id)

    def open_content(self, content_id: ContentId | str) -> BinaryIO:
        return self._repository.open_content(content_id)

    def contains_content(self, content_id: ContentId | str) -> bool:
        return self._repository.contains_content(content_id)

    def verify_content(self, content_id: ContentId | str) -> bool:
        return self._repository.verify_content(content_id)

    def source(self, source_id: SourceId | str) -> SourceRecord | None:
        return self._repository.source(source_id)

    def sources(self) -> tuple[SourceRecord, ...]:
        return self._repository.sources()

    def tree_entries(self, tree_id: TreeId | str) -> tuple[TreeEntry, ...]:
        return self._repository.tree_entries(tree_id)

    def source_snapshot(self, snapshot_id: SnapshotId | str) -> SourceSnapshot | None:
        return self._repository.source_snapshot(snapshot_id)

    def latest_source_snapshot(self, source_id: SourceId | str) -> SourceSnapshot | None:
        return self._repository.latest_source_snapshot(source_id)

    def source_snapshots_for(
        self,
        source_id: SourceId | str,
        *,
        limit: int | None = 50,
    ) -> tuple[SourceSnapshot, ...]:
        return self._repository.source_snapshots_for(source_id, limit=limit)

    def validation(
        self,
        content_id: ContentId | str,
        validator: str,
        validator_version: str,
    ) -> ValidationResult | None:
        return self._repository.validation(content_id, validator, validator_version)

    def validations_for(self, content_id: ContentId | str) -> tuple[ValidationResult, ...]:
        return self._repository.validations_for(content_id)


__all__ = ["ExtensionRepositoryView"]
