import hashlib
import io
import sqlite3
from pathlib import Path

import pytest

from efloud.catalog.memory import MemoryCatalog
from efloud.content.protocol import AnnexKey
from efloud.datasets import DatasetDefinition, ExactObservation, Latest, LatestAll, LatestBefore
from efloud.inventory import AbsenceEvidence
from efloud.json_types import json_mapping_or_none
from efloud.repository import Repository
from efloud.repository_models import (
    ArtifactAbsence,
    ContentId,
    ContentRef,
    SourceId,
    TreeEntry,
    ValidationResult,
)
from efloud.tree.protocol import GitCommitId, GitTreeEntry, GitTreeId, TreeBlob

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


class _MemoryContentStore:
    """Small in-process content store for storage-independent repository tests."""

    def __init__(self) -> None:
        self._content: dict[AnnexKey, bytes] = {}

    @staticmethod
    def _key(data: bytes) -> AnnexKey:
        return AnnexKey(f"test-sha256:{hashlib.sha256(data).hexdigest()}")

    def ingest_path(self, path: Path) -> AnnexKey:
        return self.ingest_bytes(path.read_bytes())

    def ingest_bytes(self, data: bytes) -> AnnexKey:
        key = self._key(data)
        self._content[key] = bytes(data)
        return key

    def ingest_url(self, url: str) -> AnnexKey:
        msg = f"unexpected URL ingestion: {url}"
        raise AssertionError(msg)

    def content_ref(self, key: AnnexKey, *, media_type: str | None = None) -> ContentRef:
        data = self._content[key]
        return ContentRef(
            content_id=ContentId(f"sha256:{hashlib.sha256(data).hexdigest()}"),
            byte_size=len(data),
            custody_key=str(key),
            media_type=media_type,
        )

    def has_content(self, key: AnnexKey) -> bool:
        return key in self._content

    def open(self, key: AnnexKey) -> io.BytesIO:
        return io.BytesIO(self._content[key])

    def verify(self, key: AnnexKey) -> bool:
        data = self._content.get(key)
        return data is not None and self._key(data) == key

    def present_keys(self) -> tuple[AnnexKey, ...]:
        return tuple(sorted(self._content, key=str))

    def custody_mtime(self, key: AnnexKey) -> float:
        if key not in self._content:
            raise KeyError(key)
        return 0.0

    def drop_key(self, key: AnnexKey) -> None:
        self._content.pop(key, None)

    def register_url(self, key: AnnexKey, url: str) -> None:
        del key, url

    def get(self, key: AnnexKey) -> None:
        if key not in self._content:
            raise KeyError(key)


