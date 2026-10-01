from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from efloud.json_types import json_mapping_or_none
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
    ProducerRef,
    ProvenanceEdge,
    RunId,
    SnapshotId,
    SourceId,
    SourceSnapshot,
    ValidationResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from efloud.json_types import JsonObject

_RUN_TERMINAL = frozenset({"succeeded", "partial", "failed", "cancelled"})
_OPERATION_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


class MemoryCatalog:  # ruff: ignore[too-many-public-methods] - complete semantic fake for the Catalog port.
    """Pure in-memory semantic catalog for fast storage-independent tests."""

    def __init__(self) -> None:
        """Initialize empty semantic evidence collections."""
        self._sources: dict[SourceId, SourceRecord] = {}
        self._runs: dict[RunId, RunRecord] = {}
        self._operations: dict[OperationId, OperationRecord] = {}
        self._contents: dict[ContentId, ContentRef] = {}
        self._observations: dict[ObservationId, ArtifactObservation] = {}
        self._absences: dict[ObservationId, ArtifactAbsence] = {}
        self._provenance: dict[ObservationId, list[ProvenanceEdge]] = {}
        self._validations: dict[tuple[ContentId, str, str], ValidationResult] = {}
        self._snapshots: dict[SnapshotId, SourceSnapshot] = {}
        self._datasets: dict[DatasetId, DatasetRecord] = {}

    def close(self) -> None:
        """Release no resources; provided for parity with durable catalog implementations."""

    def register_source(self, source_id: SourceId, definition: JsonObject) -> None:
        self._sources[source_id] = SourceRecord(source_id=source_id, definition=definition)

    def source(self, source_id: SourceId) -> SourceRecord | None:
        return self._sources.get(source_id)

    def sources(self) -> tuple[SourceRecord, ...]:
        return tuple(self._sources[key] for key in sorted(self._sources, key=str))

    def start_run(self, run_id: RunId, *, started_at: float, metadata: JsonObject) -> None:
        if run_id in self._runs:
            msg = f"Run already exists: {run_id}"
            raise ValueError(msg)
        self._runs[run_id] = RunRecord(run_id, started_at, None, "running", dict(metadata))

    def finish_run(self, run_id: RunId, *, finished_at: float, status: str) -> None:
        run = self._runs.get(run_id)
        if run is None:
            msg = f"Unknown run: {run_id}"
            raise KeyError(msg)
        if run.status != "running":
            msg = f"Run {run_id} cannot transition from {run.status!r}."
            raise ValueError(msg)
        if status not in _RUN_TERMINAL:
            msg = f"Invalid terminal run status: {status!r}"
            raise ValueError(msg)
        if any(operation.run_id == run_id and operation.status == "running" for operation in self._operations.values()):
            msg = f"Run {run_id} cannot finish while operations are still running."
            raise ValueError(msg)
        self._runs[run_id] = replace(run, finished_at=finished_at, status=status)

    def run(self, run_id: RunId) -> RunRecord | None:
        return self._runs.get(run_id)

    def recent_runs(self, *, limit: int = 50) -> tuple[RunRecord, ...]:
        ordered = sorted(self._runs.values(), key=lambda item: (item.started_at, str(item.run_id)), reverse=True)
        return tuple(ordered[: max(0, limit)])

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
    ) -> None:
        run = self._runs.get(run_id)
        if run is None:
            msg = f"Unknown run: {run_id}"
            raise KeyError(msg)
        if run.status != "running":
            msg = f"Cannot start operation {operation_id} in terminal run {run_id}."
            raise ValueError(msg)
        producer = json_mapping_or_none(parameters.get("producer"))
        if producer is None:
            msg = "Operation parameters require canonical producer metadata."
            raise ValueError(msg)
        ProducerRef.from_mapping(producer)
        if operation_id in self._operations:
            msg = f"Operation already exists: {operation_id}"
            raise ValueError(msg)
        self._operations[operation_id] = OperationRecord(
            operation_id=operation_id,
            run_id=run_id,
            source_id=source_id,
            kind=kind,
            subject=subject,
            started_at=started_at,
            finished_at=None,
            status="running",
            parameters=dict(parameters),
            details={},
        )

    def finish_operation(
        self,
        operation_id: OperationId,
        *,
        finished_at: float,
        status: str,
        details: JsonObject,
    ) -> None:
        operation = self._operations.get(operation_id)
        if operation is None:
            msg = f"Unknown operation: {operation_id}"
            raise KeyError(msg)
        if operation.status != "running":
            msg = f"Operation {operation_id} cannot transition from {operation.status!r}."
            raise ValueError(msg)
        if status not in _OPERATION_TERMINAL:
            msg = f"Invalid terminal operation status: {status!r}"
            raise ValueError(msg)
        self._operations[operation_id] = replace(
            operation,
            finished_at=finished_at,
            status=status,
            details=dict(details),
        )

    def operation(self, operation_id: OperationId) -> OperationRecord | None:
        return self._operations.get(operation_id)

    def operations_for_run(self, run_id: RunId) -> tuple[OperationRecord, ...]:
        return tuple(
            sorted(
                (operation for operation in self._operations.values() if operation.run_id == run_id),
                key=lambda item: (item.started_at, str(item.operation_id)),
            )
        )

    def operations_for_source(self, source_id: SourceId, *, limit: int = 50) -> tuple[OperationRecord, ...]:
        ordered = sorted(
            (operation for operation in self._operations.values() if operation.source_id == source_id),
            key=lambda item: (item.started_at, str(item.operation_id)),
            reverse=True,
        )
        return tuple(ordered[: max(0, limit)])

    def record_content(self, content: ContentRef) -> None:
        existing = self._contents.get(content.content_id)
        if existing is not None and (
            existing.byte_size != content.byte_size or existing.custody_key != content.custody_key
        ):
            msg = f"Conflicting content record for {content.content_id}"
            raise ValueError(msg)
        if existing is None:
            self._contents[content.content_id] = content

    def content(self, content_id: ContentId) -> ContentRef | None:
        return self._contents.get(content_id)

    def record_observation_bundle(
        self,
        *,
        content: ContentRef,
        observation: ArtifactObservation,
        provenance_edges: Iterable[ProvenanceEdge] = (),
    ) -> None:
        if observation.content_id != content.content_id:
            msg = "Observation content identity does not match its content record."
            raise ValueError(msg)
        self.record_content(content)
        if observation.observation_id in self._observations or observation.observation_id in self._absences:
            msg = f"Observation already exists: {observation.observation_id}"
            raise ValueError(msg)
        edges = tuple(provenance_edges)
        if any(edge.output_observation_id != observation.observation_id for edge in edges):
            msg = "Provenance output must match the recorded observation."
            raise ValueError(msg)
        self._observations[observation.observation_id] = observation
        self._provenance[observation.observation_id] = list(edges)

    def record_absence(self, absence: ArtifactAbsence) -> None:
        if absence.observation_id in self._observations or absence.observation_id in self._absences:
            msg = f"Observation already exists: {absence.observation_id}"
            raise ValueError(msg)
        self._absences[absence.observation_id] = absence

    def observation(self, observation_id: ObservationId) -> ArtifactObservation | None:
        return self._observations.get(observation_id)

    def observations_for(self, artifact_key: ArtifactKey) -> tuple[ArtifactObservation, ...]:
        return tuple(
            sorted(
                (
                    observation
                    for observation in self._observations.values()
                    if observation.artifact_key == artifact_key
                ),
                key=lambda item: (item.observed_at, str(item.observation_id)),
            )
        )

    def _latest_absence(self, artifact_key: ArtifactKey, *, before: float | None = None) -> ArtifactAbsence | None:
        candidates = [
            absence
            for absence in self._absences.values()
            if absence.artifact_key == artifact_key and (before is None or absence.observed_at <= before)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.observed_at, str(item.observation_id)))

    def latest_state(self, artifact_key: ArtifactKey, *, before: float | None = None) -> ArtifactState | None:
        observation = self.latest_observation(artifact_key, before=before)
        absence = self._latest_absence(artifact_key, before=before)
        if observation is None:
            return absence
        if absence is None:
            return observation
        observation_key = (observation.observed_at, str(observation.observation_id))
        absence_key = (absence.observed_at, str(absence.observation_id))
        return observation if observation_key >= absence_key else absence

    def latest_observation(
        self,
        artifact_key: ArtifactKey,
        *,
        before: float | None = None,
    ) -> ArtifactObservation | None:
        candidates = [
            observation
            for observation in self._observations.values()
            if observation.artifact_key == artifact_key and (before is None or observation.observed_at <= before)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.observed_at, str(item.observation_id)))

    def artifact_keys(self) -> tuple[ArtifactKey, ...]:
        keys = {observation.artifact_key for observation in self._observations.values()}
        keys.update(absence.artifact_key for absence in self._absences.values())
        return tuple(sorted(keys, key=str))

    def provenance_inputs(self, observation_id: ObservationId) -> tuple[ProvenanceEdge, ...]:
        return tuple(
            sorted(
                self._provenance.get(observation_id, ()),
                key=lambda edge: (str(edge.input_observation_id), edge.relationship),
            )
        )

    def record_validation(self, result: ValidationResult) -> None:
        key = (result.content_id, result.validator, result.validator_version)
        self._validations[key] = result

    def validation(
        self,
        content_id: ContentId,
        validator: str,
        validator_version: str,
    ) -> ValidationResult | None:
        return self._validations.get((content_id, validator, validator_version))

    def validations_for(self, content_id: ContentId) -> tuple[ValidationResult, ...]:
        return tuple(
            sorted(
                (result for result in self._validations.values() if result.content_id == content_id),
                key=lambda item: (item.validator, item.validator_version, item.checked_at),
            )
        )

    def record_source_snapshot(self, snapshot: SourceSnapshot) -> None:
        if snapshot.snapshot_id in self._snapshots:
            msg = f"Source snapshot already exists: {snapshot.snapshot_id}"
            raise ValueError(msg)
        self._snapshots[snapshot.snapshot_id] = snapshot

    def source_snapshot(self, snapshot_id: SnapshotId) -> SourceSnapshot | None:
        return self._snapshots.get(snapshot_id)

    def latest_source_snapshot(self, source_id: SourceId) -> SourceSnapshot | None:
        snapshots = self.source_snapshots_for(source_id, limit=1)
        return snapshots[0] if snapshots else None

    def source_snapshots_for(
        self,
        source_id: SourceId,
        *,
        limit: int | None = 50,
    ) -> tuple[SourceSnapshot, ...]:
        if limit is not None and limit < 0:
            msg = "limit must be nonnegative or None"
            raise ValueError(msg)
        ordered = sorted(
            (snapshot for snapshot in self._snapshots.values() if snapshot.source_id == source_id),
            key=lambda item: (item.observed_at, str(item.snapshot_id)),
            reverse=True,
        )
        return tuple(ordered if limit is None else ordered[:limit])

    def record_dataset(self, record: DatasetRecord) -> None:
        existing = self._datasets.get(record.dataset_id)
        if existing is None:
            self._datasets[record.dataset_id] = record
            return
        if existing.content_identity != record.content_identity or existing.members != record.members:
            msg = f"Conflicting dataset membership for {record.dataset_id}"
            raise ValueError(msg)
        merged = record.with_specifications(existing.specifications)
        self._datasets[record.dataset_id] = replace(merged, created_at=existing.created_at)

    def dataset(self, dataset_id: DatasetId) -> DatasetRecord | None:
        return self._datasets.get(dataset_id)


__all__ = ["MemoryCatalog"]
