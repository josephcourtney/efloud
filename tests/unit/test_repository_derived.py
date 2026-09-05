from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from efloud.fanout import RestBaseFanoutTask
from efloud.json_types import json_mapping_or_none
from efloud.models import EngineConfig
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_derived import import_derived_results
from efloud.repository_models import ArtifactAbsence, ArtifactObservation, SourceId

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]
if TYPE_CHECKING:
    from pathlib import Path

    from efloud.json_types import JsonArray, JsonObject


async def _unused_enumerator(*, sync_root, manifest, sources):
    del sync_root, manifest, sources
    await asyncio.gather()
    return []


def _fanout_task(source_id: str) -> RestBaseFanoutTask:
    return RestBaseFanoutTask(
        name="fanout",
        source_id=source_id,
        base_url="https://api.example.test/items",
        enumerator=_unused_enumerator,
        dest_subdir="fanout",
    )


def _inventory_item(item_id: str, *, with_change_token: bool) -> JsonObject:
    item: JsonObject = {
        "item_id": item_id,
        "artifact_key": f"source:collection:item:{item_id}",
        "locator": f"https://api.example.test/items/{item_id}",
        "expected_integrity": [],
        "metadata": {},
    }
    if with_change_token:
        item["change_token"] = {
            "kind": "fixture-version",
            "value": f"v-{item_id}",
            "reliability": "strong",
        }
    return item


def _collection_payload(
    root: Path,
    *,
    items: tuple[str, ...],
    missing: tuple[str, ...] = (),
    complete: bool = True,
    upstream_identity: str | None = None,
    observed_at: float = 9.0,
) -> JsonObject:
    entries: JsonObject = {}
    inventory_items: JsonArray = []
    for item_id in items:
        dest = root / "fanout" / f"{item_id}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f'{{"id":"{item_id}"}}', encoding="utf-8")
        entries[item_id] = {
            "status": "ok",
            "item_id": item_id,
            "dest": str(dest),
            "request": {
                "url": f"https://api.example.test/items/{item_id}",
                "request_path": item_id,
                "fanout_path": f"{item_id}.json",
            },
            "metadata": {"kind": "fixture"},
            "inventory": {
                "change_token": {
                    "kind": "fixture-version",
                    "value": f"v-{item_id}",
                    "reliability": "strong",
                },
                "expected_integrity": [],
            },
        }
        inventory_items.append(_inventory_item(item_id, with_change_token=True))
    for item_id in missing:
        entries[item_id] = {
            "status": "error",
            "error": "404",
            "item_id": item_id,
            "dest": str(root / "fanout" / f"{item_id}.json"),
            "request": {
                "url": f"https://api.example.test/items/{item_id}",
                "request_path": item_id,
                "fanout_path": f"{item_id}.json",
            },
            "metadata": {},
            "inventory": {"expected_integrity": []},
        }
        inventory_items.append(_inventory_item(item_id, with_change_token=False))

    enumeration: JsonObject = {
        "complete": complete,
        "item_count": len(inventory_items),
        "model": "source-inventory-v1",
    }
    inventory: JsonObject = {
        "source_id": "collection",
        "observed_at": observed_at,
        "coverage": {"scope": [], "complete": complete},
        "items": inventory_items,
        "metadata": {"transport": "REST_BASE", "collection": True},
    }
    if upstream_identity is not None:
        enumeration["upstream_identity"] = upstream_identity
        inventory["upstream_identity"] = upstream_identity
    return {
        "source_id": "collection",
        "kind": "REST_BASE",
        "request": {
            "base_url": "https://api.example.test/items",
            "fanout_root": str(root / "fanout"),
            "response_mode": "json",
        },
        "inventory": inventory,
        "enumeration": enumeration,
        "entries": entries,
        "ok": len(items),
        "err": len(missing),
    }


def _collection_config(root: Path) -> tuple[SourceDefinition, EngineConfig]:
    source = SourceDefinition(
        "collection",
        "Collection",
        "https://api.example.test/items",
        SourceKind.REST_BASE,
    )
    task = _fanout_task(source.id)
    return source, EngineConfig(root=root, sources=[source], derived_tasks=(task,))


