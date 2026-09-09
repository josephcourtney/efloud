from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, BinaryIO, Protocol

from efloud.dataset_constraints import DatasetConstraintError, DatasetConstraints
from efloud.dataset_selectors import ExactSourceSnapshot, LatestCompleteSourceSnapshot
from efloud.metadata_envelopes import dataset_specification_id
from efloud.metadata_store import DatasetMemberRecord, DatasetRecord
from efloud.repository_models import (
    ArtifactAbsence,
    ArtifactKey,
    ArtifactObservation,
    DatasetId,
    DatasetSpecificationId,
    ObservationId,
    stable_id,
)

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.repository_capabilities import DatasetRepository as RepositoryView


class DatasetSelector(Protocol):
    def resolve(self, repository: RepositoryView) -> tuple[ArtifactObservation, ...]: ...

    def to_dict(self) -> JsonObject: ...


@dataclass(frozen=True, slots=True)
class ExactObservation:
    observation_id: ObservationId | str

    def resolve(self, repository: RepositoryView) -> tuple[ArtifactObservation, ...]:
        observation = repository.observation(self.observation_id)
        if observation is None:
            msg = f"Unknown observation: {self.observation_id}"
            raise KeyError(msg)
        return (observation,)

    def to_dict(self) -> JsonObject:
        return {"kind": "exact", "observation_id": str(self.observation_id)}


@dataclass(frozen=True, slots=True)
class Latest:
    artifact_key: ArtifactKey | str

    def resolve(self, repository: RepositoryView) -> tuple[ArtifactObservation, ...]:
        state = repository.latest_state(self.artifact_key)
        if state is None or isinstance(state, ArtifactAbsence):
            msg = f"Artifact is absent: {self.artifact_key}"
            raise KeyError(msg)
        return (state,)

    def to_dict(self) -> JsonObject:
        return {"kind": "latest", "artifact_key": str(self.artifact_key)}


@dataclass(frozen=True, slots=True)
class LatestBefore:
    artifact_key: ArtifactKey | str
    timestamp: float

    def resolve(self, repository: RepositoryView) -> tuple[ArtifactObservation, ...]:
        state = repository.latest_state(self.artifact_key, before=self.timestamp)
        if state is None or isinstance(state, ArtifactAbsence):
            msg = f"Artifact is absent at or before {self.timestamp}: {self.artifact_key}"
            raise KeyError(msg)
        return (state,)

    def to_dict(self) -> JsonObject:
        return {
            "kind": "latest-before",
            "artifact_key": str(self.artifact_key),
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class LatestAll:
    before: float | None = None

    def resolve(self, repository: RepositoryView) -> tuple[ArtifactObservation, ...]:
        selected: list[ArtifactObservation] = []
        for artifact_key in repository.artifact_keys():
            state = repository.latest_state(artifact_key, before=self.before)
            if state is not None and not isinstance(state, ArtifactAbsence):
                selected.append(state)
        return tuple(selected)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {"kind": "latest-all"}
        if self.before is not None:
            payload["before"] = self.before
        return payload


@dataclass(frozen=True, slots=True)
class DatasetSelection:
    selector: DatasetSelector
    role: str | None = None

    def to_dict(self) -> JsonObject:
        payload = self.selector.to_dict()
        if self.role is not None:
            payload = dict(payload)
            payload["role"] = self.role
        return payload


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    selections: tuple[DatasetSelection, ...]
    metadata: JsonObject = field(default_factory=dict)
    constraints: DatasetConstraints = field(default_factory=DatasetConstraints)

    @classmethod
    def from_selectors(cls, *selectors: DatasetSelector) -> DatasetDefinition:
        return cls(tuple(DatasetSelection(selector) for selector in selectors))

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "selections": [selection.to_dict() for selection in self.selections],
            "metadata": dict(self.metadata),
        }
        if self.constraints != DatasetConstraints():
            payload["constraints"] = self.constraints.to_dict()
        return payload

    @property
    def specification_id(self) -> DatasetSpecificationId:
        """Stable identity of the intensional dataset definition."""
        return dataset_specification_id(self.to_dict())


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_id: DatasetId
    content_identity: str
    created_at: float
    definition: JsonObject
    members: tuple[DatasetMemberRecord, ...]
    metadata: JsonObject = field(default_factory=dict)

    @property
    def specification_id(self) -> DatasetSpecificationId:
        """Stable identity of the definition that produced this manifest."""
        return dataset_specification_id(self.definition)

    def to_record(self) -> DatasetRecord:
        return DatasetRecord(
            dataset_id=self.dataset_id,
            content_identity=self.content_identity,
            created_at=self.created_at,
            definition=self.definition,
            metadata=self.metadata,
            members=self.members,
        )

    @classmethod
    def from_record(cls, record: DatasetRecord) -> DatasetManifest:
        return cls(
            dataset_id=record.dataset_id,
            content_identity=record.content_identity,
            created_at=record.created_at,
            definition=record.definition,
            metadata=record.metadata,
            members=record.members,
        )


