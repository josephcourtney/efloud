from pathlib import Path
from textwrap import dedent

import pytest

from efloud.repository import Repository
from efloud.repository_models import ArtifactAbsence, SourceId
from efloud.rsync_reconciliation import reconcile_rsync_inventory
from efloud.transport.rsync_inventory import (
    RsyncInventory,
    RsyncInventoryEntry,
    parse_rsync_list_only,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.regression,
    # pytest.mark.db,
    # pytest.mark.medium,
]


def _run(repo: Repository, source: SourceId, *, started_at: float):
    run = repo.start_run(source_ids=(source,), started_at=started_at)
    operation = repo.start_operation(
        run_id=run,
        source_id=source,
        kind="rsync",
        subject=str(source),
        started_at=started_at,
    )
    return run, operation


def _file_inventory(
    *,
    modified: str = "2026/09/04 10:00:00",
    scope: tuple[str, ...] = (),
) -> RsyncInventory:
    return RsyncInventory(
        entries=(RsyncInventoryEntry("aa/a.txt", "file", 5, modified),),
        scope=scope,
        complete=True,
    )


@pytest.mark.small
def test_parse_rsync_list_only_preserves_file_tree_metadata() -> None:
    text = dedent(
        """\
        drwxr-xr-x          4,096 2026/09/04 10:00:00 .
        drwxr-xr-x          4,096 2026/09/04 10:00:00 aa
        -rw-r--r--              5 2026/09/04 10:00:00 aa/a.txt
        lrwxrwxrwx              0 2026/09/04 10:00:00 aa/link -> a.txt\
        """
    )

    entries = parse_rsync_list_only(text)
    assert [entry.relative_path for entry in entries] == ["aa", "aa/a.txt", "aa/link"]
    assert entries[1].byte_size == 5
    assert entries[1].modified == "2026/09/04 10:00:00"
    assert entries[2].target == "a.txt"


@pytest.mark.medium
@pytest.mark.db
def test_reconciliation_adds_then_reuses_unchanged_content(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    (mirror / "aa").mkdir(parents=True)
    (mirror / "aa" / "a.txt").write_bytes(b"hello")

    with Repository(tmp_path / "repo") as repo:
        source = repo.register_source(SourceId("rsync-source"), {"kind": "RSYNC"})
        run1, op1 = _run(repo, source, started_at=100.0)
        first = reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run1,
            operation_id=op1,
            local_root=mirror,
            inventory=_file_inventory(),
            observed_at=101.0,
            upstream_root="rsync://example/data",
        )
        assert first.complete is True
        assert first.ingested_file_count == 1
        assert first.reused_content_count == 0
        old = repo.latest_observation("source:rsync-source:path:aa/a.txt")
        assert old is not None

        run2, op2 = _run(repo, source, started_at=200.0)
        second = reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run2,
            operation_id=op2,
            local_root=mirror,
            inventory=_file_inventory(),
            observed_at=201.0,
            upstream_root="rsync://example/data",
        )
        assert second.ingested_file_count == 0
        assert second.reused_content_count == 1
        latest = repo.latest_observation("source:rsync-source:path:aa/a.txt")
        assert latest is not None
        assert latest.observation_id != old.observation_id
        assert latest.content_id == old.content_id
        blob_files = [path for path in (repo.root / "objects").rglob("*") if path.is_file()]
        assert len(blob_files) == 1


