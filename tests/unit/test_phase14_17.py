"""Integration acceptance for frozen datasets, handoff, and local durability."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

import efloud.materialization as materialization_module
from efloud.dataset_constraints import DatasetConstraintError, DatasetConstraints
from efloud.dataset_export import DetachedDatasetManifest, export_dataset_manifest, import_dataset_manifest
from efloud.dataset_selectors import ExactSourceSnapshot, LatestCompleteSourceSnapshot, SourceSelection
from efloud.datasets import (
    DatasetDefinition,
    DatasetSelection,
    ExactObservation,
    Latest,
    resolve_dataset,
)
from efloud.maintenance import RepositoryMaintenance
from efloud.materialization import DatasetMaterializer
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository import Repository
from efloud.repository_models import TreeEntry, ValidationResult
from efloud.sqlite_metadata import SQLiteMetadataStore
from efloud.writer_coordination import RepositoryBusyError

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.materialization import ExportStrategy
    from efloud.repository_models import ArtifactObservation, SourceSnapshot

pytestmark = [pytest.mark.medium, pytest.mark.integration, pytest.mark.regression, pytest.mark.timeout(30)]


def _record(
    repository: Repository, *, when: float = 1.0, data: bytes = b"first", complete: bool = True
) -> tuple[ArtifactObservation, SourceSnapshot]:
    repository.register_source("source", {"role": "reference", "tags": ["stable"]})
    run = repository.start_run(source_ids=("source",), started_at=when)
    operation = repository.start_operation(run_id=run, kind="fixture", subject="source", started_at=when)
    observation = repository.ingest_bytes(
        "namespace:item",
        data,
        run_id=run,
        operation_id=operation,
        source_id="source",
        observed_at=when,
        source_path="item.txt",
    )
    snapshot = repository.record_tree_snapshot(
        source_id="source",
        run_id=run,
        entries=(TreeEntry("item.txt", "file", observation.content_id, len(data)),),
        complete=complete,
        observed_at=when,
    )
    repository.finish_operation(operation, status="succeeded", finished_at=when)
    repository.finish_run(run, status="succeeded", finished_at=when)
    return observation, snapshot


def test_snapshot_reopens_elsewhere_and_ignores_later_mutation(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    with Repository(root) as repository:
        first, snapshot = _record(repository)
        dataset = repository.resolve_dataset(
            DatasetDefinition.from_selectors(ExactSourceSnapshot(str(snapshot.snapshot_id)))
        )
        detached = export_dataset_manifest(dataset, paths={"namespace:item": "data/item.txt"})
        original = detached.to_bytes()
        _record(repository, when=2.0, data=b"second")
        repository.register_source("source", {"role": "other", "tags": []})
        assert dataset.open("namespace:item").read() == b"first"
        assert export_dataset_manifest(dataset, paths={"namespace:item": "data/item.txt"}).to_bytes() == original
        assert SourceSelection(role="reference", tags=("stable",), before=1.0).resolve(repository) == (first,)
        assert SourceSelection(source_id="missing").resolve(repository) == ()
        assert SourceSelection(prefix="different").resolve(repository) == ()
        assert SourceSelection(after=3.0).resolve(repository) == ()
        assert SourceSelection(after=1.0, before=1.0).resolve(repository) == (first,)
        dataset_id = dataset.id
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(root, elsewhere)
    before = (elsewhere / "metadata.sqlite").read_bytes()
    with ReadOnlyRepository(elsewhere) as repository:
        imported = import_dataset_manifest(repository, DetachedDatasetManifest.from_bytes(original))
        assert imported.id == dataset_id
        assert imported.artifacts() == repository.dataset(dataset_id).artifacts()
        assert imported.verify()
        assert imported.open("namespace:item").read() == b"first"
    assert (elsewhere / "metadata.sqlite").read_bytes() == before


def test_partial_snapshots_never_become_complete_datasets(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        first, complete = _record(repository)
        _, partial = _record(repository, when=2.0, complete=False)
        with pytest.raises(ValueError, match="complete membership"):
            ExactSourceSnapshot(str(partial.snapshot_id)).resolve(repository)
        assert LatestCompleteSourceSnapshot("source").resolve(repository) == (first,)
        assert LatestCompleteSourceSnapshot("source", before=1.0).snapshot(repository) == complete
        with pytest.raises(KeyError):
            LatestCompleteSourceSnapshot("source", before=0.0).resolve(repository)
        with pytest.raises(KeyError):
            ExactSourceSnapshot("unknown").resolve(repository)
        with pytest.raises(ValueError, match="reversed"):
            SourceSelection(after=2.0, before=1.0).resolve(repository)


def test_constraints_use_only_recorded_evidence(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        first, _ = _record(repository)
        selection = DatasetSelection(ExactObservation(first.observation_id))
        constraints = DatasetConstraints(
            same_run=True, max_observation_skew=0.0, complete_snapshots=True, validations=(("test:validator", "1"),)
        )
        definition = DatasetDefinition((selection,), constraints=constraints)
        with pytest.raises(DatasetConstraintError) as caught:
            resolve_dataset(repository, definition)
        assert any(result["constraint"] == "validation" and not result["passed"] for result in caught.value.results)
        repository.record_validation(ValidationResult(first.content_id, "test:validator", "1", 1.0, "passed"))
        assert resolve_dataset(repository, definition).members[0].observation_id == first.observation_id
        later, _ = _record(repository, when=5.0)
        with pytest.raises(DatasetConstraintError):
            DatasetConstraints(same_run=True, max_observation_skew=1.0).check(repository, (first, later))
        assert DatasetConstraints().check(repository, ()) == ()


@pytest.mark.parametrize("strategy", ["copy", "auto", "symlink", "reflink"])
def test_materialization_is_detached_deterministic_and_read_only(tmp_path: Path, strategy: ExportStrategy) -> None:
    root = tmp_path / "repository"
    with Repository(root) as repository:
        observation, _ = _record(repository)
        dataset_id = repository.resolve_dataset(DatasetDefinition.from_selectors(Latest("namespace:item"))).id
    before = (root / "metadata.sqlite").read_bytes()
    with ReadOnlyRepository(root) as repository:
        manifest = export_dataset_manifest(repository.dataset(dataset_id))
        materializer = DatasetMaterializer(repository)
        destination = tmp_path / "export"
        plan = materializer.export(manifest, destination, strategy=strategy, dry_run=True)
        assert plan.destination == destination
        assert not destination.exists()
        materializer.export(manifest, destination, strategy=strategy)
        assert manifest.verify(destination)
        assert (destination / "dataset-manifest.json").read_bytes() == manifest.to_bytes()
        materializer.export(manifest, tmp_path / "again", strategy=strategy)
        assert (tmp_path / "again/dataset-manifest.json").read_bytes() == manifest.to_bytes()
        (destination / manifest.members[0].path).write_bytes(b"changed")
        assert not manifest.verify(destination)
        assert repository.verify_content(observation.content_id)
        with pytest.raises(FileExistsError):
            materializer.export(manifest, destination)
        with pytest.raises(ValueError, match="outside"):
            materializer.plan(manifest, root / "export")
    assert (root / "metadata.sqlite").read_bytes() == before


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "a/../b", "a//b", "a\\b", "C:evil", "dataset-manifest.json", ".content/a"]
)
def test_materialization_rejects_unsafe_layout_before_writing(tmp_path: Path, path: str) -> None:
    with Repository(tmp_path / "repository") as repository:
        _record(repository)
        dataset = repository.resolve_dataset(DatasetDefinition.from_selectors(Latest("namespace:item")))
        with pytest.raises(ValueError, match="path"):
            _unsafe_export(repository, dataset, path, tmp_path / "export")
        assert not (tmp_path / "export").exists()


def _unsafe_export(repository, dataset, path, destination):
    manifest = export_dataset_manifest(dataset, paths={"namespace:item": path})
    DatasetMaterializer(repository).export(manifest, destination)


def test_manifest_damage_and_wrong_repository_fail_closed(tmp_path: Path) -> None:
    with Repository(tmp_path / "repository") as repository:
        _record(repository)
        dataset = repository.resolve_dataset(DatasetDefinition.from_selectors(Latest("namespace:item")))
        manifest = export_dataset_manifest(dataset)
        damaged = json.loads(manifest.to_bytes())
        damaged["members"][0]["byte_size"] += 1
        with pytest.raises(ValueError, match="damaged"):
            DetachedDatasetManifest.from_bytes(json.dumps(damaged).encode())
        with pytest.raises(ValueError, match="identity"):
            replace(manifest, dataset_id="wrong").validate()
        with pytest.raises(ValueError, match="identity"):
            replace(manifest, members=(replace(manifest.members[0], content_id="invalid"),)).validate()
    with Repository(tmp_path / "empty") as empty, pytest.raises(ValueError, match="cannot be verified"):
        import_dataset_manifest(empty, manifest)


def test_export_copy_failure_does_not_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with Repository(tmp_path / "repository") as repository:
        _record(repository)
        manifest = export_dataset_manifest(
            repository.resolve_dataset(DatasetDefinition.from_selectors(Latest("namespace:item")))
        )

        def fail(*args: object, **kwargs: object) -> None:
            del args, kwargs
            msg = "injected read failure"
            raise OSError(msg)

        monkeypatch.setattr(repository, "open_content", fail)
        with pytest.raises(OSError, match="injected"):
            DatasetMaterializer(repository).export(manifest, tmp_path / "export", strategy="copy")
        assert sorted(path.name for path in tmp_path.iterdir()) == ["repository"]


def test_blob_before_metadata_commit_is_a_safe_orphan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with Repository(tmp_path) as repository:
        run = repository.start_run(started_at=1.0)
        operation = repository.start_operation(run_id=run, kind="fixture", subject="interrupted", started_at=1.0)

        def fail(*args: object, **kwargs: object) -> None:
            del args, kwargs
            msg = "metadata crash"
            raise RuntimeError(msg)

        monkeypatch.setattr(SQLiteMetadataStore, "record_observation_bundle", fail)
        with pytest.raises(RuntimeError, match="metadata crash"):
            repository.ingest_bytes("orphan", b"orphan", run_id=run, operation_id=operation)
        assert repository.artifact_keys() == ()
    maintenance = RepositoryMaintenance(tmp_path)
    assert "orphan-blob" in {issue.code for issue in maintenance.fsck().issues}
    for path in (tmp_path / "objects").glob("sha256/*/*"):
        os.utime(path, (1.0, 1.0))
    assert maintenance.cleanup(now=2.0, grace_period=2.0) == ()
    proposed = maintenance.cleanup(now=10.0, grace_period=1.0)
    assert proposed[0].reason == "orphan-blob"
    assert (tmp_path / proposed[0].path).is_file()
    assert maintenance.cleanup(now=10.0, grace_period=1.0, dry_run=False) == proposed
    assert not (tmp_path / proposed[0].path).exists()
    assert maintenance.recover(finished_at=10.0)
    assert maintenance.recover(finished_at=10.0, dry_run=False)
    assert maintenance.recover(finished_at=10.0, dry_run=False) == ()
    assert maintenance.fsck().ok


def test_interrupted_snapshot_recovery_preserves_content_and_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Repository(tmp_path) as repository:

        def fail(*args: object, **kwargs: object) -> None:
            del args, kwargs
            msg = "snapshot crash"
            raise RuntimeError(msg)

        with monkeypatch.context() as scoped:
            scoped.setattr(SQLiteMetadataStore, "record_source_snapshot", fail)
            with pytest.raises(RuntimeError, match="snapshot crash"):
                _record(repository)
        assert repository.latest_observation("namespace:item") is not None
        with pytest.raises(KeyError):
            LatestCompleteSourceSnapshot("source").resolve(repository)
    maintenance = RepositoryMaintenance(tmp_path)
    assert maintenance.cleanup(now=100.0, grace_period=0.0) == ()
    maintenance.recover(finished_at=10.0, dry_run=False)
    with Repository(tmp_path) as repository:
        _, snapshot = _record(repository, when=20.0)
        assert ExactSourceSnapshot(str(snapshot.snapshot_id)).resolve(repository)
    assert maintenance.fsck().ok


def test_writer_and_maintenance_coordination(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        _record(repository)
        with pytest.raises(RepositoryBusyError), Repository(tmp_path):
            pass
        maintenance = RepositoryMaintenance(tmp_path)
        with pytest.raises(RepositoryBusyError):
            maintenance.cleanup(now=10.0, grace_period=0.0, dry_run=False)
        with pytest.raises(RepositoryBusyError):
            maintenance.recover(finished_at=10.0, dry_run=False)
        assert maintenance.fsck().ok
    with Repository(tmp_path) as reopened:
        assert reopened.artifact_keys()


def test_fsck_detects_corruption_and_cleanup_preserves_validation_only_content(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        observation, _ = _record(repository)
        path = tmp_path / "validation-input"
        path.write_bytes(b"validation only")
        content = repository.store_path_content(path)
        repository.record_validation(ValidationResult(content.content_id, "test:validator", "1", 1.0, "failed"))
        repository.resolve_dataset(DatasetDefinition.from_selectors(Latest("namespace:item")))
    maintenance = RepositoryMaintenance(tmp_path)
    assert maintenance.fsck().ok
    assert dict(maintenance.fsck().reachability)[str(content.content_id)] == ("validations",)
    assert maintenance.cleanup(now=10**12, grace_period=0.0, dry_run=False) == ()
    digest = str(observation.content_id).removeprefix("sha256:")
    blob = tmp_path / "objects/sha256" / digest[:2] / digest
    blob.write_bytes(b"corrupted")
    assert "corrupt-blob" in {issue.code for issue in maintenance.fsck().issues}
    blob.unlink()
    assert "missing-blob" in {issue.code for issue in maintenance.fsck().issues}
    with closing(sqlite3.connect(tmp_path / "metadata.sqlite")) as connection, connection:
        connection.execute("UPDATE observations SET source_id = 'missing'")
    assert "dangling-reference" in {issue.code for issue in maintenance.fsck().issues}


def test_writer_exclusion_across_processes_and_crash_release(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from efloud.repository import Repository
from efloud.writer_coordination import RepositoryBusyError

try:
    with Repository(Path(sys.argv[1])):
        pass
except RepositoryBusyError:
    print("busy")
else:
    print("available")
"""
    with Repository(tmp_path):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "busy"
    crash = """
import os
import sys
from pathlib import Path
from efloud.repository import Repository

repository = Repository(Path(sys.argv[1]))
run = repository.start_run(started_at=1.0)
operation = repository.start_operation(
    run_id=run,
    kind="fixture",
    subject="crash",
    started_at=1.0,
)
repository.ingest_bytes(
    "crashed",
    b"durable",
    run_id=run,
    operation_id=operation,
    observed_at=1.0,
)
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", crash, str(tmp_path)], check=True)
    maintenance = RepositoryMaintenance(tmp_path)
    assert maintenance.recover(finished_at=5.0, dry_run=False)
    assert maintenance.fsck().ok
    with Repository(tmp_path) as repository:
        observation = repository.latest_observation("crashed")
        assert observation is not None
        assert repository.verify_content(observation.content_id)


def test_cleanup_unreferenced_rows_and_closed_writer_guard(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    path = tmp_path / "unused-input"
    path.write_bytes(b"unused")
    content = repository.store_path_content(path)
    repository.close()
    with pytest.raises(RuntimeError, match="closed"):
        repository.store_path_content(path)
    with pytest.raises(RuntimeError, match="closed"):
        repository.store_bytes_content(b"unused")
    maintenance = RepositoryMaintenance(tmp_path)
    assert maintenance.fsck().issues[0].code == "unreferenced-content"
    candidates = maintenance.cleanup(now=10**12, grace_period=0.0, dry_run=False)
    assert candidates[0].content_id == content.content_id
    assert maintenance.fsck().ok


def test_layout_collisions_and_symlink_escape_are_rejected(tmp_path: Path) -> None:
    with Repository(tmp_path / "repository") as repository:
        observation, _ = _record(repository)
        run = repository.start_run(started_at=2.0)
        operation = repository.start_operation(run_id=run, kind="fixture", subject="second", started_at=2.0)
        second = repository.ingest_bytes("second", b"second", run_id=run, operation_id=operation, observed_at=2.0)
        dataset = repository.resolve_dataset(
            DatasetDefinition.from_selectors(
                ExactObservation(observation.observation_id), ExactObservation(second.observation_id)
            )
        )
        for paths in (("a", "a"), ("a", "a/b"), ("File", "file")):
            manifest = export_dataset_manifest(
                dataset, paths=dict(zip(("namespace:item", "second"), paths, strict=True))
            )
            with pytest.raises(ValueError, match="collision"):
                DatasetMaterializer(repository).plan(manifest, tmp_path / "export")
        manifest = export_dataset_manifest(dataset)
        DatasetMaterializer(repository).export(manifest, tmp_path / "export", strategy="copy")
        member = manifest.members[0]
        exported = tmp_path / "export" / member.path
        exported.unlink()
        external = tmp_path / "external"
        external.write_bytes(b"first")
        exported.symlink_to(external)
        assert not manifest.verify(tmp_path / "export")


def test_reflink_failure_falls_back_only_in_auto_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with Repository(tmp_path / "repository") as repository:
        _record(repository)
        manifest = export_dataset_manifest(
            repository.resolve_dataset(DatasetDefinition.from_selectors(Latest("namespace:item")))
        )

        def fail_clone(*args: object) -> None:
            del args
            msg = "clone unsupported"
            raise OSError(msg)

        monkeypatch.setattr("efloud.materialization._clone", fail_clone)
        materializer = DatasetMaterializer(repository)
        materializer.export(manifest, tmp_path / "auto", strategy="auto")
        assert manifest.verify(tmp_path / "auto")
        with pytest.raises(OSError, match="clone unsupported"):
            materializer.export(manifest, tmp_path / "reflink", strategy="reflink")
        assert not (tmp_path / "reflink").exists()


def test_detached_consumer_uses_only_standard_library(tmp_path: Path) -> None:
    with Repository(tmp_path / "repository") as repository:
        _record(repository)
        dataset = repository.resolve_dataset(DatasetDefinition.from_selectors(LatestCompleteSourceSnapshot("source")))
        manifest = export_dataset_manifest(dataset, paths={"namespace:item": "catalog/item.txt"})
        DatasetMaterializer(repository).export(manifest, tmp_path / "export", strategy="copy")
    script = """
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
manifest = json.loads((root / 'dataset-manifest.json').read_bytes())
assert manifest['version'] == 1
for member in manifest['members']:
    data = (root / member['path']).read_bytes()
    assert 'sha256:' + hashlib.sha256(data).hexdigest() == member['content_id']
    assert len(data) == member['byte_size']
    assert member['observation']['source_id'] == 'source'
    assert member['source_revision']['definition']['role'] == 'reference'
