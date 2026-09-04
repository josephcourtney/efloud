from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from efloud.json_types import JsonObject
from efloud.metadata_store import DatasetMemberRecord, DatasetRecord
from efloud.repository_models import (
    ArtifactKey,
    ArtifactObservation,
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

_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    definition_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    source_id TEXT REFERENCES sources(source_id),
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    details_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logical_artifacts (
    artifact_key TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS content_objects (
    content_id TEXT PRIMARY KEY,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    storage_key TEXT NOT NULL,
    media_type TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    artifact_key TEXT NOT NULL REFERENCES logical_artifacts(artifact_key),
    content_id TEXT NOT NULL REFERENCES content_objects(content_id),
    source_id TEXT REFERENCES sources(source_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    observed_at REAL NOT NULL,
    source_path TEXT,
    upstream_locator TEXT,
    upstream_modified_at REAL,
    upstream_version TEXT,
    media_type TEXT,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_artifact_time
    ON observations(artifact_key, observed_at DESC, observation_id DESC);
CREATE INDEX IF NOT EXISTS observations_source_time
    ON observations(source_id, observed_at DESC, observation_id DESC);
CREATE TABLE IF NOT EXISTS provenance_edges (
    output_observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    input_observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    relationship TEXT NOT NULL,
    PRIMARY KEY (output_observation_id, input_observation_id, relationship)
);
CREATE TABLE IF NOT EXISTS validations (
    content_id TEXT NOT NULL REFERENCES content_objects(content_id),
    validator TEXT NOT NULL,
    validator_version TEXT NOT NULL,
    checked_at REAL NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL,
    PRIMARY KEY (content_id, validator, validator_version, checked_at)
);
CREATE TABLE IF NOT EXISTS materializations (
    content_id TEXT NOT NULL REFERENCES content_objects(content_id),
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (content_id, kind, path)
);
CREATE TABLE IF NOT EXISTS tree_snapshots (
    tree_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tree_entries (
    tree_id TEXT NOT NULL REFERENCES tree_snapshots(tree_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    content_id TEXT REFERENCES content_objects(content_id),
    byte_size INTEGER,
    target TEXT,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (tree_id, relative_path)
);
CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    observed_at REAL NOT NULL,
    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
    tree_id TEXT REFERENCES tree_snapshots(tree_id),
    scope_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS source_snapshots_source_time
    ON source_snapshots(source_id, observed_at DESC, snapshot_id DESC);
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    content_identity TEXT NOT NULL,
    created_at REAL NOT NULL,
    definition_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_members (
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    artifact_key TEXT NOT NULL REFERENCES logical_artifacts(artifact_key),
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    role TEXT,
    ordinal INTEGER NOT NULL,
    PRIMARY KEY (dataset_id, artifact_key)
);
CREATE INDEX IF NOT EXISTS dataset_members_observation
    ON dataset_members(observation_id);
"""


def _dump(value: JsonObject | list[str]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_object(value: str) -> JsonObject:
    decoded = json.loads(value)
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        msg = "Expected a JSON object in repository metadata."
        raise ValueError(msg)
    return decoded


def _load_string_tuple(value: str) -> tuple[str, ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        msg = "Expected a JSON string array in repository metadata."
        raise ValueError(msg)
    return tuple(decoded)


class SQLiteMetadataStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current not in {0, _SCHEMA_VERSION}:
            msg = f"Unsupported efloud metadata schema version: {current}"
            raise RuntimeError(msg)
        with self._connection:
            self._connection.executescript(_SCHEMA)
            self._connection.execute("PRAGMA user_version = 1")

    def close(self) -> None:
        self._connection.close()

    def register_source(self, source_id: SourceId, definition: JsonObject) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO sources(source_id, definition_json) VALUES (?, ?)
                ON CONFLICT(source_id) DO UPDATE SET definition_json = excluded.definition_json
                """,
                (str(source_id), _dump(definition)),
            )

    def start_run(self, run_id: RunId, *, started_at: float, metadata: JsonObject) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO runs(run_id, started_at, status, metadata_json) VALUES (?, ?, 'running', ?)",
                (str(run_id), started_at, _dump(metadata)),
            )

    def finish_run(self, run_id: RunId, *, finished_at: float, status: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
                (finished_at, status, str(run_id)),
            )
            if cursor.rowcount != 1:
                msg = f"Unknown run: {run_id}"
                raise KeyError(msg)

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
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO operations(
                    operation_id, run_id, source_id, kind, subject, started_at,
                    status, parameters_json, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, '{}')
                """,
                (
                    str(operation_id),
                    str(run_id),
                    str(source_id) if source_id is not None else None,
                    kind,
                    subject,
                    started_at,
                    _dump(parameters),
                ),
            )

    def finish_operation(
        self,
        operation_id: OperationId,
        *,
        finished_at: float,
        status: str,
        details: JsonObject,
    ) -> None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE operations
                SET finished_at = ?, status = ?, details_json = ?
                WHERE operation_id = ?
                """,
                (finished_at, status, _dump(details), str(operation_id)),
            )
            if cursor.rowcount != 1:
                msg = f"Unknown operation: {operation_id}"
                raise KeyError(msg)

    def record_observation_bundle(
        self,
        *,
        content: ContentRef,
        observation: ArtifactObservation,
        provenance_edges: Iterable[ProvenanceEdge] = (),
    ) -> None:
        edges = tuple(provenance_edges)
        with self._connection:
            existing = self._connection.execute(
                "SELECT byte_size, storage_key FROM content_objects WHERE content_id = ?",
                (str(content.content_id),),
            ).fetchone()
            if existing is not None and (
                int(existing["byte_size"]) != content.byte_size
                or existing["storage_key"] != content.storage_key
            ):
                msg = f"Conflicting content record for {content.content_id}"
                raise ValueError(msg)
            self._connection.execute(
                """
                INSERT OR IGNORE INTO content_objects(content_id, byte_size, storage_key, media_type)
                VALUES (?, ?, ?, ?)
                """,
                (str(content.content_id), content.byte_size, content.storage_key, content.media_type),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO logical_artifacts(artifact_key) VALUES (?)",
                (str(observation.artifact_key),),
            )
            self._connection.execute(
                """
                INSERT INTO observations(
                    observation_id, artifact_key, content_id, source_id, run_id,
                    operation_id, observed_at, source_path, upstream_locator,
                    upstream_modified_at, upstream_version, media_type, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(observation.observation_id),
                    str(observation.artifact_key),
                    str(observation.content_id),
                    str(observation.source_id) if observation.source_id is not None else None,
                    str(observation.run_id),
                    str(observation.operation_id),
                    observation.observed_at,
                    observation.source_path,
                    observation.upstream_locator,
                    observation.upstream_modified_at,
                    observation.upstream_version,
                    observation.media_type,
                    _dump(observation.metadata),
                ),
            )
            self._connection.executemany(
                """
                INSERT INTO provenance_edges(
                    output_observation_id, input_observation_id, relationship
                ) VALUES (?, ?, ?)
                """,
                [
                    (
                        str(edge.output_observation_id),
                        str(edge.input_observation_id),
                        edge.relationship,
                    )
                    for edge in edges
                ],
            )

    def record_materialization(
        self,
        *,
        content_id: ContentId,
        kind: str,
        path: str,
        metadata: JsonObject,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO materializations(content_id, kind, path, metadata_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(content_id, kind, path)
                DO UPDATE SET metadata_json = excluded.metadata_json
                """,
                (str(content_id), kind, path, _dump(metadata)),
            )

    def record_validation(self, result: ValidationResult) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO validations(
                    content_id, validator, validator_version, checked_at, status, details_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(result.content_id),
                    result.validator,
                    result.validator_version,
                    result.checked_at,
                    result.status,
                    _dump(result.details),
                ),
            )

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> ArtifactObservation:
        source_raw = row["source_id"]
        return ArtifactObservation(
            observation_id=ObservationId(row["observation_id"]),
            artifact_key=ArtifactKey(row["artifact_key"]),
            content_id=ContentId(row["content_id"]),
            source_id=SourceId(source_raw) if source_raw is not None else None,
            run_id=RunId(row["run_id"]),
            operation_id=OperationId(row["operation_id"]),
            observed_at=float(row["observed_at"]),
            source_path=row["source_path"],
            upstream_locator=row["upstream_locator"],
            upstream_modified_at=(
                float(row["upstream_modified_at"])
                if row["upstream_modified_at"] is not None
                else None
            ),
            upstream_version=row["upstream_version"],
            media_type=row["media_type"],
            metadata=_load_object(row["metadata_json"]),
        )

    def observation(self, observation_id: ObservationId) -> ArtifactObservation | None:
        row = self._connection.execute(
            "SELECT * FROM observations WHERE observation_id = ?",
            (str(observation_id),),
        ).fetchone()
        return None if row is None else self._observation_from_row(row)

    def observations_for(self, artifact_key: ArtifactKey) -> tuple[ArtifactObservation, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM observations
            WHERE artifact_key = ?
            ORDER BY observed_at, observation_id
            """,
            (str(artifact_key),),
        ).fetchall()
        return tuple(self._observation_from_row(row) for row in rows)

    def latest_observation(
        self,
        artifact_key: ArtifactKey,
        *,
        before: float | None = None,
    ) -> ArtifactObservation | None:
        if before is None:
            row = self._connection.execute(
                """
                SELECT * FROM observations
                WHERE artifact_key = ?
                ORDER BY observed_at DESC, observation_id DESC
                LIMIT 1
                """,
                (str(artifact_key),),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT * FROM observations
                WHERE artifact_key = ? AND observed_at <= ?
                ORDER BY observed_at DESC, observation_id DESC
                LIMIT 1
                """,
                (str(artifact_key), before),
            ).fetchone()
        return None if row is None else self._observation_from_row(row)

    def content(self, content_id: ContentId) -> ContentRef | None:
        row = self._connection.execute(
            "SELECT * FROM content_objects WHERE content_id = ?",
            (str(content_id),),
        ).fetchone()
        if row is None:
            return None
        return ContentRef(
            content_id=ContentId(row["content_id"]),
            byte_size=int(row["byte_size"]),
            storage_key=row["storage_key"],
            media_type=row["media_type"],
        )

    def artifact_keys(self) -> tuple[ArtifactKey, ...]:
        rows = self._connection.execute(
            "SELECT artifact_key FROM logical_artifacts ORDER BY artifact_key"
        ).fetchall()
        return tuple(ArtifactKey(row["artifact_key"]) for row in rows)

    def record_tree(self, tree_id: TreeId, entries: Iterable[TreeEntry], *, created_at: float) -> None:
        ordered = tuple(sorted(entries, key=lambda entry: entry.relative_path))
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO tree_snapshots(tree_id, created_at) VALUES (?, ?)",
                (str(tree_id), created_at),
            )
            existing_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM tree_entries WHERE tree_id = ?",
                    (str(tree_id),),
                ).fetchone()[0]
            )
            if existing_count not in {0, len(ordered)}:
                msg = f"Conflicting tree record for {tree_id}"
                raise ValueError(msg)
            if existing_count == 0:
                self._connection.executemany(
                    """
                    INSERT INTO tree_entries(
                        tree_id, relative_path, kind, content_id, byte_size, target, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            str(tree_id),
                            entry.relative_path,
                            entry.kind,
                            str(entry.content_id) if entry.content_id is not None else None,
                            entry.byte_size,
                            entry.target,
                            _dump(entry.metadata),
                        )
                        for entry in ordered
                    ],
                )

    def tree_entries(self, tree_id: TreeId) -> tuple[TreeEntry, ...]:
        rows = self._connection.execute(
            "SELECT * FROM tree_entries WHERE tree_id = ? ORDER BY relative_path",
            (str(tree_id),),
        ).fetchall()
        return tuple(
            TreeEntry(
                relative_path=row["relative_path"],
                kind=row["kind"],
                content_id=ContentId(row["content_id"]) if row["content_id"] is not None else None,
                byte_size=int(row["byte_size"]) if row["byte_size"] is not None else None,
                target=row["target"],
                metadata=_load_object(row["metadata_json"]),
            )
            for row in rows
        )

    def record_source_snapshot(self, snapshot: SourceSnapshot) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO source_snapshots(
                    snapshot_id, source_id, run_id, observed_at, complete,
                    tree_id, scope_json, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(snapshot.snapshot_id),
                    str(snapshot.source_id),
                    str(snapshot.run_id),
                    snapshot.observed_at,
                    int(snapshot.complete),
                    str(snapshot.tree_id) if snapshot.tree_id is not None else None,
                    _dump(list(snapshot.scope)),
                    _dump(snapshot.evidence),
                ),
            )

    @staticmethod
    def _source_snapshot_from_row(row: sqlite3.Row) -> SourceSnapshot:
        tree_raw = row["tree_id"]
        return SourceSnapshot(
            snapshot_id=SnapshotId(row["snapshot_id"]),
            source_id=SourceId(row["source_id"]),
            run_id=RunId(row["run_id"]),
            observed_at=float(row["observed_at"]),
            complete=bool(row["complete"]),
            tree_id=TreeId(tree_raw) if tree_raw is not None else None,
            scope=_load_string_tuple(row["scope_json"]),
            evidence=_load_object(row["evidence_json"]),
        )

    def source_snapshot(self, snapshot_id: SnapshotId) -> SourceSnapshot | None:
        row = self._connection.execute(
            "SELECT * FROM source_snapshots WHERE snapshot_id = ?",
            (str(snapshot_id),),
        ).fetchone()
        return None if row is None else self._source_snapshot_from_row(row)

    def latest_source_snapshot(self, source_id: SourceId) -> SourceSnapshot | None:
        row = self._connection.execute(
            """
            SELECT * FROM source_snapshots
            WHERE source_id = ?
            ORDER BY observed_at DESC, snapshot_id DESC
            LIMIT 1
            """,
            (str(source_id),),
        ).fetchone()
        return None if row is None else self._source_snapshot_from_row(row)

    def record_dataset(self, record: DatasetRecord) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO datasets(
                    dataset_id, content_identity, created_at, definition_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(record.dataset_id),
                    record.content_identity,
                    record.created_at,
                    _dump(record.definition),
                    _dump(record.metadata),
                ),
            )
            self._connection.executemany(
                """
                INSERT INTO dataset_members(
                    dataset_id, artifact_key, observation_id, role, ordinal
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(record.dataset_id),
                        str(member.artifact_key),
                        str(member.observation_id),
                        member.role,
                        ordinal,
                    )
                    for ordinal, member in enumerate(record.members)
                ],
            )

    def dataset(self, dataset_id: DatasetId) -> DatasetRecord | None:
        row = self._connection.execute(
            "SELECT * FROM datasets WHERE dataset_id = ?",
            (str(dataset_id),),
        ).fetchone()
        if row is None:
            return None
        member_rows = self._connection.execute(
            """
            SELECT dm.artifact_key, dm.observation_id, dm.role, o.content_id
            FROM dataset_members AS dm
            JOIN observations AS o ON o.observation_id = dm.observation_id
            WHERE dm.dataset_id = ?
            ORDER BY dm.ordinal
            """,
            (str(dataset_id),),
        ).fetchall()
        return DatasetRecord(
            dataset_id=DatasetId(row["dataset_id"]),
            content_identity=row["content_identity"],
            created_at=float(row["created_at"]),
            definition=_load_object(row["definition_json"]),
            metadata=_load_object(row["metadata_json"]),
            members=tuple(
                DatasetMemberRecord(
                    artifact_key=ArtifactKey(member["artifact_key"]),
                    observation_id=ObservationId(member["observation_id"]),
                    content_id=ContentId(member["content_id"]),
                    role=member["role"],
                )
                for member in member_rows
            ),
        )


__all__ = ["SQLiteMetadataStore"]
