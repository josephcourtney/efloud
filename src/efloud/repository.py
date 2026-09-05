from __future__ import annotations

import time
from typing import TYPE_CHECKING, BinaryIO, Self

from efloud.blob_store import BlobStore, FilesystemBlobStore
from efloud.datasets import DatasetDefinition, DatasetManifest, ImmutableDataset, resolve_dataset
from efloud.derivation import DerivationKey
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
    TreeEntry,
    TreeId,
    ValidationResult,
    absence_id_for,
    observation_id_for,
    operation_id_for,
    run_id_for,
    stable_id,
)
from efloud.sqlite_metadata import SQLiteMetadataStore

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path
    from types import TracebackType

    from efloud.json_types import JsonObject
    from efloud.metadata_store import MetadataStore, OperationRecord

_RUN_TERMINAL = frozenset({"succeeded", "partial", "failed", "cancelled"})
_OPERATION_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def _canonical_terminal_status(status: str, *, operation: bool) -> str:
    if operation and status == "partial":
        normalized = "failed"
    else:
        normalized = "succeeded" if status == "success" else status
    allowed = _OPERATION_TERMINAL if operation else _RUN_TERMINAL
    if normalized not in allowed:
        kind = "operation" if operation else "run"
        msg = f"Invalid terminal {kind} status: {status!r}"
        raise ValueError(msg)
    return normalized


def _default_producer(kind: str) -> ProducerRef:
    normalized = kind.strip().lower().replace("_", "-") or "operation"
    return ProducerRef(f"efloud:{normalized}", "1")


