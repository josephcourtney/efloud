"""Canonical extensions operate without manifest projections or write handles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

import efloud.repository_compat as compatibility
from efloud import DerivedOutput, DerivedResult, Engine, EngineConfig, SourceDefinition, SourceKind, SyncRequest
from efloud.compat.extensions import LegacyEnumeratorAdapter, LegacyTaskAdapter
from efloud.derived import ExtensionContext
from efloud.fanout import FanoutEnumeration, RestBaseFanoutTask
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.medium, pytest.mark.integration, pytest.mark.timeout(30)]


@dataclass
class CopyTask:
    name: str = "copy"
    repository_version: str = "1"
    repository_input_source_ids: tuple[str, ...] = ("input",)

    @staticmethod
    def repository_parameters():
        return {"mode": "copy"}

    async def run(self, *, context: ExtensionContext) -> DerivedResult:
        del self
        assert isinstance(context.repository, ReadOnlyRepository)
        assert not hasattr(context.repository, "ingest_bytes")
        assert len(context.inputs) == 1
        with context.repository.open_content(context.inputs[0].content_id) as stream:
            data = stream.read()
        output = context.workspace / "copy.txt"
        await asyncio.to_thread(output.write_bytes, data)
        return DerivedResult(outputs=(DerivedOutput("copy", output),))


def _seed(repository: Repository) -> str:
    repository.register_source("input", {"kind": "HTTP"})
    run = repository.start_run(started_at=1.0)
    operation = repository.start_operation(run_id=run, kind="fixture", subject="input", started_at=1.0)
    observation = repository.ingest_bytes(
        "source:input", b"fixture", run_id=run, operation_id=operation, source_id="input", observed_at=1.0
    )
    repository.finish_operation(operation, status="succeeded", finished_at=2.0)
    repository.finish_run(run, status="succeeded", finished_at=2.0)
    return str(observation.observation_id)


def test_extensions_execute_without_compatibility_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args, **kwargs):
        del args, kwargs
        pytest.fail("Canonical execution requested a compatibility manifest")

    monkeypatch.setattr(compatibility, "repository_manifest", unavailable)

    async def enumerate_empty(*, context):
        assert isinstance(context.repository, ReadOnlyRepository)
        assert len(context.inputs) == 1
        await asyncio.sleep(0)
        return FanoutEnumeration((), complete=True)

    source = SourceDefinition("collection", "Collection", "https://example.test/", SourceKind.REST_BASE)
    collection = RestBaseFanoutTask(
        "collection",
        source.id,
        source.url,
        enumerate_empty,
        "collection",
        repository_input_source_ids=("input",),
    )
    with Repository(tmp_path) as repository:
        input_id = _seed(repository)
        config = EngineConfig(root=tmp_path, sources=[source], derived_tasks=(CopyTask(), collection))
        with Engine.from_config(config, repository=repository) as engine:
            result = asyncio.run(engine.sync())
        assert result.ok
        output = repository.latest_observation("derived:copy:copy")
        assert output is not None
        assert {str(edge.input_observation_id) for edge in repository.provenance_inputs(output.observation_id)} == {
            input_id
        }
        collection_result = repository.latest_observation("derived:collection:execution")
        assert collection_result is not None
        assert {
            str(edge.input_observation_id) for edge in repository.provenance_inputs(collection_result.observation_id)
        } == {input_id}
        snapshot = repository.latest_source_snapshot(source.id)
        assert snapshot is not None
        assert snapshot.complete
        assert not (tmp_path / "log" / "sync-manifest.json").exists()


class OldTask:
    name = "old"

    @staticmethod
    async def run(*, sync_root, manifest, sources):
        assert manifest["root"] == str(sync_root)
        assert sources == ()
        await asyncio.sleep(0)
        return {"ok": True, "value": 7}


def test_legacy_extensions_require_explicit_adapters(tmp_path: Path) -> None:
    async def old_enumerator(*, sync_root, manifest, sources):
        assert manifest["root"] == str(sync_root)
        assert sources == ()
        await asyncio.sleep(0)
        return FanoutEnumeration(())

    with Repository(tmp_path) as repository:
        config = EngineConfig(root=tmp_path, sources=[], derived_tasks=(LegacyTaskAdapter(OldTask()),))
        with Engine.from_config(config, repository=repository) as engine:
            assert asyncio.run(engine.sync(SyncRequest(source_ids=()))).ok
        with ReadOnlyRepository(tmp_path) as view:
            result = asyncio.run(LegacyEnumeratorAdapter(old_enumerator)(context=ExtensionContext(view, tmp_path, ())))
            assert result == FanoutEnumeration(())
