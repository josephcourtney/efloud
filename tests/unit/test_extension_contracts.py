"""Canonical extensions operate on exact inputs and narrow repository reads."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from efloud.collections import CollectionContext, CollectionDefinition, CollectionInventory
from efloud.derivation import DerivedContext, DerivedOutput, DerivedResult, DerivedTaskSpec
from efloud.engine import Engine
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository import Repository
from efloud.sources import CollectionSource

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.medium, pytest.mark.integration, pytest.mark.timeout(30)]


@dataclass
class CopyTask:
    name: str = "copy"
    input_source_ids: tuple[str, ...] = ("input",)
    output_names: tuple[str, ...] = ("copy",)

    @property
    def spec(self) -> DerivedTaskSpec:
        return DerivedTaskSpec(
            task_id="efloud:derived:copy",
            task_version="1",
            deterministic=True,
            dependency_semantics="content",
            parameters={"mode": "copy"},
        )

    async def run(self, *, context: DerivedContext) -> DerivedResult:
        assert isinstance(context.repository, ReadOnlyRepository)
        assert not hasattr(context.repository, "ingest_bytes")
        assert len(context.inputs) == 1
        with context.repository.open_content(context.inputs[0].content_id) as stream:
            data = stream.read()
        output = context.workspace / "copy.txt"
        await asyncio.to_thread(output.write_bytes, data)
        return DerivedResult(outputs=(DerivedOutput("copy", output),))


def _seed(repository: Repository) -> str:
    repository.register_source("input", {"adapter_id": "fixture:input"})
    run = repository.start_run(started_at=1.0)
    operation = repository.start_operation(run_id=run, kind="fixture", subject="input", started_at=1.0)
    observation = repository.ingest_bytes(
        "source:input",
        b"fixture",
        run_id=run,
        operation_id=operation,
        source_id="input",
        observed_at=1.0,
    )
    repository.finish_operation(operation, status="succeeded", finished_at=2.0)
    repository.finish_run(run, status="succeeded", finished_at=2.0)
    return str(observation.observation_id)


def test_extensions_receive_narrow_repository_contexts(tmp_path: Path) -> None:
    async def enumerate_empty(*, context: CollectionContext) -> CollectionInventory:
        assert isinstance(context.repository, ReadOnlyRepository)
        assert not hasattr(context.repository, "ingest_bytes")
        assert len(context.inputs) == 1
        await asyncio.sleep(0)
        return CollectionInventory((), complete=True)

    source = CollectionSource("collection", "https://example.test/", description="Collection")
    collection = CollectionDefinition(
        source_id=source.id,
        enumerator=enumerate_empty,
        dest_subdir="collection",
        input_source_ids=("input",),
    )
    with Repository(tmp_path) as repository:
        input_id = _seed(repository)
        engine = Engine(
            repository,
            (source,),
            derived_tasks=(CopyTask(),),
            collections=(collection,),
        )
        result = asyncio.run(engine.sync())
        assert result.ok, result.execution
        output = repository.latest_observation("derived:copy:copy")
        assert output is not None
        assert {str(edge.input_observation_id) for edge in repository.provenance_inputs(output.observation_id)} == {
            input_id
        }
        collection_result = repository.latest_observation("source:collection:collection-execution")
        assert collection_result is not None
        assert {
            str(edge.input_observation_id) for edge in repository.provenance_inputs(collection_result.observation_id)
        } == {input_id}
        snapshot = repository.latest_source_snapshot(source.id)
        assert snapshot is not None
        assert snapshot.complete


@pytest.mark.parametrize("mode", ["failed", "duplicate", "empty-name", "invalid-result", "raised"])
def test_derived_failures_never_publish_outputs(tmp_path: Path, mode: str) -> None:
    class Task:
        name = "failed"
        input_source_ids: tuple[str, ...] = ()
        output_names: tuple[str, ...] = ("output",)
        spec = DerivedTaskSpec(
            task_id="efloud:derived:failed",
            task_version="1",
            deterministic=False,
            dependency_semantics="observation",
        )

        @staticmethod
        async def run(*, context: DerivedContext):
            await asyncio.sleep(0)
            if mode == "raised":
                msg = "extension failure"
                raise ValueError(msg)
            if mode == "invalid-result":
                return {"ok": True}
            name = "" if mode == "empty-name" else "output"
            output = DerivedOutput(name, context.workspace / "missing")
            return DerivedResult(ok=mode != "failed", outputs=(output, output) if mode == "duplicate" else (output,))

    with Repository(tmp_path) as repository:
        result = asyncio.run(Engine(repository, (), derived_tasks=(Task(),)).sync())
        assert not result.ok
        assert repository.latest_observation("derived:failed:output") is None
        assert result.repository_run_id is not None
        run = repository.run(result.repository_run_id)
        assert run is not None
        assert run.status == "failed"
