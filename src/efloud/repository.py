from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, BinaryIO

from efloud.blob_store import BlobStore, FilesystemBlobStore
from efloud.json_types import JsonObject
from efloud.metadata_store import MetadataStore
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
    absence_id_for,
    observation_id_for,
    operation_id_for,
    run_id_for,
    stable_id,
)
from efloud.sqlite_metadata import SQLiteMetadataStore

if TYPE_CHECKING:
    from efloud.datasets import DatasetDefinition, ImmutableDataset


class Repository:
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

    def __enter__(self) -> Repository:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
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
        self.metadata.finish_run(
            run_id,
            finished_at=time.time() if finished_at is None else finished_at,
            status=status,
        )

    def start_operation(
        self,
        *,
        run_id: RunId,
        kind: str,
        subject: str,
        source_id: SourceId | str | None = None,
        started_at: float | None = None,
        parameters: JsonObject | None = None,
    ) -> OperationId:
        operation_id = operation_id_for(run_id=run_id, kind=kind, subject=subject)
        normalized_source_id = SourceId(str(source_id)) if source_id is not None else None
        self.metadata.start_operation(
            operation_id,
            run_id=run_id,
            source_id=normalized_source_id,
            kind=kind,
            subject=subject,
            started_at=time.time() if started_at is None else started_at,
            parameters=parameters or {},
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
        self.metadata.finish_operation(
            operation_id,
            finished_at=time.time() if finished_at is None else finished_at,
            status=status,
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
        from efloud.datasets import ImmutableDataset, resolve_dataset

        manifest = resolve_dataset(self, definition, created_at=created_at)
        existing = self.metadata.dataset(manifest.dataset_id)
        if existing is None:
            self.metadata.record_dataset(manifest.to_record())
        else:
            manifest = type(manifest).from_record(existing)
        return ImmutableDataset(self, manifest)

    def dataset(self, dataset_id: DatasetId | str) -> ImmutableDataset:
        from efloud.datasets import DatasetManifest, ImmutableDataset

        record = self.metadata.dataset(DatasetId(str(dataset_id)))
        if record is None:
            msg = f"Unknown dataset: {dataset_id}"
            raise KeyError(msg)
        return ImmutableDataset(self, DatasetManifest.from_record(record))


__all__ = ["Repository"]
