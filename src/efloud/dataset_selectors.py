"""Snapshot and historical source selectors over the semantic read capability."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.repository_models import ArtifactAbsence, ArtifactObservation

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.repository_capabilities import DatasetRepository as RepositoryView
    from efloud.repository_models import SourceSnapshot


def snapshot_observations(repository: RepositoryView, snapshot: SourceSnapshot) -> tuple[ArtifactObservation, ...]:
    """Resolve only complete, unambiguous recorded membership."""
    if (
        not snapshot.complete
        or snapshot.evidence.get("reconciliation_complete") is False
        or snapshot.evidence.get("acquisition_complete") is False
    ):
        msg = f"Snapshot does not establish complete membership: {snapshot.snapshot_id}"
        raise ValueError(msg)
    candidates = tuple(
        observation
        for key in repository.artifact_keys()
        for observation in repository.observations_for(key)
        if observation.source_id == snapshot.source_id
        and observation.run_id == snapshot.run_id
        and observation.observed_at <= snapshot.observed_at
    )
    bound = snapshot.evidence.get("observation_ids")
    if isinstance(bound, list):
        selected = tuple(repository.observation(str(value)) for value in bound)
        if any(value is None or value not in candidates for value in selected):
            msg = f"Invalid snapshot observation binding: {snapshot.snapshot_id}"
            raise ValueError(msg)
        candidates = tuple(value for value in selected if value is not None)
    if snapshot.tree_id is not None:
        selected_tree: list[ArtifactObservation] = []
        for entry in repository.tree_entries(snapshot.tree_id):
            if entry.kind in {"directory", "symlink", "absent"}:
                continue
            matching = [
                observation
                for observation in candidates
                if observation.source_path == entry.relative_path and observation.content_id == entry.content_id
            ]
            if len(matching) != 1:
                msg = f"Snapshot member is unavailable or ambiguous: {entry.relative_path}"
                raise ValueError(msg)
            selected_tree.append(matching[0])
        candidates = tuple(selected_tree)
    elif bound is None and len(candidates) != 1:
        msg = f"Snapshot has no exact membership evidence: {snapshot.snapshot_id}"
        raise ValueError(msg)
    keys = [str(value.artifact_key) for value in candidates]
    if len(set(keys)) != len(keys):
        msg = "Snapshot contains ambiguous artifact observations"
        raise ValueError(msg)
    return tuple(sorted(candidates, key=lambda value: str(value.artifact_key)))


def _check_times(*values: float | None) -> None:
    if any(value is not None and not math.isfinite(value) for value in values):
        msg = "Observation time bounds must be finite"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExactSourceSnapshot:
    snapshot_id: str

    def resolve(self, repository: RepositoryView) -> tuple[ArtifactObservation, ...]:
        snapshot = repository.source_snapshot(self.snapshot_id)
        if snapshot is None:
            raise KeyError(self.snapshot_id)
        return snapshot_observations(repository, snapshot)

    def to_dict(self) -> JsonObject:
        return {"kind": "source-snapshot", "snapshot_id": self.snapshot_id}


@dataclass(frozen=True, slots=True)
class LatestCompleteSourceSnapshot:
    source_id: str
    before: float | None = None

    def __post_init__(self) -> None:
        """Reject non-finite temporal parameters."""
        _check_times(self.before)

    def snapshot(self, repository: RepositoryView) -> SourceSnapshot:
        for snapshot in repository.source_snapshots_for(self.source_id, limit=None):
            if snapshot.complete and (self.before is None or snapshot.observed_at <= self.before):
                return snapshot
        raise KeyError(self.source_id)

    def resolve(self, repository: RepositoryView) -> tuple[ArtifactObservation, ...]:
        return snapshot_observations(repository, self.snapshot(repository))

    def to_dict(self) -> JsonObject:
        return {
            "kind": "latest-complete-source-snapshot",
            "source_id": self.source_id,
            "before": self.before,
            "time_basis": "repository-observation",
        }


@dataclass(frozen=True, slots=True)
class SourceSelection:
    """Select current/as-of state using the observed source definition revision."""

    source_id: str | None = None
    role: str | None = None
    tags: tuple[str, ...] = ()
    prefix: str = ""
    after: float | None = None
    before: float | None = None

    def __post_init__(self) -> None:
        """Reject non-finite temporal parameters."""
        _check_times(self.after, self.before)

    def _matches(self, repository: RepositoryView, observation: ArtifactObservation) -> bool:
        if self.source_id is not None and observation.source_id != self.source_id:
            return False
        if self.after is not None and observation.observed_at < self.after:
            return False
        if self.role is None and not self.tags:
            return True
        source = repository.source(observation.source_id) if observation.source_id is not None else None
        revision_id = observation.metadata.get("source_definition_revision_id")
        revision = (
            next((item for item in source.revisions if item.revision_id == revision_id), None) if source else None
        )
        if revision is None:
            msg = f"Historical source definition is unknown: {observation.observation_id}"
            raise ValueError(msg)
        definition = revision.definition
        tags = definition.get("tags", [])
        return (self.role is None or definition.get("role") == self.role) and (
            isinstance(tags, list) and all(tag in tags for tag in self.tags)
        )

    def resolve(self, repository: RepositoryView) -> tuple[ArtifactObservation, ...]:
        if self.after is not None and self.before is not None and self.after > self.before:
            msg = "Observation interval is reversed"
            raise ValueError(msg)
        selected: list[ArtifactObservation] = []
        for key in repository.artifact_keys():
            if not str(key).startswith(self.prefix):
                continue
            state = repository.latest_state(key, before=self.before)
            if state is not None and not isinstance(state, ArtifactAbsence) and self._matches(repository, state):
                selected.append(state)
        return tuple(selected)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "kind": "source-selection",
            "source_id": self.source_id,
            "role_filter": self.role,
            "tags": [],
            "prefix": self.prefix,
            "after": self.after,
            "before": self.before,
            "time_basis": "repository-observation",
        }
        payload["tags"] = [str(item) for item in sorted(set(self.tags))]
        return payload