class _MemoryTreeStore:
    """Small in-process tree store for catalog-boundary repository tests."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._trees: dict[str, tuple[GitTreeEntry, ...]] = {}

    def write_tree(self, entries: tuple[TreeBlob, ...]) -> GitTreeId:
        listed: list[GitTreeEntry] = []
        digest = hashlib.sha256()
        for entry in entries:
            object_id = hashlib.sha256(entry.data).hexdigest()
            self._blobs[object_id] = bytes(entry.data)
            listed.append(GitTreeEntry(entry.relative_path, entry.mode, "blob", object_id))
            digest.update(entry.relative_path.encode())
            digest.update(b"\0")
            digest.update(entry.mode.encode())
            digest.update(b"\0")
            digest.update(object_id.encode())
            digest.update(b"\0")
        tree_id = GitTreeId(digest.hexdigest())
        self._trees[str(tree_id)] = tuple(listed)
        return tree_id

    def list_tree(self, treeish: GitTreeId | GitCommitId | str) -> tuple[GitTreeEntry, ...]:
        return self._trees[str(treeish)]

    def read_blob(self, object_id: str) -> bytes:
        return self._blobs[object_id]

    def commit_tree(self, tree: GitTreeId, *, ref: str, message: str) -> GitCommitId:
        digest = hashlib.sha256(f"{tree}\0{ref}\0{message}".encode()).hexdigest()
        return GitCommitId(digest)


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
        assert repo.contains_content(first.content_id)


def test_semantic_repository_slice_accepts_memory_catalog(tmp_path: Path) -> None:
    with Repository(
        tmp_path,
        metadata_store=MemoryCatalog(),
        content_store=_MemoryContentStore(),
        tree_store=_MemoryTreeStore(),
    ) as repo:
        source, run, operation = _run(repo)
        observation = repo.ingest_bytes(
            "artifact:a",
            b"hello",
            run_id=run,
            operation_id=operation,
            source_id=source,
            observed_at=101.0,
        )
        assert repo.source(source) is not None
        assert repo.run(run) is not None
        assert repo.operation(operation) is not None
        assert repo.observation(observation.observation_id) == observation
        assert repo.content(observation.content_id) is not None
        assert repo.latest_observation("artifact:a") == observation
        assert repo.verify_content(observation.content_id)


def test_memory_catalog_repository_uses_injected_tree_store(tmp_path: Path) -> None:
    with Repository(
        tmp_path,
        metadata_store=MemoryCatalog(),
        content_store=_MemoryContentStore(),
        tree_store=_MemoryTreeStore(),
    ) as repo:
        source, run, _operation = _run(repo)
        snapshot = repo.record_tree_snapshot(
            source_id=source,
            run_id=run,
            entries=(),
            complete=True,
            scope=(),
            observed_at=101.0,
        )
        assert snapshot.tree_id is not None
        assert repo.tree_entries(snapshot.tree_id) == ()
        assert repo.latest_source_snapshot(source) == snapshot


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
        old_dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(ExactObservation(first.observation_id)))
        new_dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(ExactObservation(second.observation_id)))
        assert old_dataset.id != new_dataset.id
        assert old_dataset.content_identity == new_dataset.content_identity
        assert old_dataset.verify()
        with new_dataset.open("artifact:a") as stream:
            assert stream.read() == b"hello"


def test_latest_before_dataset_selection(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        source, run, op = _run(repo)
        old = repo.ingest_bytes("artifact:a", b"old", run_id=run, operation_id=op, source_id=source, observed_at=101.0)
        repo.ingest_bytes("artifact:a", b"new", run_id=run, operation_id=op, source_id=source, observed_at=103.0)
        dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(LatestBefore("artifact:a", 102.0)))
        assert dataset.artifact("artifact:a").observation_id == old.observation_id
        latest = repo.resolve_dataset(DatasetDefinition.from_selectors(Latest("artifact:a")))
        assert latest.artifact("artifact:a").observation_id != old.observation_id


def test_validation_requires_known_content(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo, pytest.raises(sqlite3.IntegrityError):
        repo.record_validation(
            ValidationResult(
                content_id=ContentId("sha256:" + "0" * 64),
                validator="test",
                validator_version="1",
                checked_at=1.0,
                status="passed",
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
            evidence=AbsenceEvidence.direct_negative(
                source_id=source,
                observed_at=102.0,
                locator="test://artifact/a",
            ),
            run_id=run,
            operation_id=op,
        )
        evidence = json_mapping_or_none(absence.metadata.get("absence_evidence"))
        assert evidence is not None
        assert evidence["kind"] == "direct-negative"
        assert isinstance(repo.latest_state("artifact:a"), ArtifactAbsence)
        assert repo.latest_state("artifact:a", before=101.5) == old
        with pytest.raises(KeyError):
            repo.resolve_dataset(DatasetDefinition.from_selectors(Latest("artifact:a")))
        dataset = repo.resolve_dataset(DatasetDefinition.from_selectors(LatestAll()))
        assert dataset.artifacts() == ()
        assert absence.observation_id != old.observation_id


def test_schema_v1_is_rejected_without_migration(tmp_path: Path) -> None:
    db = tmp_path / "metadata.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE sentinel(value TEXT)")
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    with pytest.raises(
        RuntimeError,
        match=r"Unsupported efloud metadata schema version: 1; expected 4",
    ):
        Repository(tmp_path)

    connection = sqlite3.connect(db)
    try:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 1
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert names == {"sentinel"}
    finally:
        connection.close()


def test_dataset_identity_is_independent_of_repository_location(tmp_path: Path) -> None:
    def resolve_at(root: Path) -> tuple[str, str]:
        with Repository(root) as repo:
            source, run, op = _run(repo)
            observation = repo.ingest_bytes(
                "artifact:a",
                b"hello",
                run_id=run,
                operation_id=op,
                source_id=source,
                observed_at=101.0,
            )
            dataset = repo.resolve_dataset(
                DatasetDefinition.from_selectors(ExactObservation(observation.observation_id))
            )
            return str(dataset.id), dataset.content_identity

    left_id, left_content = resolve_at(tmp_path / "left")
    right_id, right_content = resolve_at(tmp_path / "right")

    assert left_id == right_id
    assert left_content == right_content
