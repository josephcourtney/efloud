from __future__ import annotations

from pathlib import Path

import pytest

from efloud.models import EngineConfig
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_models import SourceId, TreeEntry
from efloud.repository_state import repository_mirror_state
from efloud.state import node_at_path

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression]


def _rsync_source() -> SourceDefinition:
    return SourceDefinition(
        "mirror",
        "Mirror",
        "rsync://example.test/module",
        SourceKind.RSYNC,
        local_subpath="mirror/source",
    )


def test_complete_repository_history_rebuilds_mirror_state_without_mirror_scan(tmp_path: Path) -> None:
    source = _rsync_source()
    config = EngineConfig(root=tmp_path, sources=[source])
    materialized = tmp_path / "materialized.txt"
    materialized.write_bytes(b"payload")

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        run_id = repository.start_run(source_ids=(source.id,), started_at=10.0)
        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source.id,
            kind="rsync",
            subject=source.id,
            started_at=10.0,
        )
        observation = repository.ingest_path(
            "source:mirror:path:aa/file.dat",
            materialized,
            run_id=run_id,
            operation_id=operation_id,
            source_id=source.id,
            observed_at=11.0,
            source_path="aa/file.dat",
        )
        repository.record_tree_snapshot(
            source_id=source.id,
            run_id=run_id,
            entries=(
                TreeEntry(
                    relative_path="aa/file.dat",
                    kind="file",
                    content_id=observation.content_id,
                    byte_size=7,
                ),
            ),
            complete=True,
            observed_at=11.0,
            evidence={"reconciliation_complete": True},
        )
        repository.finish_operation(operation_id, status="success", finished_at=12.0)
        repository.finish_run(run_id, status="success", finished_at=12.0)

        materialized.unlink()
        state = repository_mirror_state(repository, cfg=config, generated_at=12.0)
        assert state is not None
        assert state.generated_at_unix == 12.0
        source_node = node_at_path(state.tree, "mirror/source")
        assert source_node is not None
        assert source_node.file_count == 1
        assert source_node.children is not None
        assert state.sources[0].hash == source_node.hash
        assert source_node.children["aa"].children is not None
        file_node = source_node.children["aa"].children["file.dat"]
        assert file_node.hash == str(observation.content_id).removeprefix("sha256:")


def test_partial_only_repository_history_does_not_claim_full_mirror_state(tmp_path: Path) -> None:
    source = _rsync_source()
    config = EngineConfig(root=tmp_path, sources=[source])

    with Repository(tmp_path) as repository:
        repository.register_source(SourceId(source.id), {"kind": source.kind.value})
        run_id = repository.start_run(source_ids=(source.id,), started_at=10.0)
        repository.record_tree_snapshot(
            source_id=source.id,
            run_id=run_id,
            entries=(),
            complete=False,
            scope=("aa/",),
            observed_at=11.0,
            evidence={"reconciliation_complete": True},
        )
        repository.finish_run(run_id, status="success", finished_at=12.0)

        assert repository_mirror_state(repository, cfg=config) is None
