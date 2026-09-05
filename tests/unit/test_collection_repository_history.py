from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from efloud.fanout import RestBaseFanoutTask
from efloud.models import EngineConfig
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_derived import import_derived_results
from efloud.repository_models import SourceId

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.json_types import JsonObject

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


async def _unused_enumerator(*, sync_root, manifest, sources):
    del sync_root, manifest, sources
    await asyncio.sleep(0)
    return []


def test_collection_history_survives_deleted_materialization_and_reopen(tmp_path: Path) -> None:
    source = SourceDefinition(
        "collection",
        "Collection",
        "https://api.example.test/items",
        SourceKind.REST_BASE,
    )
    task = RestBaseFanoutTask(
        name="fanout",
        source_id=source.id,
        base_url=source.url,
        enumerator=_unused_enumerator,
        dest_subdir="fanout",
    )
    config = EngineConfig(root=tmp_path, sources=[source], derived_tasks=(task,))
    materialized = tmp_path / "fanout" / "alpha.json"
    materialized.parent.mkdir(parents=True)
    materialized.write_text('{"id":"alpha"}', encoding="utf-8")
    payload: JsonObject = {
        "source_id": source.id,
        "kind": source.kind.value,
        "request": {
            "base_url": source.url,
            "fanout_root": str(materialized.parent),
            "response_mode": "json",
        },
        "inventory": {
            "source_id": source.id,
            "observed_at": 10.0,
            "coverage": {"scope": [], "complete": True},
            "items": [
                {
                    "item_id": "alpha",
                    "artifact_key": "source:collection:item:alpha",
                    "locator": f"{source.url}/alpha",
                    "expected_integrity": [],
                    "metadata": {},
                }
            ],
            "metadata": {"transport": "REST_BASE", "collection": True},
        },
        "enumeration": {
            "complete": True,
            "item_count": 1,
            "model": "source-inventory-v1",
        },
        "entries": {
            "alpha": {
                "status": "ok",
                "item_id": "alpha",
                "dest": str(materialized),
                "request": {
                    "url": f"{source.url}/alpha",
                    "request_path": "alpha",
                    "fanout_path": "alpha.json",
                },
                "metadata": {},
            }
        },
        "ok": 1,
        "err": 0,
    }

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        run_id = repository.start_run(source_ids=(source.id,), started_at=10.0)
        import_derived_results(
            repository,
            config=config,
            run_id=run_id,
            started_at=10.0,
            derived_results={"fanout": payload},
        )
        observation = repository.latest_observation("source:collection:item:alpha")
        snapshot = repository.latest_source_snapshot(source.id)
        assert observation is not None
        assert snapshot is not None
        content_id = observation.content_id
        snapshot_id = snapshot.snapshot_id

    materialized.unlink()

    with Repository(tmp_path) as reopened:
        observation = reopened.latest_observation("source:collection:item:alpha")
        snapshot = reopened.latest_source_snapshot(source.id)
        assert observation is not None
        assert observation.content_id == content_id
        assert snapshot is not None
        assert snapshot.snapshot_id == snapshot_id
        with reopened.open_content(content_id) as stream:
            assert stream.read() == b'{"id":"alpha"}'