class Repository:  # ruff: ignore[too-many-public-methods]
    def __init__(
        self,
        root: Path,
        *,
        metadata_store: MetadataStore | None = None,
        blob_store: BlobStore | None = None,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata = metadata_store or SQLiteMetadataStore(self.root / "metadata.sqlite")
        self.blobs = blob_store or FilesystemBlobStore(self.root / "objects")

    def __enter__(self) -> Self:
        """Return this repository for context-manager use."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close repository resources when leaving a context manager."""
        self.close()

    def close(self) -> None:
        self.metadata.close()

    def register_source(self, source_id: SourceId | str, definition: JsonObject) -> SourceId:
        normalized = SourceId(str(source_id))
        self.metadata.register_source(normalized, definition)
        return normalized

    def start_run(
        self,
        *,
        source_ids: Iterable[SourceId | str] = (),
        started_at: float | None = None,
        metadata: JsonObject | None = None,
    ) -> RunId:
        started = time.time() if started_at is None else started_at
        normalized_source_ids = tuple(sorted(str(source_id) for source_id in source_ids))
        run_id = run_id_for(
            root=self.root.as_posix(),
            started_at=started,
            source_ids=normalized_source_ids,
        )
        self.metadata.start_run(run_id, started_at=started, metadata=metadata or {})
        return run_id

    def finish_run(self, run_id: RunId, *, status: str, finished_at: float | None = None) -> None:
        run = self.metadata.run(run_id)
        if run is None:
            msg = f"Unknown run: {run_id}"
            raise KeyError(msg)
        if run.status != "running":
            msg = f"Run {run_id} cannot transition from {run.status!r}."
            raise ValueError(msg)
        running_operations = [
            operation
            for operation in self.metadata.operations_for_run(run_id)
            if operation.status == "running"
        ]
        if running_operations:
            msg = f"Run {run_id} cannot finish while operations are still running."
            raise ValueError(msg)
        self.metadata.finish_run(
            run_id,
            finished_at=time.time() if finished_at is None else finished_at,
            status=_canonical_terminal_status(status, operation=False),
        )

    def _operation_record(self, operation_id: OperationId) -> OperationRecord | None:
        for run in self.metadata.recent_runs(limit=100_000):
            for operation in self.metadata.operations_for_run(run.run_id):
                if operation.operation_id == operation_id:
                    return operation
        return None

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
    ) -> OperationId:
        run = self.metadata.run(run_id)
        if run is None:
            msg = f"Unknown run: {run_id}"
            raise KeyError(msg)
        if run.status != "running":
            msg = f"Cannot start an operation in terminal run {run_id}."
            raise ValueError(msg)
        operation_id = operation_id_for(run_id=run_id, kind=kind, subject=subject)
        normalized_source_id = SourceId(str(source_id)) if source_id is not None else None
        operation_parameters: JsonObject = dict(parameters or {})
        operation_parameters["producer"] = (producer or _default_producer(kind)).to_dict()
        self.metadata.start_operation(
            operation_id,
            run_id=run_id,
            source_id=normalized_source_id,
            kind=kind,
            subject=subject,
            started_at=time.time() if started_at is None else started_at,
            parameters=operation_parameters,
        )
        return operation_id

    def finish_operation(
        self,
        operation_id: OperationId,
        *,
        status: str,
        finished_at: float | None = None,
        details: JsonObject | None = None,
    ) -> None:
        operation = self._operation_record(operation_id)
        if operation is None:
            msg = f"Unknown operation: {operation_id}"
            raise KeyError(msg)
        if operation.status != "running":
            msg = f"Operation {operation_id} cannot transition from {operation.status!r}."
            raise ValueError(msg)
        self.metadata.finish_operation(
            operation_id,
            finished_at=time.time() if finished_at is None else finished_at,
            status=_canonical_terminal_status(status, operation=True),
            details=details or {},
        )

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
    ) -> ArtifactObservation:
        content = self.blobs.put_bytes(data, media_type=media_type)
        return self._record_content_observation(
            artifact_key=ArtifactKey(str(artifact_key)),
            content=content,
            run_id=run_id,
            operation_id=operation_id,
            source_id=SourceId(str(source_id)) if source_id is not None else None,
            observed_at=time.time() if observed_at is None else observed_at,
            source_path=source_path,
            upstream_locator=upstream_locator,
            upstream_modified_at=upstream_modified_at,
            upstream_version=upstream_version,
            media_type=media_type,
            metadata=metadata or {},
            inputs=inputs,
        )

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
    ) -> ArtifactObservation:
        content = self.blobs.put_path(path, media_type=media_type)
        observation = self._record_content_observation(
            artifact_key=ArtifactKey(str(artifact_key)),
            content=content,
            run_id=run_id,
            operation_id=operation_id,
            source_id=SourceId(str(source_id)) if source_id is not None else None,
            observed_at=time.time() if observed_at is None else observed_at,
            source_path=source_path,
            upstream_locator=upstream_locator,
            upstream_modified_at=upstream_modified_at,
            upstream_version=upstream_version,
            media_type=media_type,
            metadata=metadata or {},
            inputs=inputs,
        )
        if materialization_kind is not None:
            self.metadata.record_materialization(
                content_id=content.content_id,
                kind=materialization_kind,
                path=path.resolve().as_posix(),
                metadata={},
            )
        return observation

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
    ) -> ArtifactObservation:
        normalized_content_id = ContentId(str(content_id))
        content = self.metadata.content(normalized_content_id)
        if content is None:
            msg = f"Unknown repository content: {content_id}"
            raise KeyError(msg)
        observation = self._record_content_observation(
            artifact_key=ArtifactKey(str(artifact_key)),
            content=content,
            run_id=run_id,
            operation_id=operation_id,
            source_id=SourceId(str(source_id)) if source_id is not None else None,
            observed_at=time.time() if observed_at is None else observed_at,
            source_path=source_path,
            upstream_locator=upstream_locator,
            upstream_modified_at=upstream_modified_at,
            upstream_version=upstream_version,
            media_type=content.media_type,
            metadata=metadata or {},
            inputs=inputs,
        )
        if materialization_kind is not None and materialization_path is not None:
            self.metadata.record_materialization(
                content_id=content.content_id,
                kind=materialization_kind,
                path=materialization_path.resolve().as_posix(),
                metadata={},
            )
        return observation

    def reusable_derived_content(
        self,
        derivation_key: DerivationKey | str,
        artifact_key: ArtifactKey | str,
    ) -> ContentId | None:
        """Return prior deterministic output content for an identical derivation."""
        wanted = str(derivation_key)
        for observation in reversed(self.observations_for(artifact_key)):
            if observation.metadata.get("derivation_key") == wanted:
                return observation.content_id
        return None

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
    ) -> ArtifactObservation:
        """Record a derived file, reusing deterministic output content when possible."""
        input_observations = tuple(inputs)
        input_ids = tuple(observation.observation_id for observation in input_observations)
        payload: JsonObject = {**(metadata or {}), "derived_artifact": True}
        if derivation_key is not None:
            payload["derivation_key"] = str(derivation_key)
            reusable = self.reusable_derived_content(derivation_key, artifact_key)
            if reusable is not None:
                payload["derivation_reused"] = True
                return self.observe_content(
                    artifact_key,
                    reusable,
                    run_id=run_id,
                    operation_id=operation_id,
                    observed_at=observed_at,
                    metadata=payload,
                    inputs=input_ids,
                )
        payload["derivation_reused"] = False
        return self.ingest_path(
            artifact_key,
            path,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed_at,
            media_type=media_type,
            metadata=payload,
            inputs=input_ids,
            materialization_kind=materialization_kind,
        )

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
    ) -> ArtifactObservation:
        """Record derived bytes with deterministic content reuse and fresh provenance."""
        input_observations = tuple(inputs)
        input_ids = tuple(observation.observation_id for observation in input_observations)
        payload: JsonObject = {**(metadata or {}), "derived_artifact": True}
        if derivation_key is not None:
            payload["derivation_key"] = str(derivation_key)
            reusable = self.reusable_derived_content(derivation_key, artifact_key)
            if reusable is not None:
                payload["derivation_reused"] = True
                return self.observe_content(
                    artifact_key,
                    reusable,
                    run_id=run_id,
                    operation_id=operation_id,
                    observed_at=observed_at,
                    metadata=payload,
                    inputs=input_ids,
                )
        payload["derivation_reused"] = False
        return self.ingest_bytes(
            artifact_key,
            data,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed_at,
            media_type=media_type,
            metadata=payload,
            inputs=input_ids,
        )

    def provenance_inputs(
        self,
        observation_id: ObservationId | str,
    ) -> tuple[ProvenanceEdge, ...]:
        """Return direct provenance inputs for an output observation."""
        return self.metadata.provenance_inputs(ObservationId(str(observation_id)))

    def _record_content_observation(
        self,
        *,
        artifact_key: ArtifactKey,
        content: ContentRef,
        run_id: RunId,
        operation_id: OperationId,
        source_id: SourceId | None,
        observed_at: float,
        source_path: str | None,
        upstream_locator: str | None,
        upstream_modified_at: float | None,
        upstream_version: str | None,
        media_type: str | None,
        metadata: JsonObject,
        inputs: Iterable[ObservationId],
    ) -> ArtifactObservation:
        observation_id = observation_id_for(
            artifact_key=artifact_key,
            content_id=content.content_id,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed_at,
            source_path=source_path,
            upstream_locator=upstream_locator,
        )
        observation = ArtifactObservation(
            observation_id=observation_id,
            artifact_key=artifact_key,
            content_id=content.content_id,
            source_id=source_id,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed_at,
            source_path=source_path,
            upstream_locator=upstream_locator,
            upstream_modified_at=upstream_modified_at,
            upstream_version=upstream_version,
            media_type=media_type,
            metadata=metadata,
        )
        edges = tuple(
            ProvenanceEdge(output_observation_id=observation_id, input_observation_id=input_id)
            for input_id in inputs
        )
        self.metadata.record_observation_bundle(
            content=content,
            observation=observation,
            provenance_edges=edges,
        )
        return observation

    def record_absence(
        self,
        artifact_key: ArtifactKey | str,
        *,
        run_id: RunId,
        operation_id: OperationId,
        source_id: SourceId | str | None = None,
        observed_at: float | None = None,
        source_path: str | None = None,
        upstream_locator: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactAbsence:
        observed = time.time() if observed_at is None else observed_at
        normalized_key = ArtifactKey(str(artifact_key))
        normalized_source_id = SourceId(str(source_id)) if source_id is not None else None
        absence = ArtifactAbsence(
            observation_id=absence_id_for(
                artifact_key=normalized_key,
                run_id=run_id,
                operation_id=operation_id,
                observed_at=observed,
                source_path=source_path,
                upstream_locator=upstream_locator,
            ),
            artifact_key=normalized_key,
            source_id=normalized_source_id,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=observed,
            source_path=source_path,
            upstream_locator=upstream_locator,
            metadata=metadata or {},
        )
        self.metadata.record_absence(absence)
        return absence

    def latest_state(
        self,
        artifact_key: ArtifactKey | str,
        *,
        before: float | None = None,
    ) -> ArtifactState | None:
        return self.metadata.latest_state(ArtifactKey(str(artifact_key)), before=before)

    def observation(self, observation_id: ObservationId | str) -> ArtifactObservation | None:
        return self.metadata.observation(ObservationId(str(observation_id)))

    def observations_for(self, artifact_key: ArtifactKey | str) -> tuple[ArtifactObservation, ...]:
        return self.metadata.observations_for(ArtifactKey(str(artifact_key)))

    def latest_observation(
        self,
        artifact_key: ArtifactKey | str,
        *,
        before: float | None = None,
    ) -> ArtifactObservation | None:
        return self.metadata.latest_observation(ArtifactKey(str(artifact_key)), before=before)

    def artifact_keys(self) -> tuple[ArtifactKey, ...]:
        return self.metadata.artifact_keys()

    def open_content(self, content_id: ContentId | str) -> BinaryIO:
        return self.blobs.open(ContentId(str(content_id)))

    def verify_content(self, content_id: ContentId | str) -> bool:
        return self.blobs.verify(ContentId(str(content_id)))

    def record_validation(self, result: ValidationResult) -> None:
        self.metadata.record_validation(result)

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
    ) -> SourceSnapshot:
        ordered = tuple(sorted(entries, key=lambda entry: entry.relative_path))
        tree_id = TreeId(stable_id("tree", [entry.identity_payload() for entry in ordered]))
        observed = time.time() if observed_at is None else observed_at
        self.metadata.record_tree(tree_id, ordered, created_at=observed)
        normalized_source_id = SourceId(str(source_id))
        normalized_scope = tuple(sorted(scope))
        evidence_payload = evidence or {}
        snapshot_id = SnapshotId(
            stable_id(
                "snapshot",
                {
                    "source_id": str(normalized_source_id),
                    "run_id": str(run_id),
                    "observed_at": observed,
                    "complete": complete,
                    "tree_id": str(tree_id),
                    "scope": list(normalized_scope),
                    "evidence": evidence_payload,
                },
            )
        )
        snapshot = SourceSnapshot(
            snapshot_id=snapshot_id,
            source_id=normalized_source_id,
            run_id=run_id,
            observed_at=observed,
            complete=complete,
            tree_id=tree_id,
            scope=normalized_scope,
            evidence=evidence_payload,
        )
        self.metadata.record_source_snapshot(snapshot)
        return snapshot

    def record_source_snapshot(
        self,
        *,
        source_id: SourceId | str,
        run_id: RunId,
        complete: bool,
        scope: Iterable[str] = (),
        observed_at: float | None = None,
        evidence: JsonObject | None = None,
    ) -> SourceSnapshot:
        observed = time.time() if observed_at is None else observed_at
        normalized_source_id = SourceId(str(source_id))
        normalized_scope = tuple(sorted(scope))
        evidence_payload = evidence or {}
        snapshot_id = SnapshotId(
            stable_id(
                "snapshot",
                {
                    "source_id": str(normalized_source_id),
                    "run_id": str(run_id),
                    "observed_at": observed,
                    "complete": complete,
                    "scope": list(normalized_scope),
                    "evidence": evidence_payload,
                },
            )
        )
        snapshot = SourceSnapshot(
            snapshot_id=snapshot_id,
            source_id=normalized_source_id,
            run_id=run_id,
            observed_at=observed,
            complete=complete,
            scope=normalized_scope,
            evidence=evidence_payload,
        )
        self.metadata.record_source_snapshot(snapshot)
        return snapshot

    def tree_entries(self, tree_id: TreeId | str) -> tuple[TreeEntry, ...]:
        return self.metadata.tree_entries(TreeId(str(tree_id)))

    def latest_source_snapshot(self, source_id: SourceId | str) -> SourceSnapshot | None:
        return self.metadata.latest_source_snapshot(SourceId(str(source_id)))

    def resolve_dataset(
        self,
        definition: DatasetDefinition,
        *,
        created_at: float | None = None,
    ) -> ImmutableDataset:
        manifest = resolve_dataset(self, definition, created_at=created_at)
        existing = self.metadata.dataset(manifest.dataset_id)
        if existing is None:
            self.metadata.record_dataset(manifest.to_record())
        else:
            manifest = type(manifest).from_record(existing)
        return ImmutableDataset(self, manifest)

    def dataset(self, dataset_id: DatasetId | str) -> ImmutableDataset:
        record = self.metadata.dataset(DatasetId(str(dataset_id)))
        if record is None:
            msg = f"Unknown dataset: {dataset_id}"
            raise KeyError(msg)
        return ImmutableDataset(self, DatasetManifest.from_record(record))


__all__ = ["Repository"]
