from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from efloud.datasets import DatasetDefinition, ImmutableDataset
    from efloud.derivation import DerivationKey
    from efloud.inventory import AbsenceEvidence
    from efloud.json_types import JsonObject
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
        OperationId,
        ProducerRef,
        ProvenanceEdge,
        RunId,
        SnapshotId,
        SourceId,
        SourceSnapshot,
        TreeEntry,
        TreeId,
        ValidationResult,
    )


class ArtifactReader(Protocol):
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

    def artifact_keys(self) -> tuple[ArtifactKey, ...]: ...


class ContentReader(Protocol):
    def content(self, content_id: ContentId | str) -> ContentRef | None: ...

    def open_content(self, content_id: ContentId | str) -> BinaryIO: ...

    def contains_content(self, content_id: ContentId | str) -> bool: ...

    def verify_content(self, content_id: ContentId | str) -> bool: ...


class SourceReader(Protocol):
    def source(self, source_id: SourceId | str) -> SourceRecord | None: ...

    def sources(self) -> tuple[SourceRecord, ...]: ...

    def tree_entries(self, tree_id: TreeId | str) -> tuple[TreeEntry, ...]: ...

    def source_snapshot(self, snapshot_id: SnapshotId | str) -> SourceSnapshot | None: ...

    def latest_source_snapshot(self, source_id: SourceId | str) -> SourceSnapshot | None: ...

    def source_snapshots_for(
        self,
        source_id: SourceId | str,
        *,
        limit: int | None = 50,
    ) -> tuple[SourceSnapshot, ...]: ...


class RunReader(Protocol):
    def run(self, run_id: RunId | str) -> RunRecord | None: ...

    def recent_runs(self, *, limit: int = 50) -> tuple[RunRecord, ...]: ...

    def operation(self, operation_id: OperationId | str) -> OperationRecord | None: ...

    def operations_for_run(self, run_id: RunId | str) -> tuple[OperationRecord, ...]: ...

    def operations_for_source(
        self,
        source_id: SourceId | str,
        *,
        limit: int = 50,
    ) -> tuple[OperationRecord, ...]: ...


class ProvenanceReader(Protocol):
    def provenance_inputs(self, observation_id: ObservationId | str) -> tuple[ProvenanceEdge, ...]: ...

    def materializations_for(self, content_id: ContentId | str) -> tuple[MaterializationRecord, ...]: ...


class ValidationReader(Protocol):
    def validation(
        self,
        content_id: ContentId | str,
        validator: str,
        validator_version: str,
    ) -> ValidationResult | None: ...

    def validations_for(self, content_id: ContentId | str) -> tuple[ValidationResult, ...]: ...


class DatasetReader(Protocol):
    def dataset(self, dataset_id: DatasetId | str) -> ImmutableDataset: ...

    def dataset_specifications(
        self,
        dataset_id: DatasetId | str,
    ) -> tuple[DatasetSpecification, ...]: ...


class ExtensionReader(ArtifactReader, ContentReader, SourceReader, ValidationReader, Protocol):
    """Read capability available to adapters and derived/collection extensions."""

    root: Path


class DatasetRepository(ArtifactReader, ContentReader, SourceReader, ValidationReader, Protocol):
    """Reads required by dataset selection, constraints, verification, and export."""

    root: Path


class QueryRepository(
    ArtifactReader,
    ContentReader,
    SourceReader,
    RunReader,
    ProvenanceReader,
    ValidationReader,
    DatasetReader,
    Protocol,
):
    """Typed repository evidence consumed by presentation/query services."""

    root: Path


class MaintenanceRepository(DatasetRepository, DatasetReader, Protocol):
    """Semantic reads used while auditing repository metadata and content."""


class ValidationRepository(ContentReader, ValidationReader, Protocol):
    """Content reads plus the sole validation-evidence mutation."""

    def record_validation(self, result: ValidationResult) -> None: ...


