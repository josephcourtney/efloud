import asyncio
from pathlib import Path

import pytest

from efloud.adapters import AdapterRegistry, HttpAcquisition, RsyncAcquisition
from efloud.engine import Engine
from efloud.http_adapter import HttpSourceAdapter
from efloud.repository import Repository
from efloud.rsync_adapter import RsyncSourceAdapter
from efloud.sources import HttpSource, RsyncSource
from efloud.transport.rsync_inventory import RsyncInventory, RsyncInventoryEntry

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def test_engine_records_http_adapter_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    materialized = tmp_path / "http" / "data.txt"
    materialized.parent.mkdir(parents=True)
    materialized.write_bytes(b"payload")
    source = HttpSource(
        id="example",
        description="Example",
        url="https://example.test/data.txt",
    )

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
    with Repository(tmp_path) as repository:
        engine = Engine(repository, (source,))
        result = asyncio.run(engine.sync())
        assert result.ok
        assert len(result.observations) == 1
        observation = repository.latest_observation("source:example")
        assert observation is not None
        assert observation.observed_at == pytest.approx(123.0)
        assert observation.upstream_version == '"v1"'
        with repository.open_content(observation.content_id) as stream:
            assert stream.read() == b"payload"
        snapshot = repository.latest_source_snapshot("example")
        assert snapshot is not None
        assert snapshot.complete
        assert snapshot.evidence["status_code"] == 200
        assert result.repository_run_id is not None
        operation = repository.metadata.operations_for_run(result.repository_run_id)[0]
        assert operation.producer.producer_id == "efloud:http"
        assert operation.producer.version == "1"


def test_engine_leaves_source_without_adapter_unrecorded(tmp_path: Path) -> None:
    source = RsyncSource(
        id="mirror",
        description="Mirror",
        url="rsync://example.test/module",
        local_subpath="mirror",
    )

    with Repository(tmp_path) as repository:
        engine = Engine(repository, (source,), adapters=AdapterRegistry())
        result = asyncio.run(engine.sync())
        assert result.skipped_source_ids == ("mirror",)
        assert repository.artifact_keys() == ()
        assert result.plan.decisions[0].reason == "no adapter registered for efloud:rsync"


def test_engine_falls_back_to_rsync_delta_when_inventory_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror_root = tmp_path / "mirrors" / "mirror"
    changed = mirror_root / "aa" / "entry.txt"
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"version one")
    source = RsyncSource(
        id="mirror",
        description="Mirror",
        url="rsync://example.test/module",
        local_subpath="mirror",
    )

    async def fake_acquire(self, context):
        del self, context
        await asyncio.sleep(0)
        return RsyncAcquisition(
            source_id="mirror",
            status="succeeded",
            local_root=mirror_root,
            scope=("aa/",),
            observed_at=123.0,
            inventory=RsyncInventory(entries=(), scope=("aa/",), complete=False, error="offline"),
            updated_paths=("aa/entry.txt",),
        )

    monkeypatch.setattr(RsyncSourceAdapter, "acquire", fake_acquire)
    with Repository(tmp_path) as repository:
        engine = Engine(repository, (source,))
        result = asyncio.run(engine.sync())
        assert result.skipped_source_ids == ()
        observation = repository.latest_observation("source:mirror:path:aa/entry.txt")
        assert observation is not None
        assert observation.source_path == "aa/entry.txt"
        with repository.open_content(observation.content_id) as stream:
            assert stream.read() == b"version one"
        snapshot = repository.latest_source_snapshot("mirror")
        assert snapshot is not None
        assert snapshot.complete is False
        assert snapshot.scope == ("aa/",)
        assert snapshot.evidence["reconciliation_complete"] is False
        assert snapshot.evidence["inventory_error"] == "offline"
        assert snapshot.tree_id is not None
        assert repository.tree_entries(snapshot.tree_id)[0].relative_path == "aa/entry.txt"


def test_engine_authoritatively_records_rsync_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror_root = tmp_path / "mirrors" / "mirror"
    materialized = mirror_root / "aa" / "entry.txt"
    materialized.parent.mkdir(parents=True)
    materialized.write_bytes(b"version one")
    source = RsyncSource(
        id="mirror",
        description="Mirror",
        url="rsync://example.test/module",
        local_subpath="mirror",
    )

    async def fake_acquire(self, context):
        del self, context
        await asyncio.sleep(0)
        return RsyncAcquisition(
            source_id="mirror",
            status="succeeded",
            local_root=mirror_root,
            scope=(),
            observed_at=123.0,
            inventory=RsyncInventory(
                entries=(
                    RsyncInventoryEntry(
                        "aa/entry.txt",
                        "file",
                        len(b"version one"),
                        "2026/09/04 10:00:00",
                    ),
                ),
                scope=(),
                complete=True,
            ),
            updated_paths=("aa/entry.txt",),
        )

    monkeypatch.setattr(RsyncSourceAdapter, "acquire", fake_acquire)
    with Repository(tmp_path) as repository:
        engine = Engine(repository, (source,))
        result = asyncio.run(engine.sync())
        assert len(result.observations) == 1
        observation = repository.latest_observation("source:mirror:path:aa/entry.txt")
        assert observation is not None
        snapshot = repository.latest_source_snapshot("mirror")
        assert snapshot is not None
        assert snapshot.complete is True
        assert snapshot.evidence["reconciliation_complete"] is True
        assert snapshot.evidence["inventory_entry_count"] == 1


def test_engine_does_not_infer_rsync_deletion_when_inventory_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror_root = tmp_path / "mirrors" / "mirror"
    mirror_root.mkdir(parents=True)
    source = RsyncSource(
        id="mirror",
        description="Mirror",
        url="rsync://example.test/module",
        local_subpath="mirror",
    )

    async def fake_acquire(self, context):
        del self, context
        await asyncio.sleep(0)
        return RsyncAcquisition(
            source_id="mirror",
            status="succeeded",
            local_root=mirror_root,
            scope=(),
            observed_at=123.0,
            inventory=RsyncInventory(entries=(), scope=(), complete=False, error="offline"),
            updated_paths=(),
        )

    monkeypatch.setattr(RsyncSourceAdapter, "acquire", fake_acquire)
    with Repository(tmp_path) as repository:
        engine = Engine(repository, (source,))
        asyncio.run(engine.sync())
        assert repository.latest_state("source:mirror:path:stale.txt") is None
        snapshot = repository.latest_source_snapshot("mirror")
        assert snapshot is not None
        assert snapshot.complete is False
