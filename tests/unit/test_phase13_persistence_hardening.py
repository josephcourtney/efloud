from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from efloud.datasets import DatasetDefinition, ExactObservation, Latest
from efloud.repository import Repository
from efloud.repository_models import SourceId

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.json_types import JsonObject
    from efloud.repository_models import SourceDefinitionRevisionId

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]

_SOURCE_REVISION_KEY = "source_definition_revision_id"


def _source_definition(url: str, *, role: str) -> JsonObject:
    return {
        "adapter_id": "efloud:http",
        "description": "fixture source",
        "url": url,
        "protocol": "http",
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


def _record_and_assert_revision_evidence(
    repository: Repository,
    *,
    source_id: SourceId,
    payload: bytes,
    observed_at: float,
    revision_id: SourceDefinitionRevisionId,
) -> None:
    run_id, _operation_id, observation, snapshot = _record_source_observation(
        repository,
        source_id=source_id,
        payload=payload,
        observed_at=observed_at,
    )
    operation = repository.metadata.operations_for_run(run_id)[0]

    assert observation.metadata[_SOURCE_REVISION_KEY] == str(revision_id)
    assert snapshot.evidence[_SOURCE_REVISION_KEY] == str(revision_id)
    assert operation.parameters[_SOURCE_REVISION_KEY] == str(revision_id)


def test_source_definition_revisions_pin_new_repository_evidence(tmp_path: Path) -> None:
    first_definition = _source_definition("https://example.test/one", role="raw")
    second_definition = _source_definition("https://example.test/two", role="reference")

    with Repository(tmp_path) as repository:
        source_id = repository.register_source("source-a", first_definition)
        first_source = repository.metadata.source(source_id)
        assert first_source is not None
        first_revision_id = first_source.revision_id

        _record_and_assert_revision_evidence(
            repository,
            source_id=source_id,
            payload=b"one",
            observed_at=100.0,
            revision_id=first_revision_id,
        )

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
        assert second_source.definition == second_definition
        assert len(second_source.revisions) == 2

        _record_and_assert_revision_evidence(
            repository,
            source_id=source_id,
            payload=b"two",
            observed_at=200.0,
            revision_id=second_revision_id,
        )


def test_dataset_specification_identity_is_distinct_from_membership(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        source_id = repository.register_source(
            "source-a",
            _source_definition("https://example.test/a", role="raw"),
        )
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

    with Repository(tmp_path) as reopened:
        canonical = reopened.dataset(exact.id)
        assert str(canonical.specification_id) == expected_canonical
        assert len(reopened.dataset_specifications(exact.id)) == 2


@pytest.mark.parametrize("version", [1, 2, 99])
def test_noncurrent_schema_versions_are_rejected(tmp_path: Path, version: int) -> None:
    db = tmp_path / "metadata.sqlite"
    connection = sqlite3.connect(db)
    connection.execute(f"PRAGMA user_version = {version}")
    connection.commit()
    connection.close()

    with pytest.raises(
        RuntimeError,
        match=rf"Unsupported efloud metadata schema version: {version}",
    ):
        Repository(tmp_path)


def test_nonempty_unversioned_database_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "metadata.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE historical_alpha_state (value TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="Unsupported unversioned efloud metadata database"):
        Repository(tmp_path)
