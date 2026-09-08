from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, cast

import pytest

from efloud.datasets import DatasetDefinition, ExactObservation, Latest
from efloud.repository import Repository
from efloud.repository_models import SourceId, ValidationResult
from efloud.repository_query import RepositoryQueryService

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.json_types import JsonObject
    from efloud.sqlite_metadata_v3 import SQLiteMetadataStore

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]

_SOURCE_REVISION_KEY = "source_definition_revision_id"


def _source_definition(url: str, *, role: str) -> JsonObject:
    return {
        "description": "fixture source",
        "url": url,
        "kind": "HTTP",
        "tags": ["fixture", role],
        "role": role,
    }


def _record_source_observation(
    repository: Repository,
    *,
    source_id: SourceId,
    payload: bytes,
    observed_at: float,
):
    run_id = repository.start_run(source_ids=(source_id,), started_at=observed_at - 1)
    operation_id = repository.start_operation(
        run_id=run_id,
        source_id=source_id,
        kind="http",
        subject=str(source_id),
        started_at=observed_at - 0.5,
    )
    observation = repository.ingest_bytes(
        f"source:{source_id}",
        payload,
        run_id=run_id,
        operation_id=operation_id,
        source_id=source_id,
        observed_at=observed_at,
    )
    snapshot = repository.record_source_snapshot(
        source_id=source_id,
        run_id=run_id,
        complete=True,
        observed_at=observed_at,
        evidence={"fixture": True},
    )
    repository.finish_operation(operation_id, status="succeeded", finished_at=observed_at + 0.25)
    repository.finish_run(run_id, status="succeeded", finished_at=observed_at + 0.5)
    return run_id, operation_id, observation, snapshot


def test_source_definition_revisions_pin_new_repository_evidence(tmp_path: Path) -> None:
    first_definition = _source_definition("https://example.test/one", role="raw")
    second_definition = _source_definition("https://example.test/two", role="reference")

    with Repository(tmp_path) as repository:
        source_id = repository.register_source("source-a", first_definition)
        first_source = repository.metadata.source(source_id)
        assert first_source is not None
        first_revision_id = first_source.revision_id

        first_run, _first_operation, first_observation, first_snapshot = _record_source_observation(
            repository,
            source_id=source_id,
            payload=b"one",
            observed_at=100.0,
        )
        first_operation = repository.metadata.operations_for_run(first_run)[0]

        repository.register_source(source_id, first_definition)
        unchanged_source = repository.metadata.source(source_id)
        assert unchanged_source is not None
        assert unchanged_source.revision_id == first_revision_id
        assert len(unchanged_source.revisions) == 1

        repository.register_source(source_id, second_definition)
        second_source = repository.metadata.source(source_id)
        assert second_source is not None
        second_revision_id = second_source.revision_id
        assert second_revision_id != first_revision_id
        assert len(second_source.revisions) == 2

        second_run, _second_operation, second_observation, second_snapshot = _record_source_observation(
            repository,
            source_id=source_id,
            payload=b"two",
            observed_at=200.0,
        )
        second_operation = repository.metadata.operations_for_run(second_run)[0]

        assert first_observation.metadata[_SOURCE_REVISION_KEY] == str(first_revision_id)
        assert first_snapshot.evidence[_SOURCE_REVISION_KEY] == str(first_revision_id)
        assert first_operation.parameters[_SOURCE_REVISION_KEY] == str(first_revision_id)
        assert second_observation.metadata[_SOURCE_REVISION_KEY] == str(second_revision_id)
        assert second_snapshot.evidence[_SOURCE_REVISION_KEY] == str(second_revision_id)
        assert second_operation.parameters[_SOURCE_REVISION_KEY] == str(second_revision_id)

        source_payload = RepositoryQueryService(repository).query("source:source-a")
        source = source_payload["source"]
        assert isinstance(source, dict)
        assert source["definition"] == second_definition
        assert source["definition_revision_id"] == str(second_revision_id)
        revisions = source["definition_revisions"]
        assert isinstance(revisions, list)
        assert len(revisions) == 2


def test_dataset_specification_identity_is_distinct_from_membership(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        source_id = repository.register_source("source-a", _source_definition("https://example.test/a", role="raw"))
        run_id = repository.start_run(source_ids=(source_id,), started_at=99.0)
        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source_id,
            kind="http",
            subject="source-a",
            started_at=99.5,
        )
        observation = repository.ingest_bytes(
            "artifact:a",
            b"payload",
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=100.0,
        )
        repository.finish_operation(operation_id, status="succeeded", finished_at=100.5)
        repository.finish_run(run_id, status="succeeded", finished_at=101.0)

        exact_definition = DatasetDefinition.from_selectors(ExactObservation(observation.observation_id))
        latest_definition = DatasetDefinition.from_selectors(Latest("artifact:a"))
        exact = repository.resolve_dataset(exact_definition, created_at=110.0)
        latest = repository.resolve_dataset(latest_definition, created_at=120.0)

        assert exact.id == latest.id
        assert exact.content_identity == latest.content_identity
        assert exact.specification_id != latest.specification_id

        specifications = repository.dataset_specifications(exact.id)
        assert {item.specification_id for item in specifications} == {
            exact.specification_id,
            latest.specification_id,
        }
        expected_canonical = min(str(item.specification_id) for item in specifications)
        canonical = repository.dataset(exact.id)
        assert str(canonical.specification_id) == expected_canonical

        query_payload = RepositoryQueryService(repository).query(f"dataset:{exact.id}")
        serialized = query_payload["specifications"]
        assert isinstance(serialized, list)
        assert len(serialized) == 2

    with Repository(tmp_path) as reopened:
        canonical = reopened.dataset(exact.id)
        assert str(canonical.specification_id) == expected_canonical
        assert len(reopened.dataset_specifications(exact.id)) == 2


