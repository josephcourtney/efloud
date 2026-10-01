from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, BinaryIO, Self

from efloud.content.git_annex import GitAnnexContentStore
from efloud.content.protocol import AnnexKey, ContentReader
from efloud.datasets import DatasetManifest, ImmutableDataset
from efloud.repository_models import (
    ArtifactKey,
    ArtifactObservation,
    ArtifactState,
    ContentId,
    ContentRef,
    DatasetId,
    ObservationId,
    OperationId,
    SnapshotId,
    SourceId,
    SourceSnapshot,
    TreeEntry,
    TreeId,
    ValidationResult,
)
from efloud.repository_models import RunId as RepositoryRunId
from efloud.schema import CURRENT_SCHEMA_VERSION
from efloud.sqlite_metadata import SQLiteMetadataStore

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from efloud.metadata_store import (
        MaterializationRecord,
        OperationRecord,
        RunRecord,
        SourceRecord,
    )
    from efloud.repository_models import (
        DatasetSpecification,
        ProvenanceEdge,
        RunId,
    )


class ReadOnlySQLiteMetadataStore(SQLiteMetadataStore):
    """SQLite metadata access that never initializes or migrates repository state."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve(strict=True)
        if not self.path.is_file():
            msg = f"Repository metadata is not a file: {self.path}"
            raise FileNotFoundError(msg)
        uri = f"{self.path.as_uri()}?mode=ro"
        self._connection = sqlite3.connect(uri, uri=True)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current != CURRENT_SCHEMA_VERSION:
            self._connection.close()
            msg = (
                f"Unsupported efloud metadata schema version: {current}; "
                f"expected {CURRENT_SCHEMA_VERSION}. Historical schemas are not migrated in place."
            )
            raise RuntimeError(msg)


class ReadOnlyGitAnnexContentStore:
    """Read-only view of git-annex custody operations."""

    def __init__(self, store: GitAnnexContentStore) -> None:
        self._store = store

    def has_content(self, key: AnnexKey) -> bool:
        return self._store.has_content(key)

    def open(self, key: AnnexKey) -> BinaryIO:
        return self._store.open(key)

    def verify(self, key: AnnexKey) -> bool:
        return self._store.verify(key)

    def content_ref(self, key: AnnexKey, *, media_type: str | None = None):
        return self._store.content_ref(key, media_type=media_type)

    def present_keys(self) -> tuple[AnnexKey, ...]:
        return self._store.present_keys()


class ReadOnlyRepository:  # ruff: ignore[too-many-public-methods] - mirrors the repository's read capability surface.
    """Non-mutating view of an existing efloud repository.

    Construction does not create directories, initialize schemas, or run schema
    migrations. The SQLite database is opened with ``mode=ro`` and content custody is exposed only
    through its read-only content-reader port.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            msg = f"Repository root is not a directory: {self.root}"
            raise FileNotFoundError(msg)
        self.metadata = ReadOnlySQLiteMetadataStore(self.root / "metadata.sqlite")
        store = GitAnnexContentStore(self.root)
        store.check_available()
        self.content_store: ContentReader = ReadOnlyGitAnnexContentStore(store)

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

    def source(self, source_id: SourceId | str) -> SourceRecord | None:
        return self.metadata.source(SourceId(str(source_id)))

    def sources(self) -> tuple[SourceRecord, ...]:
        return self.metadata.sources()

    def run(self, run_id: RunId | str) -> RunRecord | None:
        return self.metadata.run(RepositoryRunId(str(run_id)))

    def recent_runs(self, *, limit: int = 50) -> tuple[RunRecord, ...]:
        return self.metadata.recent_runs(limit=limit)

    def operation(self, operation_id: OperationId | str) -> OperationRecord | None:
        return self.metadata.operation(OperationId(str(operation_id)))

    def operations_for_run(self, run_id: RunId | str) -> tuple[OperationRecord, ...]:
        return self.metadata.operations_for_run(RepositoryRunId(str(run_id)))

    def operations_for_source(
        self,
        source_id: SourceId | str,
        *,
        limit: int = 50,
    ) -> tuple[OperationRecord, ...]:
        return self.metadata.operations_for_source(SourceId(str(source_id)), limit=limit)

    def provenance_inputs(
        self,
        observation_id: ObservationId | str,
    ) -> tuple[ProvenanceEdge, ...]:
        return self.metadata.provenance_inputs(ObservationId(str(observation_id)))

    def materializations_for(self, content_id: ContentId | str) -> tuple[MaterializationRecord, ...]:
        return self.metadata.materializations_for(ContentId(str(content_id)))

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

    def content(self, content_id: ContentId | str) -> ContentRef | None:
        return self.metadata.content(ContentId(str(content_id)))

    def artifact_keys(self) -> tuple[ArtifactKey, ...]:
        return self.metadata.artifact_keys()

    def open_content(self, content_id: ContentId | str) -> BinaryIO:
        content = self.metadata.content(ContentId(str(content_id)))
        if content is None:
            msg = f"Unknown repository content: {content_id}"
            raise KeyError(msg)
        return self.content_store.open(AnnexKey(content.custody_key))

    def contains_content(self, content_id: ContentId | str) -> bool:
        content = self.metadata.content(ContentId(str(content_id)))
        return content is not None and self.content_store.has_content(AnnexKey(content.custody_key))

    def verify_content(self, content_id: ContentId | str) -> bool:
        content = self.metadata.content(ContentId(str(content_id)))
        return content is not None and self.content_store.verify(AnnexKey(content.custody_key))

    def validation(
        self,
        content_id: ContentId | str,
        validator: str,
        validator_version: str,
    ) -> ValidationResult | None:
        return self.metadata.validation(ContentId(str(content_id)), validator, validator_version)

    def validations_for(self, content_id: ContentId | str) -> tuple[ValidationResult, ...]:
        return self.metadata.validations_for(ContentId(str(content_id)))

    def tree_entries(self, tree_id: TreeId | str) -> tuple[TreeEntry, ...]:
        return self.metadata.tree_entries(TreeId(str(tree_id)))

    def source_snapshot(self, snapshot_id: SnapshotId | str) -> SourceSnapshot | None:
        return self.metadata.source_snapshot(SnapshotId(str(snapshot_id)))

    def latest_source_snapshot(self, source_id: SourceId | str) -> SourceSnapshot | None:
        return self.metadata.latest_source_snapshot(SourceId(str(source_id)))

    def source_snapshots_for(
        self,
        source_id: SourceId | str,
        *,
        limit: int | None = 50,
    ) -> tuple[SourceSnapshot, ...]:
        return self.metadata.source_snapshots_for(SourceId(str(source_id)), limit=limit)

    def dataset(self, dataset_id: DatasetId | str) -> ImmutableDataset:
        record = self.metadata.dataset(DatasetId(str(dataset_id)))
        if record is None:
            msg = f"Unknown dataset: {dataset_id}"
            raise KeyError(msg)
        return ImmutableDataset(self, DatasetManifest.from_record(record))

    def dataset_specifications(
        self,
        dataset_id: DatasetId | str,
    ) -> tuple[DatasetSpecification, ...]:
        record = self.metadata.dataset(DatasetId(str(dataset_id)))
        if record is None:
            msg = f"Unknown dataset: {dataset_id}"
            raise KeyError(msg)
        return record.specifications


__all__ = [
    "ReadOnlyRepository",
    "ReadOnlySQLiteMetadataStore",
]
