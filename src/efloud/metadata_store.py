from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from efloud.json_types import JsonObject
from efloud.repository_models import (
    ArtifactAbsence,
    ArtifactKey,
    ArtifactObservation,
    ArtifactState,
    ContentId,
    ContentRef,
    DatasetId,
    ObservationId,
    OperationId,
    ProvenanceEdge,
    RunId,
    SnapshotId,
    SourceId,
    SourceSnapshot,
    TreeEntry,
    TreeId,
    ValidationResult,
)


@dataclass(frozen=True, slots=True)
class DatasetMemberRecord:
    artifact_key: ArtifactKey
    observation_id: ObservationId
    content_id: ContentId
    role: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    dataset_id: DatasetId
    content_identity: str
    created_at: float
    definition: JsonObject
    metadata: JsonObject
    members: tuple[DatasetMemberRecord, ...]


class MetadataStore(Protocol):
    def close(self) -> None: ...

    def register_source(self, source_id: SourceId, definition: JsonObject) -> None: ...

    def start_run(
        self,
        run_id: RunId,
        *,
        started_at: float,
        metadata: JsonObject,
    ) -> None: ...

    def finish_run(self, run_id: RunId, *, finished_at: float, status: str) -> None: ...

    def start_operation(
        self,
        operation_id: OperationId,
        *,
        run_id: RunId,
        source_id: SourceId | None,
        kind: str,
        subject: str,
        started_at: float,
        parameters: JsonObject,
    ) -> None: ...

    def finish_operation(
        self,
        operation_id: OperationId,
        *,
        finished_at: float,
        status: str,
        details: JsonObject,
    ) -> None: ...

    def record_observation_bundle(
        self,
        *,
        content: ContentRef,
        observation: ArtifactObservation,
        provenance_edges: Iterable[ProvenanceEdge] = (),
    ) -> None: ...

    def record_absence(self, absence: ArtifactAbsence) -> None: ...

    def record_materialization(
        self,
        *,
        content_id: ContentId,
        kind: str,
        path: str,
        metadata: JsonObject,
    ) -> None: ...

    def record_validation(self, result: ValidationResult) -> None: ...

    def observation(self, observation_id: ObservationId) -> ArtifactObservation | None: ...

    def observations_for(self, artifact_key: ArtifactKey) -> tuple[ArtifactObservation, ...]: ...

    def latest_state(
        self,
        artifact_key: ArtifactKey,
        *,
        before: float | None = None,
    ) -> ArtifactState | None: ...

    def latest_observation(
        self,
        artifact_key: ArtifactKey,
        *,
        before: float | None = None,
    ) -> ArtifactObservation | None: ...

    def content(self, content_id: ContentId) -> ContentRef | None: ...

    def artifact_keys(self) -> tuple[ArtifactKey, ...]: ...

    def record_tree(self, tree_id: TreeId, entries: Iterable[TreeEntry], *, created_at: float) -> None: ...

    def tree_entries(self, tree_id: TreeId) -> tuple[TreeEntry, ...]: ...

    def record_source_snapshot(self, snapshot: SourceSnapshot) -> None: ...

    def source_snapshot(self, snapshot_id: SnapshotId) -> SourceSnapshot | None: ...

    def latest_source_snapshot(self, source_id: SourceId) -> SourceSnapshot | None: ...

    def record_dataset(self, record: DatasetRecord) -> None: ...

    def dataset(self, dataset_id: DatasetId) -> DatasetRecord | None: ...


__all__ = [
    "DatasetMemberRecord",
    "DatasetRecord",
    "MetadataStore",
]