def test_complete_collection_records_items_absence_snapshot_and_execution(tmp_path: Path) -> None:
    source, config = _collection_config(tmp_path)

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        run_id = repository.start_run(source_ids=(source.id,), started_at=10.0)
        imported = import_derived_results(
            repository,
            config=config,
            run_id=run_id,
            started_at=10.0,
            derived_results={
                "fanout": _collection_payload(
                    tmp_path,
                    items=("alpha",),
                    missing=("missing",),
                    upstream_identity="catalog-v1",
                )
            },
        )

        assert imported.handled_source_ids == ("collection",)
        alpha = repository.latest_observation("source:collection:item:alpha")
        assert alpha is not None
        assert alpha.metadata["reconciliation_state"] == "new"
        with repository.open_content(alpha.content_id) as stream:
            assert stream.read() == b'{"id":"alpha"}'

        missing = repository.latest_state("source:collection:item:missing")
        assert isinstance(missing, ArtifactAbsence)
        assert missing.metadata["http_status"] == 404
        assert missing.metadata["reconciliation_state"] == "new"

        snapshot = repository.latest_source_snapshot("collection")
        assert snapshot is not None
        assert snapshot.complete
        assert snapshot.observed_at == pytest.approx(9.0)
        assert snapshot.evidence["inventory_model"] == "source-inventory-v1"
        assert snapshot.evidence["enumeration_complete"] is True
        assert snapshot.evidence["upstream_identity"] == "catalog-v1"
        assert snapshot.evidence["content_item_count"] == 1
        assert snapshot.evidence["absent_item_count"] == 1
        assert snapshot.evidence["classification_counts"] == {
            "new": 2,
            "changed": 0,
            "unchanged": 0,
            "absent": 0,
        }
        assert snapshot.tree_id is not None
        tree_entries = repository.tree_entries(snapshot.tree_id)
        assert {entry.metadata["item_id"] for entry in tree_entries} == {"alpha", "missing"}

        execution = repository.latest_observation("derived:fanout:execution")
        assert execution is not None
        assert execution.media_type == "application/json"
        assert execution.metadata["collection_snapshot_id"] == str(snapshot.snapshot_id)
        assert execution.metadata["compatibility_execution_record"] is True


def test_complete_collection_enumeration_records_removed_item_absence(tmp_path: Path) -> None:
    source, config = _collection_config(tmp_path)

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        first_run = repository.start_run(source_ids=(source.id,), started_at=10.0)
        import_derived_results(
            repository,
            config=config,
            run_id=first_run,
            started_at=10.0,
            derived_results={
                "fanout": _collection_payload(
                    tmp_path,
                    items=("alpha", "beta"),
                    observed_at=9.0,
                )
            },
        )
        assert repository.latest_observation("source:collection:item:beta") is not None

        second_run = repository.start_run(source_ids=(source.id,), started_at=20.0)
        import_derived_results(
            repository,
            config=config,
            run_id=second_run,
            started_at=20.0,
            derived_results={
                "fanout": _collection_payload(
                    tmp_path,
                    items=("alpha",),
                    observed_at=19.0,
                )
            },
        )

        beta = repository.latest_state("source:collection:item:beta")
        assert isinstance(beta, ArtifactAbsence)
        assert beta.metadata["reason"] == "removed-from-complete-enumeration"
        assert beta.metadata["reconciliation_state"] == "absent"
        snapshot = repository.latest_source_snapshot("collection")
        assert snapshot is not None
        assert snapshot.evidence["removed_item_count"] == 1
        assert snapshot.evidence["classification_counts"] == {
            "new": 0,
            "changed": 0,
            "unchanged": 1,
            "absent": 1,
        }


