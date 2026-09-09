from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

import efloud
from efloud import DatasetManifest, DatasetSpec, Engine, HttpSource, Repository, SyncRequest
from efloud.adapters import HttpAcquisition
from efloud.errors import RepositoryOpenError
from efloud.http_adapter import HttpSourceAdapter

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def test_package_root_is_small_semantic_surface() -> None:
    assert "EngineConfig" not in efloud.__all__
    assert "SourceDefinition" not in efloud.__all__
    assert "SourceKind" not in efloud.__all__
    assert "ReadOnlyRepository" not in efloud.__all__
    assert "RepositoryView" not in efloud.__all__
    assert "DatasetMaterializer" not in efloud.__all__
    assert "Engine" in efloud.__all__
    assert "Repository" in efloud.__all__
    assert "DatasetSpec" in efloud.__all__


def test_public_source_types_are_protocol_specific() -> None:
    source = HttpSource(
        id="example",
        url="https://example.test/data.json",
        tags=("reference", "reference"),
    )
    assert source.adapter_id == "efloud:http"
    assert source.tags == ("reference",)
    assert not hasattr(source, "rsync_paths")


def test_repository_create_and_read_only_open_are_explicit(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    with Repository.create(root) as writable:
        assert writable.mode == "rw"
        assert writable.artifacts.keys() == ()

    with Repository.open(root, mode="r") as readonly:
        assert readonly.mode == "r"
        assert readonly.artifacts.keys() == ()
        with pytest.raises(RepositoryOpenError):
            Engine(readonly, [])


def test_dataset_spec_requires_aware_datetimes() -> None:
    naive = datetime(2026, 9, 9)  # ruff: ignore[call-datetime-without-tzinfo] - deliberately verify rejection of a naive datetime.
    with pytest.raises(ValueError, match="timezone-aware"):
        DatasetSpec.latest_before("source:example", naive)

    spec = DatasetSpec.latest_before("source:example", datetime(2026, 9, 9, tzinfo=UTC))
    assert spec is not None


def test_clean_api_acquire_freeze_export_and_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    materialized = tmp_path / "downloaded.txt"
    materialized.write_bytes(b"payload")

    async def fake_acquire(self, context):
        del self, context
        await asyncio.sleep(0)
        return HttpAcquisition(
            source_id="example",
            status="succeeded",
            destination=materialized,
            observed_at=123.0,
            status_code=200,
            etag='"v1"',
        )

    monkeypatch.setattr(HttpSourceAdapter, "acquire", fake_acquire)
    source = HttpSource(id="example", url="https://example.test/data.txt")

    with Repository.create(root) as repository:
        engine = Engine(repository, [source])
        plan = engine.plan(SyncRequest(dry_run=True))
        assert plan.request.dry_run

        result = asyncio.run(engine.sync())
        assert result.ok
        assert len(result.observation_ids) == 1
        assert result.failed_source_ids == ()

        dataset = repository.datasets.freeze(DatasetSpec.latest("source:example"))
        assert dataset.verify()
        assert dataset.member("source:example").content_id.startswith("sha256:")

        destination = tmp_path / "export"
        manifest = dataset.export(destination, strategy="copy")
        assert manifest.verify(destination)
        restored = DatasetManifest.from_bytes(manifest.to_bytes())
        assert restored.dataset_id == dataset.id
        assert restored.verify(destination)
        dataset_id = dataset.id

    with Repository.open(root, mode="r") as repository:
        reopened = repository.datasets.get(dataset_id)
        assert reopened.verify()
        with reopened.open("source:example") as stream:
            assert stream.read() == b"payload"
        assert repository.maintenance.audit().ok


def test_unbounded_snapshot_history_uses_none_publicly(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    with Repository.create(root) as repository:
        assert repository.sources.snapshots("missing", limit=None) == ()
        with pytest.raises(ValueError, match="nonnegative"):
            repository.sources.snapshots("missing", limit=-1)


def test_public_repository_reports_writer_contention(tmp_path: Path) -> None:
    root = tmp_path / "repository"

    with Repository.create(root):
        script = """
import sys
from efloud import Repository
from efloud.errors import RepositoryBusyError

try:
    with Repository.open(sys.argv[1], mode="rw"):
        pass
except RepositoryBusyError:
    print("busy")
else:
    print("available")
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(root)],
            capture_output=True,
            text=True,
        )

        print("stdout:", result.stdout)
        print("stderr:", result.stderr)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "busy"
