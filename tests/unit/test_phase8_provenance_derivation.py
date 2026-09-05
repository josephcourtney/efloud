from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from efloud.derivation import DerivedTaskSpec, derivation_key_for
from efloud.indexing import DerivedIndexDefinition, DerivedIndexRegistry
from efloud.models import EngineConfig
from efloud.query import index_payload
from efloud.repository import Repository
from efloud.repository_models import ProducerRef

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.json_types import JsonObject
    from efloud.repository_models import ArtifactObservation, RunId

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def _input_observation(
    repo: Repository,
    run_id: RunId,
    *,
    observed_at: float,
) -> ArtifactObservation:
    operation_id = repo.start_operation(
        run_id=run_id,
        kind="fixture-input",
        subject=f"input-{observed_at}",
        producer=ProducerRef("test:fixture-input", "1"),
    )
    observation = repo.ingest_bytes(
        "input:a",
        b"same input bytes",
        run_id=run_id,
        operation_id=operation_id,
        observed_at=observed_at,
    )
    repo.finish_operation(operation_id, status="succeeded", finished_at=observed_at + 0.1)
    return observation


def test_producer_identity_and_lifecycle_transitions_are_explicit(tmp_path: Path) -> None:
    with Repository(tmp_path) as repo:
        run_id = repo.start_run(started_at=1.0)
        producer = ProducerRef("test:worker", "7")
        operation_id = repo.start_operation(
            run_id=run_id,
            kind="work",
            subject="alpha",
            producer=producer,
            started_at=2.0,
        )
        operation = repo.metadata.operations_for_run(run_id)[0]
        assert operation.status == "running"
        assert operation.producer == producer

        with pytest.raises(ValueError, match="still running"):
            repo.finish_run(run_id, status="succeeded", finished_at=2.5)

        repo.finish_operation(operation_id, status="success", finished_at=3.0)
        operation = repo.metadata.operations_for_run(run_id)[0]
        assert operation.status == "succeeded"
        with pytest.raises(ValueError, match="cannot transition"):
            repo.finish_operation(operation_id, status="failed", finished_at=4.0)

        repo.finish_run(run_id, status="success", finished_at=5.0)
        run = repo.metadata.run(run_id)
        assert run is not None
        assert run.status == "succeeded"
        with pytest.raises(ValueError, match="cannot transition"):
            repo.finish_run(run_id, status="failed", finished_at=6.0)
        with pytest.raises(ValueError, match="terminal run"):
            repo.start_operation(run_id=run_id, kind="late", subject="late")


def test_producer_ids_must_be_namespaced_and_versioned() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        ProducerRef("worker", "1")
    with pytest.raises(ValueError, match="version"):
        ProducerRef("test:worker", "")


def test_content_derivation_reuses_content_with_fresh_observation_provenance(tmp_path: Path) -> None:
    spec = DerivedTaskSpec(
        task_id="test:derive",
        task_version="1",
        deterministic=True,
        dependency_semantics="content",
        parameters={"mode": "fixture"},
    )

    with Repository(tmp_path) as repo:
        first_run = repo.start_run(started_at=10.0)
        first_input = _input_observation(repo, first_run, observed_at=11.0)
        first_key = derivation_key_for(spec, outputs=("derived:a",), inputs=(first_input,))
        first_operation = repo.start_operation(
            run_id=first_run,
            kind="derive",
            subject="a",
            producer=spec.producer,
            parameters={"derivation_key": str(first_key)},
            started_at=12.0,
        )
        first_output = repo.record_derived_bytes(
            "derived:a",
            b"deterministic result",
            derivation_key=first_key,
            run_id=first_run,
            operation_id=first_operation,
            inputs=(first_input,),
            observed_at=13.0,
        )
        repo.finish_operation(first_operation, status="succeeded", finished_at=14.0)
        repo.finish_run(first_run, status="succeeded", finished_at=15.0)

        second_run = repo.start_run(started_at=20.0)
        second_input = _input_observation(repo, second_run, observed_at=21.0)
        second_key = derivation_key_for(spec, outputs=("derived:a",), inputs=(second_input,))
        assert second_input.observation_id != first_input.observation_id
        assert second_input.content_id == first_input.content_id
        assert second_key == first_key

        second_operation = repo.start_operation(
            run_id=second_run,
            kind="derive",
            subject="a",
            producer=spec.producer,
            parameters={"derivation_key": str(second_key)},
            started_at=22.0,
        )
        second_output = repo.record_derived_bytes(
            "derived:a",
            b"this would be wrong if recomputed",
            derivation_key=second_key,
            run_id=second_run,
            operation_id=second_operation,
            inputs=(second_input,),
            observed_at=23.0,
        )
        repo.finish_operation(second_operation, status="succeeded", finished_at=24.0)

        assert second_output.observation_id != first_output.observation_id
        assert second_output.content_id == first_output.content_id
        assert second_output.metadata["derivation_reused"] is True
        edges = repo.provenance_inputs(second_output.observation_id)
        assert len(edges) == 1
        assert edges[0].output_observation_id == second_output.observation_id
        assert edges[0].input_observation_id == second_input.observation_id
        assert edges[0].input_observation_id != first_input.observation_id
        with repo.open_content(second_output.content_id) as stream:
            assert stream.read() == b"deterministic result"