class RepositoryWriter(
    ExtensionReader,
    RunReader,
    ProvenanceReader,
    DatasetReader,
    Protocol,
):
    """Internal authoritative mutation capability used only by execution services."""

    root: Path

    def register_source(self, source_id: SourceId | str, definition: JsonObject) -> SourceId: ...

    def start_run(
        self,
        *,
        source_ids: Iterable[SourceId | str] = (),
        started_at: float | None = None,
        metadata: JsonObject | None = None,
    ) -> RunId: ...

    def finish_run(
        self,
        run_id: RunId,
        *,
        status: str,
        finished_at: float | None = None,
    ) -> None: ...

    def start_operation(
        self,
        *,
        run_id: RunId,
        kind: str,
        subject: str,
        source_id: SourceId | str | None = None,
        started_at: float | None = None,
        parameters: JsonObject | None = None,
        producer: ProducerRef | None = None,
    ) -> OperationId: ...

    def finish_operation(
        self,
        operation_id: OperationId,
        *,
        status: str,
        finished_at: float | None = None,
        details: JsonObject | None = None,
    ) -> None: ...

    def store_path_content(self, path: Path, *, media_type: str | None = None) -> ContentRef: ...

    def ingest_bytes(
        self,
        artifact_key: ArtifactKey | str,
        data: bytes,
        *,
        run_id: RunId,
        operation_id: OperationId,
        source_id: SourceId | str | None = None,
        observed_at: float | None = None,
        source_path: str | None = None,
        upstream_locator: str | None = None,
        upstream_modified_at: float | None = None,
        upstream_version: str | None = None,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
        inputs: Iterable[ObservationId] = (),
    ) -> ArtifactObservation: ...

    def ingest_path(
        self,
        artifact_key: ArtifactKey | str,
        path: Path,
        *,
        run_id: RunId,
        operation_id: OperationId,
        source_id: SourceId | str | None = None,
        observed_at: float | None = None,
        source_path: str | None = None,
        upstream_locator: str | None = None,
        upstream_modified_at: float | None = None,
        upstream_version: str | None = None,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
        inputs: Iterable[ObservationId] = (),
        materialization_kind: str | None = None,
    ) -> ArtifactObservation: ...

    def observe_content(
        self,
        artifact_key: ArtifactKey | str,
        content_id: ContentId | str,
        *,
        run_id: RunId,
        operation_id: OperationId,
        source_id: SourceId | str | None = None,
        observed_at: float | None = None,
        source_path: str | None = None,
        upstream_locator: str | None = None,
        upstream_modified_at: float | None = None,
        upstream_version: str | None = None,
        metadata: JsonObject | None = None,
        inputs: Iterable[ObservationId] = (),
        materialization_kind: str | None = None,
        materialization_path: Path | None = None,
    ) -> ArtifactObservation: ...

    def record_absence(
        self,
        artifact_key: ArtifactKey | str,
        *,
        evidence: AbsenceEvidence,
        run_id: RunId,
        operation_id: OperationId,
        source_path: str | None = None,
        upstream_locator: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactState: ...

    def record_validation(self, result: ValidationResult) -> None: ...

    def record_tree_snapshot(
        self,
        *,
        source_id: SourceId | str,
        run_id: RunId,
        entries: Iterable[TreeEntry],
        complete: bool,
        scope: Iterable[str] = (),
        observed_at: float | None = None,
        evidence: JsonObject | None = None,
    ) -> SourceSnapshot: ...

    def record_source_snapshot(
        self,
        *,
        source_id: SourceId | str,
        run_id: RunId,
        complete: bool,
        scope: Iterable[str] = (),
        observed_at: float | None = None,
        evidence: JsonObject | None = None,
    ) -> SourceSnapshot: ...

    def reusable_derived_content(
        self,
        derivation_key: DerivationKey | str,
        artifact_key: ArtifactKey | str,
    ) -> ContentId | None: ...

    def record_derived_path(
        self,
        artifact_key: ArtifactKey | str,
        path: Path,
        *,
        derivation_key: DerivationKey | str | None,
        run_id: RunId,
        operation_id: OperationId,
        inputs: Iterable[ArtifactObservation],
        observed_at: float | None = None,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
        materialization_kind: str | None = None,
    ) -> ArtifactObservation: ...

    def record_derived_bytes(
        self,
        artifact_key: ArtifactKey | str,
        data: bytes,
        *,
        derivation_key: DerivationKey | str | None,
        run_id: RunId,
        operation_id: OperationId,
        inputs: Iterable[ArtifactObservation],
        observed_at: float | None = None,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactObservation: ...

    def resolve_dataset(
        self,
        definition: DatasetDefinition,
        *,
        created_at: float | None = None,
    ) -> ImmutableDataset: ...


__all__ = [
    "ArtifactReader",
    "ContentReader",
    "DatasetReader",
    "DatasetRepository",
    "ExtensionReader",
    "MaintenanceRepository",
    "ProvenanceReader",
    "QueryRepository",
    "RepositoryWriter",
    "RunReader",
    "SourceReader",
    "ValidationReader",
    "ValidationRepository",
]
