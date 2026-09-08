from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.metadata_store import MaterializationRecord, OperationRecord, RunRecord, SourceRecord
    from efloud.repository_models import (
        ArtifactKey,
        ArtifactObservation,
        ArtifactState,
        ContentId,
        ContentRef,
        DatasetId,
        DatasetSpecification,
        ObservationId,
        RunId,
        SnapshotId,
        SourceId,
        SourceSnapshot,
        TreeEntry,
        TreeId,
        ValidationResult,
    )


class RepositoryView(Protocol):
    """Read-only semantic repository capability used by queries and datasets.

    Implementations may be backed by a mutable :class:`Repository` or by a
    physically read-only store. Consumers depend on repository semantics rather
    than concrete metadata/blob implementations.
    """

    root: Path

    def source(self, source_id: SourceId | str) -> SourceRecord | None: ...

    def sources(self) -> tuple[SourceRecord, ...]: ...

    def run(self, run_id: RunId | str) -> RunRecord | None: ...

    def recent_runs(self, *, limit: int = 50) -> tuple[RunRecord, ...]: ...

    def operation(self, operation_id: str) -> OperationRecord | None: ...

    def operations_for_run(self, run_id: RunId | str) -> tuple[OperationRecord, ...]: ...

    def operations_for_source(
        self,
        source_id: SourceId | str,
        *,
        limit: int = 50,
    ) -> tuple[OperationRecord, ...]: ...

    def materializations_for(self, content_id: ContentId | str) -> tuple[MaterializationRecord, ...]: ...

    def latest_state(
        self,
        artifact_key: ArtifactKey | str,
        *,
        before: float | None = None,
    ) -> ArtifactState | None: ...

    def observation(self, observation_id: ObservationId | str) -> ArtifactObservation | None: ...

    def observations_for(self, artifact_key: ArtifactKey | str) -> tuple[ArtifactObservation, ...]: ...

    def latest_observation(
        self,
        artifact_key: ArtifactKey | str,
        *,
        before: float | None = None,
    ) -> ArtifactObservation | None: ...

    def content(self, content_id: ContentId | str) -> ContentRef | None: ...

    def artifact_keys(self) -> tuple[ArtifactKey, ...]: ...

    def open_content(self, content_id: ContentId | str) -> BinaryIO: ...

    def contains_content(self, content_id: ContentId | str) -> bool: ...

    def verify_content(self, content_id: ContentId | str) -> bool: ...

    def validation(
        self,
        content_id: ContentId | str,
        validator: str,
        validator_version: str,
    ) -> ValidationResult | None: ...

    def validations_for(self, content_id: ContentId | str) -> tuple[ValidationResult, ...]: ...

    def tree_entries(self, tree_id: TreeId | str) -> tuple[TreeEntry, ...]: ...

    def source_snapshot(self, snapshot_id: SnapshotId | str) -> SourceSnapshot | None: ...

    def latest_source_snapshot(self, source_id: SourceId | str) -> SourceSnapshot | None: ...

    def source_snapshots_for(
        self,
        source_id: SourceId | str,
        *,
        limit: int = 50,
    ) -> tuple[SourceSnapshot, ...]: ...

    def dataset_specifications(
        self,
        dataset_id: DatasetId | str,
    ) -> tuple[DatasetSpecification, ...]: ...


__all__ = ["RepositoryView"]
