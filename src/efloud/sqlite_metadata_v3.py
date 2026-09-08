from __future__ import annotations

import json
from typing import TYPE_CHECKING

from efloud.schema_migrations import CURRENT_SCHEMA_VERSION, initialize_or_migrate
from efloud.sqlite_metadata import SQLiteMetadataStore as _SQLiteMetadataStoreV2

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.metadata_store import DatasetRecord


def _dump(value: JsonObject) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SQLiteMetadataStore(_SQLiteMetadataStoreV2):
    """Canonical SQLite metadata store with explicit Phase-13 schema migration."""

    def _initialize_schema(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current == CURRENT_SCHEMA_VERSION:
            return
        if current not in {0, 1, 2}:
            msg = f"Unsupported efloud metadata schema version: {current}"
            raise RuntimeError(msg)

        if current in {0, 1}:
            super()._initialize_schema()
        initialize_or_migrate(self._connection, baseline_schema="")

    @property
    def schema_version(self) -> int:
        """Current persisted metadata schema version."""
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

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


__all__ = ["SQLiteMetadataStore"]
