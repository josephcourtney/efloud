from pathlib import Path

import pytest

from efloud.datasets import DatasetDefinition, Latest
from efloud.json_types import JsonMapping, JsonValue, json_mapping_or_none
from efloud.repository import Repository
from efloud.repository_models import SourceId, TreeEntry
from efloud.repository_query import RepositoryQueryService

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def _mapping(value: JsonValue | None) -> JsonMapping:
    mapping = json_mapping_or_none(value)
    assert mapping is not None
    return mapping


def _array(value: JsonValue | None) -> list[JsonValue]:
    assert isinstance(value, list)
    return value


def _seed(repo: Repository):
    source = repo.register_source(SourceId("test-source"), {"kind": "test"})
    run = repo.start_run(source_ids=(source,), started_at=100.0)
    op = repo.start_operation(
        run_id=run,
        source_id=source,
        kind="fetch",
        subject="seed",
        started_at=100.0,
    )
    return source, run, op


def test_artifact_query_reports_present_and_absent_state(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _seed(repo)
        observation = repo.ingest_bytes(
            "artifact:a",
            b"hello",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=101.0,
        )
        query = RepositoryQueryService(repo)
        present = query.query("artifact:artifact:a")
        present_state = _mapping(present.get("state"))
        assert present_state["content_id"] == str(observation.content_id)
        assert len(_array(present.get("history"))) == 1

        repo.record_absence(
            "artifact:a",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=102.0,
        )
        absent = query.query("artifact:artifact:a")
        absent_state = _mapping(absent.get("state"))
        assert absent_state["absent"] is True
        assert len(_array(absent.get("history"))) == 1


def test_artifact_locator_reads_immutable_blob_content(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _seed(repo)
        repo.ingest_bytes(
            "artifact:json",
            b'{"items":[{"name":"alpha"}]}',
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=101.0,
            media_type="application/json",
        )
        payload = RepositoryQueryService(repo).query("artifact:artifact:json#/items/0/name")
        locator = _mapping(payload.get("locator"))
        assert locator["value"] == "alpha"
        assert locator["error"] is None


def test_exact_observation_query_is_independent_of_latest_state(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _seed(repo)
        old = repo.ingest_bytes(
            "artifact:a",
            b"old",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=101.0,
        )
        repo.ingest_bytes(
            "artifact:a",
            b"new",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=102.0,
        )
        payload = RepositoryQueryService(repo).query(f"observation:{old.observation_id}#text")
        observation = _mapping(payload.get("observation"))
        locator = _mapping(payload.get("locator"))
        assert observation["observation_id"] == str(old.observation_id)
        assert locator["value"] == "old"


def test_snapshot_queries_include_tree_entries(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _seed(repo)
        observation = repo.ingest_bytes(
            "artifact:a",
            b"hello",
            run_id=run,
            operation_id=op,
            source_id=source,
            source_path="aa/a.txt",
        )
        snapshot = repo.record_tree_snapshot(
            source_id=source,
            run_id=run,
            entries=(TreeEntry("aa/a.txt", "file", observation.content_id, 5),),
            complete=False,
            scope=("aa/",),
            observed_at=105.0,
        )
        query = RepositoryQueryService(repo)
        exact = query.query(f"snapshot:{snapshot.snapshot_id}")
        exact_snapshot = _mapping(exact.get("snapshot"))
        entries = _array(exact_snapshot.get("entries"))
        first_entry = _mapping(entries[0])
        assert first_entry["path"] == "aa/a.txt"
        latest = query.query(f"source-snapshot:{source}")
        latest_snapshot = _mapping(latest.get("snapshot"))
        assert latest_snapshot["snapshot_id"] == str(snapshot.snapshot_id)


def test_dataset_query_exposes_frozen_membership(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _seed(repo)
        observation = repo.ingest_bytes(
            "artifact:a",
            b"hello",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=101.0,
        )
        dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(Latest("artifact:a")))
        payload = RepositoryQueryService(repo).query(f"dataset:{dataset.id}")
        assert payload["dataset_id"] == str(dataset.id)
        assert payload["members"] == [
            {
                "artifact_key": "artifact:a",
                "observation_id": str(observation.observation_id),
                "content_id": str(observation.content_id),
            }
        ]