@dataclass(frozen=True, slots=True)
class ImmutableDataset:
    repository: RepositoryView
    manifest: DatasetManifest

    @property
    def id(self) -> DatasetId:
        return self.manifest.dataset_id

    @property
    def specification_id(self) -> DatasetSpecificationId:
        return self.manifest.specification_id

    @property
    def content_identity(self) -> str:
        return self.manifest.content_identity

    def artifacts(self) -> tuple[DatasetMemberRecord, ...]:
        return self.manifest.members

    def artifact(self, artifact_key: ArtifactKey | str) -> DatasetMemberRecord:
        wanted = str(artifact_key)
        for member in self.manifest.members:
            if str(member.artifact_key) == wanted:
                return member
        msg = f"Artifact is not part of dataset {self.id}: {artifact_key}"
        raise KeyError(msg)

    def open(self, artifact_key: ArtifactKey | str) -> BinaryIO:
        member = self.artifact(artifact_key)
        return self.repository.open_content(member.content_id)

    def verify(self) -> bool:
        return all(self.repository.verify_content(member.content_id) for member in self.manifest.members)


def resolve_dataset(
    repository: RepositoryView,
    definition: DatasetDefinition,
    *,
    created_at: float | None = None,
) -> DatasetManifest:
    resolved: list[tuple[ArtifactObservation, str | None]] = []
    snapshot_ids: list[str] = []
    for selection in definition.selections:
        selector = selection.selector
        if isinstance(selector, LatestCompleteSourceSnapshot):
            selector = ExactSourceSnapshot(str(selector.snapshot(repository).snapshot_id))
        if isinstance(selector, ExactSourceSnapshot):
            snapshot_ids.append(str(selector.snapshot_id))
        resolved.extend((observation, selection.role) for observation in selector.resolve(repository))

    resolved.sort(key=lambda item: (str(item[0].artifact_key), item[1] or "", str(item[0].observation_id)))
    seen: set[str] = set()
    members: list[DatasetMemberRecord] = []
    for observation, role in resolved:
        key = str(observation.artifact_key)
        if key in seen:
            msg = f"Dataset resolves artifact more than once: {key}"
            raise ValueError(msg)
        seen.add(key)
        members.append(
            DatasetMemberRecord(
                artifact_key=observation.artifact_key,
                observation_id=observation.observation_id,
                content_id=observation.content_id,
                role=role,
            )
        )

    if not resolved and definition.constraints.complete_snapshots and not snapshot_ids:
        raise DatasetConstraintError((
            {
                "constraint": "complete-snapshot",
                "passed": False,
                "reason": "empty selection has no complete snapshot evidence",
            },
        ))
    constraint_results = definition.constraints.check(repository, tuple(item[0] for item in resolved))
    identity_payload = [
        {
            "artifact_key": str(member.artifact_key),
            "observation_id": str(member.observation_id),
            "role": member.role,
        }
        for member in members
    ]
    content_payload = [
        {
            "artifact_key": str(member.artifact_key),
            "content_id": str(member.content_id),
            "role": member.role,
        }
        for member in members
    ]
    dataset_id = DatasetId(stable_id("dataset", identity_payload))
    content_identity = stable_id("dataset-content", content_payload)
    resolution: JsonObject = {}
    resolution["snapshot_ids"] = [str(item) for item in sorted(set(snapshot_ids))]
    resolution["constraint_results"] = list(constraint_results)
    resolution["snapshots"] = [
        snapshot.to_dict()
        for snapshot_id in sorted(set(snapshot_ids))
        if (snapshot := repository.source_snapshot(snapshot_id)) is not None
    ]
    return DatasetManifest(
        dataset_id=dataset_id,
        content_identity=content_identity,
        created_at=time.time() if created_at is None else created_at,
        definition=definition.to_dict(),
        members=tuple(members),
        metadata={**definition.metadata, "resolution": resolution},
    )


__all__ = [
    "DatasetDefinition",
    "DatasetManifest",
    "DatasetSelection",
    "DatasetSelector",
    "ExactObservation",
    "ImmutableDataset",
    "Latest",
    "LatestAll",
    "LatestBefore",
    "resolve_dataset",
]
