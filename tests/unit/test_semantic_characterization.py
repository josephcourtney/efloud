from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from efloud.dataset_export import export_dataset_manifest
from efloud.datasets import DatasetDefinition, DatasetSelection, ExactObservation
from efloud.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


def _resolve_two_source_dataset(repository: Repository):
    left = repository.register_source("left", {"kind": "test", "role": "left"})
    right = repository.register_source("right", {"kind": "test", "role": "right"})
    run = repository.start_run(source_ids=(left, right), started_at=100.0)
    left_operation = repository.start_operation(
        run_id=run,
        source_id=left,
        kind="fetch",
        subject="left",
        started_at=100.0,
    )
    right_operation = repository.start_operation(
        run_id=run,
        source_id=right,
        kind="fetch",
        subject="right",
        started_at=100.0,
    )
    left_observation = repository.ingest_bytes(
        "artifact:left",
        b"left payload",
        run_id=run,
        operation_id=left_operation,
        source_id=left,
        observed_at=101.0,
        source_path="left.dat",
    )
    right_observation = repository.ingest_bytes(
        "artifact:right",
        b"right payload",
        run_id=run,
        operation_id=right_operation,
        source_id=right,
        observed_at=102.0,
        source_path="right.dat",
    )
    definition = DatasetDefinition(
        (
            DatasetSelection(ExactObservation(left_observation.observation_id), role="left-role"),
            DatasetSelection(ExactObservation(right_observation.observation_id), role="right-role"),
        )
    )
    return repository.resolve_dataset(definition)


def test_multi_source_dataset_preserves_source_and_role_evidence(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        dataset = _resolve_two_source_dataset(repository)
        members = dataset.artifacts()

        assert [(str(member.artifact_key), member.role) for member in members] == [
            ("artifact:left", "left-role"),
            ("artifact:right", "right-role"),
        ]
        assert [
            str(repository.observation(member.observation_id).source_id)  # type: ignore[union-attr]
            for member in members
        ] == ["left", "right"]

        detached = export_dataset_manifest(dataset)
        assert [member.observation["source_id"] for member in detached.members] == ["left", "right"]
        assert [member.source_revision["definition"]["role"] for member in detached.members] == [  # type: ignore[index]
            "left",
            "right",
        ]


def test_dataset_identity_is_independent_of_detached_export_layout(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        dataset = _resolve_two_source_dataset(repository)

        first = export_dataset_manifest(
            dataset,
            paths={
                "artifact:left": "layout-a/left.dat",
                "artifact:right": "layout-a/right.dat",
            },
        )
        second = export_dataset_manifest(
            dataset,
            paths={
                "artifact:left": "other/left.bin",
                "artifact:right": "other/right.bin",
            },
        )

        assert first.dataset_id == second.dataset_id == str(dataset.id)
        assert first.content_identity == second.content_identity == dataset.content_identity
        assert [member.path for member in first.members] != [member.path for member in second.members]
