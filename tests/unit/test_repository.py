import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from efloud.datasets import DatasetDefinition, ExactObservation, Latest, LatestAll, LatestBefore
from efloud.repository import Repository
from efloud.repository_models import ArtifactAbsence, ContentId, SourceId, TreeEntry, ValidationResult

if TYPE_CHECKING:
    from efloud.sqlite_metadata import SQLiteMetadataStore

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def _run(repo: Repository):
    source = repo.register_source(SourceId("test-source"), {"kind": "test"})
    run = repo.start_run(source_ids=(source,), started_at=100.0)
    op = repo.start_operation(run_id=run, source_id=source, kind="fetch", subject="a", started_at=100.0)
    return source, run, op


def test_content_dedup_and_observation_history(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _run(repo)
        first = repo.ingest_bytes(
            "artifact:a",
            b"hello",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=101.0,
        )
        second = repo.ingest_bytes(
            "artifact:a",
            b"hello",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=102.0,
        )
        assert first.content_id == second.content_id
        assert first.observation_id != second.observation_id
        assert len(repo.observations_for("artifact:a")) == 2
        assert repo.latest_observation("artifact:a") == second
        assert repo.verify_content(first.content_id)
        blob_files = [p for p in (tmp_path / "objects").rglob("*") if p.is_file()]
        assert len(blob_files) == 1


def test_repository_survives_reopen(tmp_path: Path) -> None:
    repo = Repository(tmp_path)
    source, run, op = _run(repo)
    obs = repo.ingest_bytes("artifact:a", b"hello", run_id=run, operation_id=op, source_id=source)
    repo.close()

    with Repository(tmp_path) as reopened:
        loaded = reopened.observation(obs.observation_id)
        assert loaded is not None
        assert loaded.content_id == obs.content_id
        with reopened.open_content(obs.content_id) as stream:
            assert stream.read() == b"hello"


def test_partial_tree_snapshot_retains_scope(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _run(repo)
        obs = repo.ingest_bytes(
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
            entries=(TreeEntry("aa/a.txt", "file", obs.content_id, 5),),
            complete=False,
            scope=("aa/",),
            observed_at=105.0,
        )
        assert snapshot.complete is False
        assert snapshot.scope == ("aa/",)
        assert snapshot.tree_id is not None
        assert repo.tree_entries(snapshot.tree_id)[0].relative_path == "aa/a.txt"
        assert repo.latest_source_snapshot(source) == snapshot


def test_dataset_exact_and_content_equivalence(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _run(repo)
        first = repo.ingest_bytes(
            "artifact:a", b"hello", run_id=run, operation_id=op, source_id=source, observed_at=101.0
        )
        second = repo.ingest_bytes(
            "artifact:a", b"hello", run_id=run, operation_id=op, source_id=source, observed_at=102.0
        )
        old_dataset = repo.resolve_dataset(
            DatasetDefinition.from_selectors(ExactObservation(first.observation_id))
        )
        new_dataset = repo.resolve_dataset(
            DatasetDefinition.from_selectors(ExactObservation(second.observation_id))
        )
        assert old_dataset.id != new_dataset.id
        assert old_dataset.content_identity == new_dataset.content_identity
        assert old_dataset.verify()
        with new_dataset.open("artifact:a") as stream:
            assert stream.read() == b"hello"


def test_latest_before_dataset_selection(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _run(repo)
        old = repo.ingest_bytes(
            "artifact:a", b"old", run_id=run, operation_id=op, source_id=source, observed_at=101.0
        )
        repo.ingest_bytes(
            "artifact:a", b"new", run_id=run, operation_id=op, source_id=source, observed_at=103.0
        )
        dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(LatestBefore("artifact:a", 102.0)))
        assert dataset.artifact("artifact:a").observation_id == old.observation_id
        latest = repo.resolve_dataset(DatasetDefinition.from_selectors(Latest("artifact:a")))
        assert latest.artifact("artifact:a").observation_id != old.observation_id


def test_dataset_verification_detects_blob_corruption(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _run(repo)
        obs = repo.ingest_bytes("artifact:a", b"hello", run_id=run, operation_id=op, source_id=source)
        dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(Latest("artifact:a")))
        repo.blobs.path_for(obs.content_id).write_bytes(b"corrupt")
        assert dataset.verify() is False


def test_validation_requires_known_content(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo, pytest.raises(sqlite3.IntegrityError):
        repo.record_validation(
            ValidationResult(
                content_id=ContentId("sha256:" + "0" * 64),
                validator="test",
                validator_version="1",
                checked_at=1.0,
                status="pass",
            )
        )


def test_absence_hides_latest_artifact_but_preserves_history(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _run(repo)
        old = repo.ingest_bytes(
            "artifact:a",
            b"hello",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=101.0,
        )
        absence = repo.record_absence(
            "artifact:a",
            run_id=run,
            operation_id=op,
            source_id=source,
            observed_at=102.0,
        )
        assert isinstance(repo.latest_state("artifact:a"), ArtifactAbsence)
        assert repo.latest_state("artifact:a", before=101.5) == old
        with pytest.raises(KeyError):
            repo.resolve_dataset(DatasetDefinition.from_selectors(Latest("artifact:a")))
        dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(LatestAll()))
        assert dataset.artifacts() == ()
        assert absence.observation_id != old.observation_id


def test_schema_v1_migrates_to_absence_capable_v2(tmp_path: Path) -> None:
    db = tmp_path / "metadata.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE sentinel(value TEXT)")
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    # A v1 database receives the additive v2 tables without losing existing data.
    with Repository(tmp_path) as repo:
        metadata = cast("SQLiteMetadataStore", repo.metadata)
        version = metadata._connection.execute("PRAGMA user_version").fetchone()[0]
        assert version == 2
        names = {
            row[0]
            for row in metadata._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "artifact_absences" in names
        assert "sentinel" in names
