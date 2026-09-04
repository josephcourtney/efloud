from __future__ import annotations

from pathlib import Path

import pytest

from efloud.fanout import RestBaseFanoutTask
from efloud.models import EngineConfig
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_derived import import_derived_results
from efloud.repository_models import ArtifactAbsence, SourceId

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression]


async def _unused_enumerator(*, sync_root, manifest, sources):
    del sync_root, manifest, sources
    return []


def _fanout_task(source_id: str) -> RestBaseFanoutTask:
    return RestBaseFanoutTask(
        name="fanout",
        source_id=source_id,
        base_url="https://api.example.test/items",
        enumerator=_unused_enumerator,
        dest_subdir="fanout",
    )


def _collection_payload(
    root: Path,
    *,
    items: tuple[str, ...],
    missing: tuple[str, ...] = (),
) -> dict[str, object]:
    entries: dict[str, object] = {}
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
                "fanout_path": f"{item_id}.json",
            },
            "metadata": {"kind": "fixture"},
        }
    for item_id in missing:
        entries[item_id] = {
            "status": "error",
            "error": "404",
            "item_id": item_id,
            "dest": str(root / "fanout" / f"{item_id}.json"),
            "request": {
                "url": f"https://api.example.test/items/{item_id}",
                "fanout_path": f"{item_id}.json",
            },
            "metadata": {},
        }
    return {
        "source_id": "collection",
        "kind": "REST_BASE",
        "request": {
            "base_url": "https://api.example.test/items",
            "fanout_root": str(root / "fanout"),
            "response_mode": "json",
        },
        "enumeration": {"complete": True, "item_count": len(entries)},
        "entries": entries,
        "ok": len(items),
        "err": len(missing),
    }


def test_complete_collection_records_items_absence_snapshot_and_result(tmp_path: Path) -> None:
    source = SourceDefinition(
        "collection",
        "Collection",
        "https://api.example.test/items",
        SourceKind.REST_BASE,
    )
    task = _fanout_task(source.id)
    config = EngineConfig(root=tmp_path, sources=[source], derived_tasks=(task,))

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        run_id = repository.start_run(source_ids=(source.id,), started_at=10.0)
        imported = import_derived_results(
            repository,
            config=config,
            run_id=run_id,
            started_at=10.0,
            derived_results={
                "fanout": _collection_payload(tmp_path, items=("alpha",), missing=("missing",))
            },
        )

        assert imported.handled_source_ids == ("collection",)
        alpha = repository.latest_observation("source:collection:item:alpha")
        assert alpha is not None
        with repository.open_content(alpha.content_id) as stream:
            assert stream.read() == b'{"id":"alpha"}'

        missing = repository.latest_state("source:collection:item:missing")
        assert isinstance(missing, ArtifactAbsence)
        assert missing.metadata["http_status"] == 404

        snapshot = repository.latest_source_snapshot("collection")
        assert snapshot is not None
        assert snapshot.complete
        assert snapshot.evidence["enumeration_complete"] is True
        assert snapshot.evidence["content_item_count"] == 1
        assert snapshot.evidence["absent_item_count"] == 1
        assert snapshot.tree_id is not None
        entries = repository.tree_entries(snapshot.tree_id)
        assert {entry.metadata["item_id"] for entry in entries} == {"alpha", "missing"}

        result = repository.latest_observation("derived:fanout:result")
        assert result is not None
        assert result.media_type == "application/json"
        assert result.metadata["collection_snapshot_id"] == str(snapshot.snapshot_id)


def test_complete_collection_enumeration_records_removed_item_absence(tmp_path: Path) -> None:
    source = SourceDefinition(
        "collection",
        "Collection",
        "https://api.example.test/items",
        SourceKind.REST_BASE,
    )
    task = _fanout_task(source.id)
    config = EngineConfig(root=tmp_path, sources=[source], derived_tasks=(task,))

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        first_run = repository.start_run(source_ids=(source.id,), started_at=10.0)
        import_derived_results(
            repository,
            config=config,
            run_id=first_run,
            started_at=10.0,
            derived_results={"fanout": _collection_payload(tmp_path, items=("alpha", "beta"))},
        )
        assert repository.latest_observation("source:collection:item:beta") is not None

        second_run = repository.start_run(source_ids=(source.id,), started_at=20.0)
        import_derived_results(
            repository,
            config=config,
            run_id=second_run,
            started_at=20.0,
            derived_results={"fanout": _collection_payload(tmp_path, items=("alpha",))},
        )

        beta = repository.latest_state("source:collection:item:beta")
        assert isinstance(beta, ArtifactAbsence)
        assert beta.metadata["reason"] == "removed-from-complete-enumeration"
        snapshot = repository.latest_source_snapshot("collection")
        assert snapshot is not None
        assert snapshot.evidence["removed_item_count"] == 1


class DerivedFileTask:
    name = "derived-file"
    repository_version = "3"
    repository_input_source_ids: tuple[str, ...] = ()

    def repository_parameters(self) -> dict[str, object]:
        return {"mode": "fixture"}

    async def run(self, *, sync_root, manifest, sources):
        del sync_root, manifest, sources
        return {}


def test_generic_derived_task_records_output_and_result(tmp_path: Path) -> None:
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
        result = repository.latest_observation("derived:derived-file:result")
        assert result is not None
        assert result.metadata["task_version"] == "3"
        assert result.metadata["provenance_complete"] is True
