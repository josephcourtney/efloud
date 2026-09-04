from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from efloud.json_types import json_mapping_or_none
from efloud.models import EngineConfig
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_compat import repository_manifest
from efloud.repository_derived import import_derived_results
from efloud.repository_models import SourceId

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.small]


class DerivedTask:
    name = "summary"
    repository_version = "1"
    repository_input_source_ids = ("http",)

    @staticmethod
    def repository_parameters():
        return {"kind": "fixture"}

    @staticmethod
    async def run(*, sync_root, manifest, sources):
        del sync_root, manifest, sources
        await asyncio.sleep(0)
        return {}


def test_manifest_is_reconstructed_from_repository_state(tmp_path: Path) -> None:
    source = SourceDefinition(
        "http",
        "HTTP",
        "https://example.test/data.json",
        SourceKind.HTTP,
    )
    task = DerivedTask()
    config = EngineConfig(root=tmp_path, sources=[source], derived_tasks=(task,))
    source_file = tmp_path / "http" / "data.json"
    source_file.parent.mkdir(parents=True)
    source_file.write_text('{"value":1}', encoding="utf-8")

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        run_id = repository.start_run(source_ids=(source.id,), started_at=100.0)
        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source.id,
            kind="http",
            subject=source.id,
            started_at=100.0,
            parameters={"url": source.url},
        )
        observation = repository.ingest_path(
            "source:http",
            source_file,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source.id,
            observed_at=101.0,
            upstream_locator=source.url,
            upstream_version='"v1"',
            media_type="application/json",
            materialization_kind="compatibility-http",
        )
        repository.record_source_snapshot(
            source_id=source.id,
            run_id=run_id,
            complete=True,
            observed_at=101.0,
            evidence={"status_code": 200, "etag": '"v1"'},
        )
        repository.finish_operation(operation_id, status="success", finished_at=102.0)

        import_derived_results(
            repository,
            config=config,
            run_id=run_id,
            started_at=103.0,
            derived_results={"summary": {"ok": True, "count": 1}},
        )
        repository.finish_run(run_id, status="success", finished_at=104.0)

        manifest = repository_manifest(repository, cfg=config, run_id=run_id)
        http = manifest["results"]["http"]["http"]
        freshness = json_mapping_or_none(http.get("freshness"))
        assert freshness is not None
        assert http["content_id"] == str(observation.content_id)
        assert freshness["etag"] == '"v1"'
        assert manifest["results"]["derived"]["summary"] == {"ok": True, "count": 1}
        assert manifest["started_at_unix"] == 100
        assert manifest["finished_at_unix"] == 104
        assert manifest["errors"] == []