def test_partial_collection_enumeration_never_proves_removed_items_absent(tmp_path: Path) -> None:
    source, config = _collection_config(tmp_path)

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        first_run = repository.start_run(source_ids=(source.id,), started_at=10.0)
        import_derived_results(
            repository,
            config=config,
            run_id=first_run,
            started_at=10.0,
            derived_results={
                "fanout": _collection_payload(
                    tmp_path,
                    items=("alpha", "beta"),
                    observed_at=9.0,
                )
            },
        )
        beta_before = repository.latest_state("source:collection:item:beta")
        assert isinstance(beta_before, ArtifactObservation)

        partial_run = repository.start_run(source_ids=(source.id,), started_at=20.0)
        import_derived_results(
            repository,
            config=config,
            run_id=partial_run,
            started_at=20.0,
            derived_results={
                "fanout": _collection_payload(
                    tmp_path,
                    items=("alpha",),
                    complete=False,
                    observed_at=19.0,
                )
            },
        )

        assert repository.latest_state("source:collection:item:beta") == beta_before
        partial_snapshot = repository.latest_source_snapshot("collection")
        assert partial_snapshot is not None
        assert partial_snapshot.complete is False
        assert partial_snapshot.evidence["removed_item_count"] == 0
        assert partial_snapshot.evidence["classification_counts"] == {
            "new": 0,
            "changed": 0,
            "unchanged": 1,
            "absent": 0,
        }

        final_run = repository.start_run(source_ids=(source.id,), started_at=30.0)
        import_derived_results(
            repository,
            config=config,
            run_id=final_run,
            started_at=30.0,
            derived_results={
                "fanout": _collection_payload(
                    tmp_path,
                    items=("alpha",),
                    observed_at=29.0,
                )
            },
        )
        beta_after = repository.latest_state("source:collection:item:beta")
        assert isinstance(beta_after, ArtifactAbsence)
        assert beta_after.metadata["reason"] == "removed-from-complete-enumeration"


def test_enumerated_item_without_retrieval_result_is_unresolved_not_absent(tmp_path: Path) -> None:
    source, config = _collection_config(tmp_path)
    payload = _collection_payload(tmp_path, items=("alpha", "beta"))
    entries = json_mapping_or_none(payload.get("entries"))
    assert entries is not None
    payload["entries"] = {key: value for key, value in entries.items() if key != "beta"}
    payload["ok"] = 1

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

        assert repository.latest_state("source:collection:item:beta") is None
        snapshot = repository.latest_source_snapshot("collection")
        assert snapshot is not None
        assert snapshot.complete is True
        assert snapshot.evidence["enumerated_item_count"] == 2
        assert snapshot.evidence["unresolved_item_count"] == 1
        assert snapshot.evidence["removed_item_count"] == 0
        assert snapshot.evidence["acquisition_complete"] is False
        assert snapshot.tree_id is not None
        tree_entries = repository.tree_entries(snapshot.tree_id)
        beta = next(entry for entry in tree_entries if entry.metadata.get("item_id") == "beta")
        assert beta.kind == "unresolved"


def test_declared_inventory_count_mismatch_downgrades_complete_coverage(tmp_path: Path) -> None:
    source, config = _collection_config(tmp_path)
    payload = _collection_payload(tmp_path, items=("alpha",))
    enumeration = json_mapping_or_none(payload.get("enumeration"))
    assert enumeration is not None
    payload["enumeration"] = {**enumeration, "item_count": 2}

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
        snapshot = repository.latest_source_snapshot("collection")
        assert snapshot is not None
        assert snapshot.complete is False
        assert snapshot.evidence["enumeration_complete"] is False


class DerivedFileTask:
    name = "derived-file"
    repository_version = "3"
    repository_input_source_ids: tuple[str, ...] = ()

    @staticmethod
    def repository_parameters() -> JsonObject:
        return {"mode": "fixture"}

    @staticmethod
    async def run(*, sync_root, manifest, sources):
        del sync_root, manifest, sources
        await asyncio.gather()
        return {}


def test_generic_derived_task_records_output_and_execution(tmp_path: Path) -> None:
    output = tmp_path / "derived.txt"
    output.write_text("derived bytes", encoding="utf-8")
    task = DerivedFileTask()
    config = EngineConfig(root=tmp_path, sources=[], derived_tasks=(task,))

    with Repository(tmp_path) as repository:
        run_id = repository.start_run(started_at=30.0)
        imported = import_derived_results(
            repository,
            config=config,
            run_id=run_id,
            started_at=30.0,
            derived_results={"derived-file": {"ok": True, "dest": str(output), "count": 1}},
        )

        assert len(imported.observations) == 2
        artifact = repository.latest_observation("derived:derived-file:output")
        assert artifact is not None
        with repository.open_content(artifact.content_id) as stream:
            assert stream.read() == b"derived bytes"
        execution = repository.latest_observation("derived:derived-file:execution")
        assert execution is not None
        assert execution.metadata["task_version"] == "3"
        assert execution.metadata["provenance_complete"] is True
        assert execution.metadata["input_observation_ids"] == []
