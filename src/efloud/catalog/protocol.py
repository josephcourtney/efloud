from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from efloud.json_types import JsonObject
    from efloud.metadata_store import DatasetRecord, OperationRecord, RunRecord, SourceRecord
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
        ValidationResult,
    )


class Catalog(Protocol):  # ruff: ignore[too-many-public-methods] - one internal port for durable semantic evidence.
    """Durable semantic metadata, excluding physical content, trees, and materialized paths."""

    def close(self) -> None: ...

    def register_source(self, source_id: SourceId, definition: JsonObject) -> None: ...

    def source(self, source_id: SourceId) -> SourceRecord | None: ...

    def sources(self) -> tuple[SourceRecord, ...]: ...

    def start_run(self, run_id: RunId, *, started_at: float, metadata: JsonObject) -> None: ...

    def finish_run(self, run_id: RunId, *, finished_at: float, status: str) -> None: ...

    def run(self, run_id: RunId) -> RunRecord | None: ...

    def recent_runs(self, *, limit: int = 50) -> tuple[RunRecord, ...]: ...

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

    def operation(self, operation_id: OperationId) -> OperationRecord | None: ...

    def operations_for_run(self, run_id: RunId) -> tuple[OperationRecord, ...]: ...

    def operations_for_source(self, source_id: SourceId, *, limit: int = 50) -> tuple[OperationRecord, ...]: ...

    def record_content(self, content: ContentRef) -> None: ...

    def content(self, content_id: ContentId) -> ContentRef | None: ...

    def record_observation_bundle(
        self,
        *,
        content: ContentRef,
        observation: ArtifactObservation,
        provenance_edges: Iterable[ProvenanceEdge] = (),
    ) -> None: ...

    def record_absence(self, absence: ArtifactAbsence) -> None: ...

    def observation(self, observation_id: ObservationId) -> ArtifactObservation | None: ...

    def observations_for(self, artifact_key: ArtifactKey) -> tuple[ArtifactObservation, ...]: ...

    def latest_state(self, artifact_key: ArtifactKey, *, before: float | None = None) -> ArtifactState | None: ...

    def latest_observation(
        self,
        artifact_key: ArtifactKey,
        *,
        before: float | None = None,
    ) -> ArtifactObservation | None: ...

    def artifact_keys(self) -> tuple[ArtifactKey, ...]: ...

    def provenance_inputs(self, observation_id: ObservationId) -> tuple[ProvenanceEdge, ...]: ...

    def record_validation(self, result: ValidationResult) -> None: ...

    def validation(
        self,
        content_id: ContentId,
        validator: str,
        validator_version: str,
    ) -> ValidationResult | None: ...

    def validations_for(self, content_id: ContentId) -> tuple[ValidationResult, ...]: ...

    def record_source_snapshot(self, snapshot: SourceSnapshot) -> None: ...

    def source_snapshot(self, snapshot_id: SnapshotId) -> SourceSnapshot | None: ...

    def latest_source_snapshot(self, source_id: SourceId) -> SourceSnapshot | None: ...

    def source_snapshots_for(
        self,
        source_id: SourceId,
        *,
        limit: int | None = 50,
    ) -> tuple[SourceSnapshot, ...]: ...

    def record_dataset(self, record: DatasetRecord) -> None: ...

    def dataset(self, dataset_id: DatasetId) -> DatasetRecord | None: ...


__all__ = ["Catalog"]
