from __future__ import annotations

from typing import TYPE_CHECKING

from efloud.schema import CURRENT_SCHEMA_VERSION

if TYPE_CHECKING:
    import sqlite3

CURRENT_SCHEMA_SQL = """
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
CREATE INDEX IF NOT EXISTS operations_run_time
    ON operations(run_id, started_at, operation_id);
CREATE INDEX IF NOT EXISTS operations_source_time
    ON operations(source_id, started_at DESC, operation_id DESC);
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
CREATE TABLE IF NOT EXISTS artifact_absences (
    observation_id TEXT PRIMARY KEY,
    artifact_key TEXT NOT NULL REFERENCES logical_artifacts(artifact_key),
    source_id TEXT REFERENCES sources(source_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    observed_at REAL NOT NULL,
    source_path TEXT,
    upstream_locator TEXT,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS artifact_absences_artifact_time
    ON artifact_absences(artifact_key, observed_at DESC, observation_id DESC);
CREATE INDEX IF NOT EXISTS artifact_absences_source_time
    ON artifact_absences(source_id, observed_at DESC, observation_id DESC);
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
CREATE INDEX IF NOT EXISTS validations_content_validator
    ON validations(content_id, validator, validator_version, checked_at DESC);
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


def _application_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create the current schema, or reject any non-current repository."""
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current == CURRENT_SCHEMA_VERSION:
        return
    if current != 0:
        msg = (
            f"Unsupported efloud metadata schema version: {current}; "
            f"expected {CURRENT_SCHEMA_VERSION}. Historical schemas are not migrated in place."
        )
        raise RuntimeError(msg)

    existing_tables = _application_tables(connection)
    if existing_tables:
        msg = (
            "Unsupported unversioned efloud metadata database; clean repositories must be initialized "
            f"at schema version {CURRENT_SCHEMA_VERSION}."
        )
        raise RuntimeError(msg)

    with connection:
        connection.executescript(CURRENT_SCHEMA_SQL)
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")


__all__ = ["CURRENT_SCHEMA_SQL", "initialize_schema"]