def _remove_revision_key(raw: str) -> str:
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        msg = "Fixture expected a JSON object."
        raise TypeError(msg)
    decoded.pop(_SOURCE_REVISION_KEY, None)
    return json.dumps(decoded, sort_keys=True, separators=(",", ":"))


def _downgrade_fixture_to_v2(
    db: Path,
    *,
    source_definition: JsonObject,
    dataset_definition: JsonObject,
) -> None:
    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE sources SET definition_json = ? WHERE source_id = 'source-a'",
        (json.dumps(source_definition, sort_keys=True, separators=(",", ":")),),
    )
    connection.execute(
        "UPDATE datasets SET definition_json = ?",
        (json.dumps(dataset_definition, sort_keys=True, separators=(",", ":")),),
    )
    for table, column in (
        ("operations", "parameters_json"),
        ("observations", "metadata_json"),
        ("source_snapshots", "evidence_json"),
    ):
        rows = connection.execute(f"SELECT rowid, {column} FROM {table}").fetchall()
        for rowid, raw in rows:
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                (_remove_revision_key(raw), rowid),
            )
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()


def test_v2_upgrade_preserves_repository_state_without_inventing_revision_provenance(tmp_path: Path) -> None:
    source_definition = _source_definition("https://example.test/a", role="raw")
    with Repository(tmp_path) as repository:
        source_id = repository.register_source("source-a", source_definition)
        run_id = repository.start_run(source_ids=(source_id,), started_at=99.0)
        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source_id,
            kind="http",
            subject="source-a",
            started_at=99.5,
        )
        first = repository.ingest_bytes(
            "artifact:a",
            b"input",
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=100.0,
        )
        derived = repository.ingest_bytes(
            "artifact:b",
            b"derived",
            run_id=run_id,
            operation_id=operation_id,
            source_id=source_id,
            observed_at=101.0,
            inputs=(first.observation_id,),
        )
        snapshot = repository.record_source_snapshot(
            source_id=source_id,
            run_id=run_id,
            complete=True,
            observed_at=102.0,
            evidence={"fixture": True},
        )
        repository.record_validation(
            ValidationResult(
                content_id=first.content_id,
                validator="test:fixture",
                validator_version="1",
                checked_at=103.0,
                status="passed",
            )
        )
        dataset = repository.resolve_dataset(
            DatasetDefinition.from_selectors(ExactObservation(first.observation_id)),
            created_at=104.0,
        )
        dataset_definition = dict(dataset.manifest.definition)
        repository.finish_operation(operation_id, status="succeeded", finished_at=105.0)
        repository.finish_run(run_id, status="succeeded", finished_at=106.0)

    _downgrade_fixture_to_v2(
        tmp_path / "metadata.sqlite",
        source_definition=source_definition,
        dataset_definition=dataset_definition,
    )

    with Repository(tmp_path) as upgraded:
        metadata = cast("SQLiteMetadataStore", upgraded.metadata)
        assert metadata.schema_version == 3

        source = upgraded.metadata.source(SourceId("source-a"))
        assert source is not None
        assert source.definition == source_definition
        assert len(source.revisions) == 1

        migrated_first = upgraded.observation(first.observation_id)
        assert migrated_first is not None
        assert _SOURCE_REVISION_KEY not in migrated_first.metadata
        migrated_snapshot = upgraded.metadata.source_snapshot(snapshot.snapshot_id)
        assert migrated_snapshot is not None
        assert _SOURCE_REVISION_KEY not in migrated_snapshot.evidence
        migrated_operation = upgraded.metadata.operations_for_run(run_id)[0]
        assert _SOURCE_REVISION_KEY not in migrated_operation.parameters

        assert upgraded.observation(derived.observation_id) is not None
        provenance = upgraded.provenance_inputs(derived.observation_id)
        assert [edge.input_observation_id for edge in provenance] == [first.observation_id]
        validation = upgraded.validation(first.content_id, "test:fixture", "1")
        assert validation is not None
        assert validation.status == "passed"

        migrated_dataset = upgraded.dataset(dataset.id)
        assert migrated_dataset.id == dataset.id
        assert migrated_dataset.artifact("artifact:a").observation_id == first.observation_id
        assert len(upgraded.dataset_specifications(dataset.id)) == 1

    with Repository(tmp_path) as reopened:
        metadata = cast("SQLiteMetadataStore", reopened.metadata)
        assert metadata.schema_version == 3
        source = reopened.metadata.source(SourceId("source-a"))
        assert source is not None
        assert len(source.revisions) == 1


def test_future_schema_version_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "metadata.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA user_version = 99")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="Unsupported efloud metadata schema version: 99"):
        Repository(tmp_path)