def test_observation_sensitive_derivations_distinguish_identical_bytes(tmp_path: Path) -> None:
    spec = DerivedTaskSpec(
        task_id="test:observation-sensitive",
        task_version="1",
        deterministic=True,
        dependency_semantics="observation",
        parameters={},
    )
    with Repository(tmp_path) as repo:
        first_run = repo.start_run(started_at=10.0)
        first = _input_observation(repo, first_run, observed_at=11.0)
        repo.finish_run(first_run, status="succeeded", finished_at=12.0)
        second_run = repo.start_run(started_at=20.0)
        second = _input_observation(repo, second_run, observed_at=21.0)
        assert first.content_id == second.content_id
        assert derivation_key_for(spec, outputs=("derived:a",), inputs=(first,)) != derivation_key_for(
            spec,
            outputs=("derived:a",),
            inputs=(second,),
        )


def test_semantic_index_reuses_by_derivation_key_without_ttl(tmp_path: Path) -> None:
    builds: list[str] = []

    def build_index(*, repository: Repository, inputs: tuple[ArtifactObservation, ...]) -> JsonObject:
        del repository
        builds.append(str(inputs[0].content_id))
        return {"input_content_id": str(inputs[0].content_id)}

    indexes = DerivedIndexRegistry([
        DerivedIndexDefinition(
            index_id="alpha",
            task_version="3",
            build=build_index,
            dependency_semantics="content",
            parameters={"schema": 2},
            description="Fixture semantic index",
        )
    ])

    with Repository(tmp_path) as repo:
        first_run = repo.start_run(started_at=100.0)
        first_input = _input_observation(repo, first_run, observed_at=101.0)
        first = indexes.build(
            "alpha",
            repository=repo,
            run_id=first_run,
            inputs=(first_input,),
            observed_at=102.0,
        )
        repo.finish_run(first_run, status="succeeded", finished_at=103.0)
        assert first.reused is False
        assert len(builds) == 1

    with Repository(tmp_path) as reopened:
        second_run = reopened.start_run(started_at=200.0)
        second_input = _input_observation(reopened, second_run, observed_at=201.0)
        second = indexes.build(
            "alpha",
            repository=reopened,
            run_id=second_run,
            inputs=(second_input,),
            observed_at=202.0,
        )
        assert second.reused is True
        assert len(builds) == 1
        assert second.observation.observation_id != first.observation.observation_id
        assert second.observation.content_id == first.observation.content_id
        assert second.payload == first.payload
        operation = next(
            operation
            for operation in reopened.metadata.operations_for_run(second_run)
            if operation.kind == "derive-index"
        )
        assert operation.producer == ProducerRef("efloud:index:alpha", "3")

    cfg = EngineConfig(root=tmp_path, sources=[], derived_index_registry=indexes)
    queried = index_payload("alpha", cfg=cfg)
    status = queried["status"]
    assert isinstance(status, dict)
    assert status["validity"] == "derivation-key"
    assert status["present"] is True
    assert "expired" not in status
    assert queried["payload"] == first.payload