assert manifest['resolution']['snapshots'][0]['complete']
print(manifest['dataset_id'])
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(tmp_path / "export")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == str(dataset.id)


def test_unknown_historical_source_revision_cannot_satisfy_metadata_filters(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        _record(repository)
    with closing(sqlite3.connect(tmp_path / "metadata.sqlite")) as connection, connection:
        connection.execute("UPDATE observations SET metadata_json = '{}'")
    with ReadOnlyRepository(tmp_path) as repository:
        assert SourceSelection(source_id="source").resolve(repository)
        with pytest.raises(ValueError, match="unknown"):
            SourceSelection(role="reference").resolve(repository)


def test_snapshot_membership_remains_bound_when_same_run_receives_backdated_observation(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        original, snapshot = _record(repository)
        repository.ingest_bytes(
            "later",
            b"later",
            run_id=original.run_id,
            operation_id=original.operation_id,
            source_id="source",
            observed_at=0.0,
            source_path="elsewhere",
        )
        assert ExactSourceSnapshot(str(snapshot.snapshot_id)).resolve(repository) == (original,)


def test_destination_created_during_export_is_never_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with Repository(tmp_path / "repository") as repository:
        _record(repository)
        manifest = export_dataset_manifest(
            repository.resolve_dataset(DatasetDefinition.from_selectors(Latest("namespace:item")))
        )
        publish = materialization_module._publish_directory
        destination = tmp_path / "export"

        def race(staging: Path, target: Path) -> None:
            target.mkdir()
            (target / "keep").write_bytes(b"other writer")
            publish(staging, target)

        monkeypatch.setattr(materialization_module, "_publish_directory", race)
        with pytest.raises(FileExistsError):
            DatasetMaterializer(repository).export(manifest, destination, strategy="copy")
        assert (destination / "keep").read_bytes() == b"other writer"
        assert not (destination / "dataset-manifest.json").exists()


def test_cleanup_rejects_unknown_schema_and_dangling_metadata(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        _record(repository)
    maintenance = RepositoryMaintenance(tmp_path)
    with closing(sqlite3.connect(tmp_path / "metadata.sqlite")) as connection, connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="schema"):
        maintenance.cleanup(now=100.0, grace_period=0.0, dry_run=False)
    with closing(sqlite3.connect(tmp_path / "metadata.sqlite")) as connection, connection:
        connection.execute("PRAGMA user_version = 3")
        connection.execute("UPDATE observations SET source_id = 'unknown'")
    with pytest.raises(ValueError, match="dangling"):
        maintenance.cleanup(now=100.0, grace_period=0.0, dry_run=False)


def test_empty_dataset_requires_explicit_complete_snapshot_evidence(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        definition = DatasetDefinition(
            (DatasetSelection(SourceSelection(source_id="source")),),
            constraints=DatasetConstraints(complete_snapshots=True),
        )
        with pytest.raises(DatasetConstraintError):
            resolve_dataset(repository, definition)
        repository.register_source("source", {})
        run = repository.start_run(started_at=1.0)
        snapshot = repository.record_tree_snapshot(
            source_id="source", run_id=run, entries=(), complete=True, observed_at=1.0
        )
        definition = replace(definition, selections=(DatasetSelection(ExactSourceSnapshot(str(snapshot.snapshot_id))),))
        assert resolve_dataset(repository, definition).members == ()


def test_cleanup_removes_unreferenced_metadata_without_blob(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        path = tmp_path / "unused"
        path.write_bytes(b"unused")
        content = repository.store_path_content(path)
    digest = str(content.content_id).removeprefix("sha256:")
    (tmp_path / "objects/sha256" / digest[:2] / digest).unlink()
    maintenance = RepositoryMaintenance(tmp_path)
    candidates = maintenance.cleanup(now=10**12, grace_period=0.0, dry_run=False)
    assert candidates[0].reason == "unreferenced-missing-content"
    assert maintenance.fsck().ok
\n\ndef test_cleanup_grace_period_boundary_is_inclusive(tmp_path: Path) -> None:\n    with Repository(tmp_path) as repository:\n        content = repository.store_bytes_content(b"unused")\n        blob = repository.blobs.path_for(content.content_id)\n    os.utime(blob, (100.0, 100.0))\n    maintenance = RepositoryMaintenance(tmp_path)\n    assert maintenance.cleanup(now=109.999, grace_period=10.0) == ()\n    candidates = maintenance.cleanup(now=110.0, grace_period=10.0)\n    assert len(candidates) == 1\n    assert candidates[0].content_id == content.content_id\n\n\ndef test_cleanup_fails_closed_on_semantic_corruption(tmp_path: Path) -> None:\n    with Repository(tmp_path) as repository:\n        _record(repository)\n        unused = repository.store_bytes_content(b"unused")\n        unused_blob = repository.blobs.path_for(unused.content_id)\n    os.utime(unused_blob, (1.0, 1.0))\n    with closing(sqlite3.connect(tmp_path / "metadata.sqlite")) as connection, connection:\n        connection.execute("UPDATE tree_entries SET relative_path = 'tampered.txt'")\n    maintenance = RepositoryMaintenance(tmp_path)\n    with pytest.raises(ValueError, match="tree-identity"):\n        maintenance.cleanup(now=100.0, grace_period=0.0, dry_run=False)\n    assert unused_blob.is_file()\n\n\ndef test_cleanup_fails_closed_on_reachable_corrupt_content(tmp_path: Path) -> None:\n    with Repository(tmp_path) as repository:\n        observation, _ = _record(repository)\n        unused = repository.store_bytes_content(b"unused")\n        unused_blob = repository.blobs.path_for(unused.content_id)\n        referenced_blob = repository.blobs.path_for(observation.content_id)\n    os.utime(unused_blob, (1.0, 1.0))\n    referenced_blob.write_bytes(b"corrupt")\n    maintenance = RepositoryMaintenance(tmp_path)\n    with pytest.raises(ValueError, match="corrupt-blob"):\n        maintenance.cleanup(now=100.0, grace_period=0.0, dry_run=False)\n    assert unused_blob.is_file()\n\n\ndef test_cleanup_preserves_provenance_history(tmp_path: Path) -> None:\n    with Repository(tmp_path) as repository:\n        source, _ = _record(repository)\n        run = repository.start_run(started_at=10.0)\n        operation = repository.start_operation(\n            run_id=run,\n            kind="derive",\n            subject="derived",\n            started_at=10.0,\n        )\n        derived = repository.record_derived_bytes(\n            "derived:item",\n            b"derived",\n            derivation_key=None,\n            run_id=run,\n            operation_id=operation,\n            inputs=(source,),\n            observed_at=10.0,\n        )\n        repository.finish_operation(operation, status="succeeded", finished_at=10.0)\n        repository.finish_run(run, status="succeeded", finished_at=10.0)\n        source_content = source.content_id\n        derived_content = derived.content_id\n    maintenance = RepositoryMaintenance(tmp_path)\n    assert maintenance.cleanup(now=10**12, grace_period=0.0, dry_run=False) == ()\n    with ReadOnlyRepository(tmp_path) as repository:\n        assert repository.verify_content(source_content)\n        assert repository.verify_content(derived_content)\n        edges = repository.provenance_inputs(derived.observation_id)\n        assert len(edges) == 1\n        assert edges[0].input_observation_id == source.observation_id\n