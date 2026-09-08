from __future__ import annotations

import json
import sqlite3

from efloud.json_types import JsonObject, json_object_or_none
from efloud.metadata_envelopes import (
    dataset_specifications_payload,
    source_definition_history_payload,
)

CURRENT_SCHEMA_VERSION = 3
_SUPPORTED_HISTORICAL_VERSIONS = frozenset({1, 2})


def _load_object(raw: str) -> JsonObject:
    decoded = json.loads(raw)
    value = json_object_or_none(decoded)
    if value is None:
        msg = "Expected a JSON object in repository metadata during migration."
        raise ValueError(msg)
    return dict(value)


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _set_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(f"PRAGMA user_version = {version}")


def _migrate_1_to_2(connection: sqlite3.Connection, *, baseline_schema: str) -> None:
    connection.executescript(baseline_schema)
    _set_version(connection, 2)


def _migrate_2_to_3(connection: sqlite3.Connection) -> None:
    source_rows = connection.execute("SELECT source_id, definition_json FROM sources").fetchall()
    for source_id, raw_definition in source_rows:
        definition = _load_object(raw_definition)
        envelope = source_definition_history_payload(str(source_id), definition)
        connection.execute(
            "UPDATE sources SET definition_json = ? WHERE source_id = ?",
            (_dump(envelope), source_id),
        )

    dataset_rows = connection.execute("SELECT dataset_id, definition_json FROM datasets").fetchall()
    for dataset_id, raw_definition in dataset_rows:
        definition = _load_object(raw_definition)
        envelope = dataset_specifications_payload(definition)
        connection.execute(
            "UPDATE datasets SET definition_json = ? WHERE dataset_id = ?",
            (_dump(envelope), dataset_id),
        )

    _set_version(connection, 3)


def initialize_or_migrate(
    connection: sqlite3.Connection,
    *,
    baseline_schema: str,
) -> None:
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    supported = {0, *_SUPPORTED_HISTORICAL_VERSIONS, CURRENT_SCHEMA_VERSION}
    if current not in supported:
        msg = f"Unsupported efloud metadata schema version: {current}"
        raise RuntimeError(msg)

    with connection:
        if current == 0:
            connection.executescript(baseline_schema)
            _set_version(connection, 2)
            current = 2
        if current == 1:
            _migrate_1_to_2(connection, baseline_schema=baseline_schema)
            current = 2
        if current == 2:
            _migrate_2_to_3(connection)


__all__ = ["CURRENT_SCHEMA_VERSION", "initialize_or_migrate"]