@pytest.mark.medium
@pytest.mark.db
def test_reconciliation_records_modification_and_deletion(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    (mirror / "aa").mkdir(parents=True)
    file_path = mirror / "aa" / "a.txt"
    file_path.write_bytes(b"hello")

    with Repository(tmp_path / "repo") as repo:
        source = repo.register_source(SourceId("rsync-source"), {"kind": "RSYNC"})
        run1, op1 = _run(repo, source, started_at=100.0)
        reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run1,
            operation_id=op1,
            local_root=mirror,
            inventory=_file_inventory(),
            observed_at=101.0,
            upstream_root="rsync://example/data",
        )
        old = repo.latest_observation("source:rsync-source:path:aa/a.txt")
        assert old is not None

        file_path.write_bytes(b"world!")
        changed_inventory = RsyncInventory(
            entries=(RsyncInventoryEntry("aa/a.txt", "file", 6, "2026/09/04 11:00:00"),),
            complete=True,
        )
        run2, op2 = _run(repo, source, started_at=200.0)
        changed = reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run2,
            operation_id=op2,
            local_root=mirror,
            inventory=changed_inventory,
            observed_at=201.0,
            upstream_root="rsync://example/data",
        )
        assert changed.ingested_file_count == 1
        current = repo.latest_observation("source:rsync-source:path:aa/a.txt")
        assert current is not None
        assert current.content_id != old.content_id

        file_path.unlink()
        run3, op3 = _run(repo, source, started_at=300.0)
        deleted = reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run3,
            operation_id=op3,
            local_root=mirror,
            inventory=RsyncInventory(entries=(), complete=True),
            observed_at=301.0,
            upstream_root="rsync://example/data",
        )
        assert deleted.absence_count == 1
        assert isinstance(repo.latest_state("source:rsync-source:path:aa/a.txt"), ArtifactAbsence)


@pytest.mark.medium
@pytest.mark.db
def test_partial_scope_can_prove_absence_only_within_same_scope(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    (mirror / "aa").mkdir(parents=True)
    file_path = mirror / "aa" / "a.txt"
    file_path.write_bytes(b"hello")
    scope = ("aa/",)

    with Repository(tmp_path / "repo") as repo:
        source = repo.register_source(SourceId("rsync-source"), {"kind": "RSYNC"})
        run1, op1 = _run(repo, source, started_at=100.0)
        first = reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run1,
            operation_id=op1,
            local_root=mirror,
            inventory=_file_inventory(scope=scope),
            observed_at=101.0,
            upstream_root="rsync://example/data",
        )
        snapshot = repo.latest_source_snapshot(source)
        assert first.complete is True
        assert snapshot is not None
        assert snapshot.complete is False
        assert snapshot.scope == scope
        assert snapshot.evidence["scope_complete"] is True

        file_path.unlink()
        run2, op2 = _run(repo, source, started_at=200.0)
        second = reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run2,
            operation_id=op2,
            local_root=mirror,
            inventory=RsyncInventory(entries=(), scope=scope, complete=True),
            observed_at=201.0,
            upstream_root="rsync://example/data",
        )
        assert second.absence_count == 1
        assert isinstance(repo.latest_state("source:rsync-source:path:aa/a.txt"), ArtifactAbsence)


@pytest.mark.medium
@pytest.mark.db
def test_incomplete_inventory_never_emits_absence(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror"
    (mirror / "aa").mkdir(parents=True)
    file_path = mirror / "aa" / "a.txt"
    file_path.write_bytes(b"hello")

    with Repository(tmp_path / "repo") as repo:
        source = repo.register_source(SourceId("rsync-source"), {"kind": "RSYNC"})
        run1, op1 = _run(repo, source, started_at=100.0)
        reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run1,
            operation_id=op1,
            local_root=mirror,
            inventory=_file_inventory(),
            observed_at=101.0,
            upstream_root="rsync://example/data",
        )
        old = repo.latest_state("source:rsync-source:path:aa/a.txt")
        file_path.unlink()

        run2, op2 = _run(repo, source, started_at=200.0)
        incomplete = reconcile_rsync_inventory(
            repo,
            source_id=source,
            run_id=run2,
            operation_id=op2,
            local_root=mirror,
            inventory=RsyncInventory(entries=(), complete=False, error="enumeration failed"),
            observed_at=201.0,
            upstream_root="rsync://example/data",
        )
        assert incomplete.complete is False
        assert incomplete.absence_count == 0
        assert repo.latest_state("source:rsync-source:path:aa/a.txt") == old
        snapshot = repo.latest_source_snapshot(source)
        assert snapshot is not None
        assert snapshot.evidence["reconciliation_complete"] is False
