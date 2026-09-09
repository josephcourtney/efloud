"""Explicit, acquisition-free dataset coherence checks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.dataset_selectors import snapshot_observations

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.repository_models import ArtifactObservation
    from efloud.repository_view import RepositoryView


class DatasetConstraintError(ValueError):
    """Resolution failure with machine-readable constraint results."""

    def __init__(self, results: tuple[JsonObject, ...]) -> None:
        self.results = results
        super().__init__(f"Dataset constraints failed: {results}")


@dataclass(frozen=True, slots=True)
class DatasetConstraints:
    same_run: bool = False
    max_observation_skew: float | None = None
    complete_snapshots: bool = False
    validations: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Reject non-finite temporal parameters."""
        if self.max_observation_skew is not None and (
            not math.isfinite(self.max_observation_skew) or self.max_observation_skew < 0
        ):
            msg = "Maximum observation skew must be finite and nonnegative"
            raise ValueError(msg)

    def to_dict(self) -> JsonObject:
        return {
            "same_run": self.same_run,
            "max_observation_skew": self.max_observation_skew,
            "complete_snapshots": self.complete_snapshots,
            "validations": [list(item) for item in sorted(set(self.validations))],
        }

    def check(
        self, repository: RepositoryView, observations: tuple[ArtifactObservation, ...]
    ) -> tuple[JsonObject, ...]:
        results: list[JsonObject] = []
        if self.same_run:
            results.append({"constraint": "same-run", "passed": len({obs.run_id for obs in observations}) <= 1})
        if self.max_observation_skew is not None:
            times = [obs.observed_at for obs in observations]
            skew = max(times) - min(times) if times else 0.0
            results.append({
                "constraint": "observation-skew",
                "actual": skew,
                "passed": 0 <= skew <= self.max_observation_skew,
            })
        for observation in observations:
            if self.complete_snapshots:
                results.append(self._snapshot_check(repository, observation))
            for validator, version in sorted(set(self.validations)):
                result = repository.validation(observation.content_id, validator, version)
                results.append({
                    "constraint": "validation",
                    "observation_id": str(observation.observation_id),
                    "validator": validator,
                    "version": version,
                    "passed": result is not None and result.status == "passed",
                    "evidence": result.to_dict() if result is not None else None,
                })
        if any(result["passed"] is not True for result in results):
            raise DatasetConstraintError(tuple(results))
        return tuple(results)

    @staticmethod
    def _snapshot_check(repository: RepositoryView, observation: ArtifactObservation) -> JsonObject:
        matched: list[str] = []
        if observation.source_id is not None:
            for snapshot in repository.source_snapshots_for(observation.source_id, limit=-1):
                if snapshot.complete and snapshot.run_id == observation.run_id:
                    try:
                        members = snapshot_observations(repository, snapshot)
                    except ValueError:
                        continue
                    if observation in members:
                        matched.append(str(snapshot.snapshot_id))
        result: JsonObject = {
            "constraint": "complete-snapshot",
            "observation_id": str(observation.observation_id),
            "snapshot_ids": [],
            "passed": bool(matched),
        }
        result["snapshot_ids"] = [str(item) for item in sorted(matched)]
        return result
