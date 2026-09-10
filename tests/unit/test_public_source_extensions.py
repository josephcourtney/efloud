from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from efloud import CollectionSource, DatasetSpec, Engine, LocalSource, Repository
from efloud.collections import CollectionContext, CollectionDefinition, CollectionInventory

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


@dataclass
class HoldingsEnumerator:
    observed: bytes | None = None

    async def __call__(self, *, context: CollectionContext) -> CollectionInventory:
        assert len(context.inputs) == 1
        with context.repository.open_content(context.inputs[0].content_id) as stream:
            self.observed = stream.read()
        await asyncio.sleep(0)
        return CollectionInventory((), complete=True, upstream_identity="fixture-holdings")


def test_public_engine_executes_advanced_collection_definition_from_repository_inputs(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    holdings_path = tmp_path / "holdings.txt"
    holdings_path.write_bytes(b"1abc\n2def\n")
    holdings = LocalSource(
        id="holdings",
        path=holdings_path,
        artifact_key="pdb:holdings",
        media_type="text/plain",
    )
    collection = CollectionSource(
        id="pdb-core-entry",
        url="https://example.invalid/core/entry",
    )
    enumerator = HoldingsEnumerator()
    definition = CollectionDefinition(
        source_id=collection.id,
        enumerator=enumerator,
        input_source_ids=(holdings.id,),
    )

    with Repository.create(repository_root) as repository:
        result = asyncio.run(
            Engine(
                repository,
                (collection, holdings),
                collections=(definition,),
            ).sync()
        )
        assert result.ok
        assert enumerator.observed == b"1abc\n2def\n"
        snapshots = repository.sources.snapshots(collection.id)
        assert len(snapshots) == 1
        assert snapshots[0].complete is True


def test_local_source_pins_bytes_independently_of_original_file(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    source_path = tmp_path / "analysis-input.json"
    source_path.write_bytes(b'{"version":1}\n')
    source = LocalSource(
        id="analysis-input",
        path=source_path,
        artifact_key="analysis:input",
        media_type="application/json",
        role="analysis-input",
    )

    with Repository.create(repository_root) as repository:
        result = asyncio.run(Engine(repository, (source,)).sync())
        assert result.ok
        assert len(result.observation_ids) == 1
        frozen = repository.datasets.freeze(DatasetSpec.latest("analysis:input"))
        dataset_id = frozen.id
        content_id = frozen.member("analysis:input").content_id

    source_path.write_bytes(b'{"version":2}\n')
    source_path.unlink()

    with Repository.open(repository_root, mode="r") as repository:
        frozen = repository.datasets.get(dataset_id)
        assert frozen.verify()
        assert frozen.member("analysis:input").content_id == content_id
        with frozen.open("analysis:input") as stream:
            assert stream.read() == b'{"version":1}\n'


def test_missing_local_source_fails_without_advancing_artifact(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    source = LocalSource(
        id="missing-input",
        path=tmp_path / "missing.dat",
        artifact_key="analysis:missing",
    )

    with Repository.create(repository_root) as repository:
        result = asyncio.run(Engine(repository, (source,)).sync())
        assert result.ok is False
        assert repository.artifacts.latest("analysis:missing") is None
        assert repository.sources.snapshots(source.id) == ()
