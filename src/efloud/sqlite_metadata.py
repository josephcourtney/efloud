from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from efloud.json_types import json_mapping_or_none, json_object_or_none
from efloud.metadata_store import (
    DatasetMemberRecord,
    DatasetRecord,
    MaterializationRecord,
    OperationRecord,
    RunRecord,
    SourceRecord,
)
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
)
from efloud.schema_migrations import initialize_schema

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from efloud.json_types import JsonObject

_SHA256_HEX_LENGTH = 64


def _storage_key_for(content_id: ContentId) -> str:
    """Derive the canonical SQLite locator without consulting any blob backend."""
    text = str(content_id)
    prefix = "sha256:"
    if not text.startswith(prefix):
        return text
    digest = text.removeprefix(prefix)
    if len(digest) != _SHA256_HEX_LENGTH or any(ch not in "0123456789abcdef" for ch in digest):
        return text
    return f"sha256/{digest[:2]}/{digest}"


_RUN_TERMINAL = frozenset({"succeeded", "partial", "failed", "cancelled"})
_OPERATION_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def _dump(value: JsonObject | list[str]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_object(value: str) -> JsonObject:
    decoded = json.loads(value)
    json_object = json_object_or_none(decoded)
    if json_object is None:
        msg = "Expected a JSON object in repository metadata."
        raise ValueError(msg)
    return json_object


def _load_string_tuple(value: str) -> tuple[str, ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        msg = "Expected a JSON string array in repository metadata."
        raise ValueError(msg)
    return tuple(decoded)


def _run_terminal_status(status: str) -> str:
    if status not in _RUN_TERMINAL:
        msg = f"Invalid terminal run status: {status!r}"
        raise ValueError(msg)
    return status


def _operation_terminal_status(status: str) -> str:
    if status not in _OPERATION_TERMINAL:
        msg = f"Invalid terminal operation status: {status!r}"
        raise ValueError(msg)
    return status


def _operation_parameters(parameters: JsonObject) -> JsonObject:
    normalized = dict(parameters)
    raw_producer = json_mapping_or_none(normalized.get("producer"))
    if raw_producer is None:
        msg = "Operation parameters require canonical producer metadata."
        raise ValueError(msg)
    ProducerRef.from_mapping(raw_producer)
    return normalized


class SQLiteMetadataStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        self._connection = connection
        initialized = False
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._initialize_schema()
            initialized = True
        finally:
            if not initialized:
                connection.close()

    def _initialize_schema(self) -> None:
        initialize_schema(self._connection)

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

    def source(self, source_id: SourceId) -> SourceRecord | None:
        row = self._connection.execute(
            "SELECT * FROM sources WHERE source_id = ?",
            (str(source_id),),
        ).fetchone()
        if row is None:
            return None
        return SourceRecord(source_id=SourceId(row["source_id"]), definition=_load_object(row["definition_json"]))

    def sources(self) -> tuple[SourceRecord, ...]:
        rows = self._connection.execute("SELECT * FROM sources ORDER BY source_id").fetchall()
        return tuple(
            SourceRecord(source_id=SourceId(row["source_id"]), definition=_load_object(row["definition_json"]))
            for row in rows
        )

    def start_run(self, run_id: RunId, *, started_at: float, metadata: JsonObject) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO runs(run_id, started_at, status, metadata_json) VALUES (?, ?, 'running', ?)",
                (str(run_id), started_at, _dump(metadata)),
            )

    def finish_run(self, run_id: RunId, *, finished_at: float, status: str) -> None:
        normalized_status = _run_terminal_status(status)
        with self._connection:
            row = self._connection.execute(
                "SELECT status FROM runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
            if row is None:
                msg = f"Unknown run: {run_id}"
                raise KeyError(msg)
            if row["status"] != "running":
                msg = f"Run {run_id} cannot transition from {row['status']!r}."
                raise ValueError(msg)
            running_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE run_id = ? AND status = 'running'",
                    (str(run_id),),
                ).fetchone()[0]
            )
            if running_count:
                msg = f"Run {run_id} cannot finish while operations are still running."
                raise ValueError(msg)
            self._connection.execute(
                "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
                (finished_at, normalized_status, str(run_id)),
            )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRecord:
        finished = row["finished_at"]
        return RunRecord(
            run_id=RunId(row["run_id"]),
            started_at=float(row["started_at"]),
            finished_at=float(finished) if finished is not None else None,
            status=row["status"],
            metadata=_load_object(row["metadata_json"]),
        )

    def run(self, run_id: RunId) -> RunRecord | None:
        row = self._connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        return None if row is None else self._run_from_row(row)

    def recent_runs(self, *, limit: int = 50) -> tuple[RunRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, run_id DESC LIMIT ?",
            (max(0, limit),),
        ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

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
        normalized_parameters = _operation_parameters(parameters)
        with self._connection:
            run_row = self._connection.execute(
                "SELECT status FROM runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
            if run_row is None:
                msg = f"Unknown run: {run_id}"
                raise KeyError(msg)
            if run_row["status"] != "running":
                msg = f"Cannot start operation {operation_id} in terminal run {run_id}."
                raise ValueError(msg)
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
                    _dump(normalized_parameters),
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
        normalized_status = _operation_terminal_status(status)
        with self._connection:
            row = self._connection.execute(
                "SELECT status FROM operations WHERE operation_id = ?",
                (str(operation_id),),
            ).fetchone()
            if row is None:
                msg = f"Unknown operation: {operation_id}"
                raise KeyError(msg)
            if row["status"] != "running":
                msg = f"Operation {operation_id} cannot transition from {row['status']!r}."
                raise ValueError(msg)
            self._connection.execute(
                """
                UPDATE operations
                SET finished_at = ?, status = ?, details_json = ?
                WHERE operation_id = ?
                """,
                (finished_at, normalized_status, _dump(details), str(operation_id)),
            )

    @staticmethod
    def _operation_from_row(row: sqlite3.Row) -> OperationRecord:
        source_raw = row["source_id"]
        finished = row["finished_at"]
        return OperationRecord(
            operation_id=OperationId(row["operation_id"]),
            run_id=RunId(row["run_id"]),
            source_id=SourceId(source_raw) if source_raw is not None else None,
            kind=row["kind"],
            subject=row["subject"],
            started_at=float(row["started_at"]),
            finished_at=float(finished) if finished is not None else None,
            status=row["status"],
            parameters=_load_object(row["parameters_json"]),
            details=_load_object(row["details_json"]),
        )

    def operations_for_run(self, run_id: RunId) -> tuple[OperationRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM operations WHERE run_id = ? ORDER BY started_at, operation_id",
            (str(run_id),),
        ).fetchall()
        return tuple(self._operation_from_row(row) for row in rows)

    def operations_for_source(
        self,
        source_id: SourceId,
        *,
        limit: int = 50,
    ) -> tuple[OperationRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM operations
            WHERE source_id = ?
            ORDER BY started_at DESC, operation_id DESC
            LIMIT ?
            """,
            (str(source_id), max(0, limit)),
        ).fetchall()
        return tuple(self._operation_from_row(row) for row in rows)

    def record_content(self, content: ContentRef) -> None:
        with self._connection:
            existing = self._connection.execute(
                "SELECT byte_size, storage_key FROM content_objects WHERE content_id = ?",
                (str(content.content_id),),
            ).fetchone()
            if existing is not None and (
                int(existing["byte_size"]) != content.byte_size
                or existing["storage_key"] != _storage_key_for(content.content_id)
            ):
                msg = f"Conflicting content record for {content.content_id}"
                raise ValueError(msg)
            self._connection.execute(
                """
                INSERT OR IGNORE INTO content_objects(content_id, byte_size, storage_key, media_type)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(content.content_id),
                    content.byte_size,
                    _storage_key_for(content.content_id),
                    content.media_type,
                ),
            )

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
                or existing["storage_key"] != _storage_key_for(content.content_id)
            ):
                msg = f"Conflicting content record for {content.content_id}"
                raise ValueError(msg)
            self._connection.execute(
                """
                INSERT OR IGNORE INTO content_objects(content_id, byte_size, storage_key, media_type)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(content.content_id),
                    content.byte_size,
                    _storage_key_for(content.content_id),
                    content.media_type,
                ),
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

    def provenance_inputs(self, observation_id: ObservationId) -> tuple[ProvenanceEdge, ...]:
        rows = self._connection.execute(
            """
            SELECT output_observation_id, input_observation_id, relationship
            FROM provenance_edges
            WHERE output_observation_id = ?
            ORDER BY input_observation_id, relationship
            """,
            (str(observation_id),),
        ).fetchall()
        return tuple(
            ProvenanceEdge(
                output_observation_id=ObservationId(row["output_observation_id"]),
                input_observation_id=ObservationId(row["input_observation_id"]),
                relationship=row["relationship"],
            )
            for row in rows
        )

    def record_absence(self, absence: ArtifactAbsence) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO logical_artifacts(artifact_key) VALUES (?)",
                (str(absence.artifact_key),),
            )
            self._connection.execute(
                """
                INSERT INTO artifact_absences(
                    observation_id, artifact_key, source_id, run_id, operation_id,
                    observed_at, source_path, upstream_locator, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(absence.observation_id),
                    str(absence.artifact_key),
                    str(absence.source_id) if absence.source_id is not None else None,
                    str(absence.run_id),
                    str(absence.operation_id),
                    absence.observed_at,
                    absence.source_path,
                    absence.upstream_locator,
                    _dump(absence.metadata),
                ),
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

    def materializations_for(self, content_id: ContentId) -> tuple[MaterializationRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM materializations
            WHERE content_id = ?
            ORDER BY kind, path
            """,
            (str(content_id),),
        ).fetchall()
        return tuple(
            MaterializationRecord(
                content_id=ContentId(row["content_id"]),
                kind=row["kind"],
                path=row["path"],
                metadata=_load_object(row["metadata_json"]),
            )
            for row in rows
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
    def _validation_from_row(row: sqlite3.Row) -> ValidationResult:
        return ValidationResult(
            content_id=ContentId(row["content_id"]),
            validator=row["validator"],
            validator_version=row["validator_version"],
            checked_at=float(row["checked_at"]),
            status=row["status"],
            details=_load_object(row["details_json"]),
        )

    def validation(
        self,
        content_id: ContentId,
        validator: str,
        validator_version: str,
    ) -> ValidationResult | None:
        row = self._connection.execute(
            """
            SELECT * FROM validations
            WHERE content_id = ? AND validator = ? AND validator_version = ?
            ORDER BY checked_at DESC
            LIMIT 1
            """,
            (str(content_id), validator, validator_version),
        ).fetchone()
        return None if row is None else self._validation_from_row(row)

    def validations_for(self, content_id: ContentId) -> tuple[ValidationResult, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM validations
            WHERE content_id = ?
            ORDER BY validator, validator_version, checked_at
            """,
            (str(content_id),),
        ).fetchall()
        return tuple(self._validation_from_row(row) for row in rows)

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> ArtifactObservation:
        source_raw = row["source_id"]
        modified = row["upstream_modified_at"]
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
            upstream_modified_at=float(modified) if modified is not None else None,
            upstream_version=row["upstream_version"],
            media_type=row["media_type"],
            metadata=_load_object(row["metadata_json"]),
        )

    @staticmethod
    def _absence_from_row(row: sqlite3.Row) -> ArtifactAbsence:
        source_raw = row["source_id"]
        return ArtifactAbsence(
            observation_id=ObservationId(row["observation_id"]),
            artifact_key=ArtifactKey(row["artifact_key"]),
            source_id=SourceId(source_raw) if source_raw is not None else None,
            run_id=RunId(row["run_id"]),
            operation_id=OperationId(row["operation_id"]),
            observed_at=float(row["observed_at"]),
            source_path=row["source_path"],
            upstream_locator=row["upstream_locator"],
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

    def _latest_absence(
        self,
        artifact_key: ArtifactKey,
        *,
        before: float | None = None,
    ) -> ArtifactAbsence | None:
        if before is None:
            row = self._connection.execute(
                """
                SELECT * FROM artifact_absences
                WHERE artifact_key = ?
                ORDER BY observed_at DESC, observation_id DESC
                LIMIT 1
                """,
                (str(artifact_key),),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT * FROM artifact_absences
                WHERE artifact_key = ? AND observed_at <= ?
                ORDER BY observed_at DESC, observation_id DESC
                LIMIT 1
                """,
                (str(artifact_key), before),
            ).fetchone()
        return None if row is None else self._absence_from_row(row)

    def latest_state(
        self,
        artifact_key: ArtifactKey,
        *,
        before: float | None = None,
    ) -> ArtifactState | None:
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
            media_type=row["media_type"],
        )

    def artifact_keys(self) -> tuple[ArtifactKey, ...]:
        rows = self._connection.execute("SELECT artifact_key FROM logical_artifacts ORDER BY artifact_key").fetchall()
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

    def source_snapshots_for(
        self,
        source_id: SourceId,
        *,
        limit: int | None = 50,
    ) -> tuple[SourceSnapshot, ...]:
        if limit is not None and limit < 0:
            msg = "limit must be nonnegative or None"
            raise ValueError(msg)
        query = """
            SELECT * FROM source_snapshots
            WHERE source_id = ?
            ORDER BY observed_at DESC, snapshot_id DESC
        """
        if limit is None:
            rows = self._connection.execute(query, (str(source_id),)).fetchall()
        else:
            rows = self._connection.execute(f"{query} LIMIT ?", (str(source_id), limit)).fetchall()
        return tuple(self._source_snapshot_from_row(row) for row in rows)

    def record_dataset(self, record: DatasetRecord) -> None:
        existing = self.dataset(record.dataset_id)
        if existing is not None:
            if existing.content_identity != record.content_identity or existing.members != record.members:
                msg = f"Conflicting dataset membership for {record.dataset_id}"
                raise ValueError(msg)
            merged = record.with_specifications(existing.specifications)
            with self._connection:
                self._connection.execute(
                    """
                    UPDATE datasets
                    SET definition_json = ?, metadata_json = ?
                    WHERE dataset_id = ?
                    """,
                    (
                        _dump(merged.storage_definition()),
                        _dump(merged.metadata),
                        str(record.dataset_id),
                    ),
                )
            return

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
                    _dump(record.storage_definition()),
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

    @property
    def schema_version(self) -> int:
        """Current persisted metadata schema version."""
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    def operation(self, operation_id: OperationId) -> OperationRecord | None:
        row = self._connection.execute(
            "SELECT * FROM operations WHERE operation_id = ?",
            (str(operation_id),),
        ).fetchone()
        return None if row is None else self._operation_from_row(row)


__all__ = ["SQLiteMetadataStore"]
