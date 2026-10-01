from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from efloud.catalog import Catalog, MemoryCatalog
from efloud.metadata_store import DatasetMemberRecord, DatasetRecord
from efloud.repository_models import (
    ArtifactAbsence,
    ArtifactKey,
    ArtifactObservation,
    ContentId,
    ContentRef,
    DatasetId,
    ObservationId,
    OperationId,
    ProvenanceEdge,
    RunId,
    SnapshotId,
    SourceId,
    SourceSnapshot,
    ValidationResult,
)

if TYPE_CHECKING:
    from efloud.json_types import JsonObject

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.small]


def _catalog() -> Catalog:
    return MemoryCatalog()


def _producer_parameters() -> JsonObject:
    return {"producer": {"producer_id": "test:fixture", "version": "1"}}


def test_memory_catalog_tracks_observation_absence_provenance_and_validation() -> None:
    catalog = _catalog()
    source_id = SourceId("source")
    run_id = RunId("run:1")
    operation_id = OperationId("op:1")
    artifact_key = ArtifactKey("artifact:item")

    catalog.register_source(source_id, {"role": "fixture"})
    catalog.start_run(run_id, started_at=1.0, metadata={})
    catalog.start_operation(
        operation_id,
        run_id=run_id,
        source_id=source_id,
        kind="fetch",
        subject="fixture",
        started_at=1.0,
        parameters=_producer_parameters(),
    )

    first_content = ContentRef(ContentId(f"sha256:{'a' * 64}"), 1, "test:a")
    first = ArtifactObservation(
        ObservationId("obs:1"),
        artifact_key,
        first_content.content_id,
        source_id,
        run_id,
        operation_id,
        2.0,
    )
    catalog.record_observation_bundle(content=first_content, observation=first)

    second_content = ContentRef(ContentId(f"sha256:{'b' * 64}"), 1, "test:b")
    second = ArtifactObservation(
        ObservationId("obs:2"),
        artifact_key,
        second_content.content_id,
        source_id,
        run_id,
        operation_id,
        3.0,
    )
    edge = ProvenanceEdge(second.observation_id, first.observation_id)
    catalog.record_observation_bundle(
        content=second_content,
        observation=second,
        provenance_edges=(edge,),
    )
    absence = ArtifactAbsence(
        ObservationId("obs:absence"),
        artifact_key,
        source_id,
        run_id,
        operation_id,
        4.0,
    )
    catalog.record_absence(absence)

    assert catalog.observations_for(artifact_key) == (first, second)
    assert catalog.latest_observation(artifact_key) == second
    assert catalog.latest_state(artifact_key) == absence
    assert catalog.latest_state(artifact_key, before=3.0) == second
    assert catalog.provenance_inputs(second.observation_id) == (edge,)
    assert catalog.artifact_keys() == (artifact_key,)

    old_validation = ValidationResult(second.content_id, "test:validator", "1", 5.0, "passed")
    new_validation = ValidationResult(second.content_id, "test:validator", "1", 6.0, "failed")
    catalog.record_validation(old_validation)
    catalog.record_validation(new_validation)
    assert catalog.validation(second.content_id, "test:validator", "1") == new_validation
    assert catalog.validations_for(second.content_id) == (new_validation,)

    catalog.finish_operation(operation_id, finished_at=7.0, status="succeeded", details={})
    catalog.finish_run(run_id, finished_at=8.0, status="succeeded")
    finished = catalog.run(run_id)
    assert finished is not None
    assert finished.status == "succeeded"


def test_memory_catalog_keeps_snapshot_history_and_merges_dataset_specifications() -> None:
    catalog = _catalog()
    source_id = SourceId("source")
    run_id = RunId("run:1")
    first_snapshot = SourceSnapshot(SnapshotId("snapshot:1"), source_id, run_id, 1.0, True)
    second_snapshot = SourceSnapshot(SnapshotId("snapshot:2"), source_id, run_id, 2.0, False)
    catalog.record_source_snapshot(first_snapshot)
    catalog.record_source_snapshot(second_snapshot)

    assert catalog.latest_source_snapshot(source_id) == second_snapshot
    assert catalog.source_snapshots_for(source_id, limit=None) == (second_snapshot, first_snapshot)
    with pytest.raises(ValueError, match="nonnegative"):
        catalog.source_snapshots_for(source_id, limit=-1)

    member = DatasetMemberRecord(
        artifact_key=ArtifactKey("artifact:item"),
        observation_id=ObservationId("obs:1"),
        content_id=ContentId(f"sha256:{'a' * 64}"),
    )
    first = DatasetRecord(
        dataset_id=DatasetId("dataset:1"),
        content_identity="dataset-content:1",
        created_at=10.0,
        definition={"selections": [{"kind": "latest", "artifact_key": "artifact:item"}]},
        metadata={},
        members=(member,),
    )
    second = DatasetRecord(
        dataset_id=first.dataset_id,
        content_identity=first.content_identity,
        created_at=20.0,
        definition={"selections": [{"kind": "exact", "observation_id": "obs:1"}]},
        metadata={},
        members=(member,),
    )
    catalog.record_dataset(first)
    catalog.record_dataset(second)

    stored = catalog.dataset(first.dataset_id)
    assert stored is not None
    assert stored.created_at == pytest.approx(10.0)
    assert len(stored.specifications) == 2
    definitions = [specification.definition for specification in stored.specifications]
    assert first.definition in definitions
    assert second.definition in definitions


def test_catalog_boundary_excludes_physical_tree_and_materialization_state() -> None:
    assert "record_tree" not in Catalog.__dict__
    assert "tree_entries" not in Catalog.__dict__
    assert "record_materialization" not in Catalog.__dict__
    assert "materializations_for" not in Catalog.__dict__
    assert not hasattr(MemoryCatalog(), "record_tree")
    assert not hasattr(MemoryCatalog(), "record_materialization")
