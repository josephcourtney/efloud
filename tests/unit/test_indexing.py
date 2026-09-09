from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from efloud.indexing import DerivedIndexDefinition, DerivedIndexRegistry
from efloud.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.medium]


def test_derived_index_reuses_matching_derivation(tmp_path: Path) -> None:
    builds: list[int] = []

    def build(*, repository, inputs):
        del repository, inputs
        builds.append(len(builds) + 1)
        return {"build": builds[-1]}

    registry = DerivedIndexRegistry((DerivedIndexDefinition("alpha", "1", build),))

    with Repository(tmp_path) as repository:
        first_run = repository.start_run(started_at=1.0)
        first = registry.build("alpha", repository=repository, run_id=first_run, observed_at=2.0)
        repository.finish_run(first_run, status="succeeded", finished_at=3.0)

        assert first.reused is False
        assert first.payload == {"build": 1}
        assert builds == [1]

        second_run = repository.start_run(started_at=4.0)
        second = registry.build("alpha", repository=repository, run_id=second_run, observed_at=5.0)
        repository.finish_run(second_run, status="succeeded", finished_at=6.0)

        assert second.reused is True
        assert second.payload == {"build": 1}
        assert second.observation.content_id == first.observation.content_id
        assert builds == [1]


def test_derived_index_parameters_change_derivation_identity(tmp_path: Path) -> None:
    builds: list[str] = []

    def builder(label: str):
        def build(*, repository, inputs):
            del repository, inputs
            builds.append(label)
            return {"label": label}

        return build

    first_registry = DerivedIndexRegistry(
        (DerivedIndexDefinition("alpha", "1", builder("first"), parameters={"mode": "a"}),)
    )
    second_registry = DerivedIndexRegistry(
        (DerivedIndexDefinition("alpha", "1", builder("second"), parameters={"mode": "b"}),)
    )

    with Repository(tmp_path) as repository:
        first_run = repository.start_run(started_at=1.0)
        first = first_registry.build("alpha", repository=repository, run_id=first_run, observed_at=2.0)
        repository.finish_run(first_run, status="succeeded", finished_at=3.0)

        second_run = repository.start_run(started_at=4.0)
        second = second_registry.build("alpha", repository=repository, run_id=second_run, observed_at=5.0)
        repository.finish_run(second_run, status="succeeded", finished_at=6.0)

    assert first.reused is False
    assert second.reused is False
    assert builds == ["first", "second"]
    assert first.observation.content_id != second.observation.content_id


def test_derived_index_registry_rejects_unknown_identifier(tmp_path: Path) -> None:
    with Repository(tmp_path) as repository:
        run = repository.start_run(started_at=1.0)
        with pytest.raises(ValueError, match="Unknown derived index identifier"):
            DerivedIndexRegistry().build("missing", repository=repository, run_id=run)
