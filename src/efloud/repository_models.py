from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NewType

if TYPE_CHECKING:
    from efloud.json_types import JsonObject

SourceId = NewType("SourceId", str)
ArtifactKey = NewType("ArtifactKey", str)
ContentId = NewType("ContentId", str)
ObservationId = NewType("ObservationId", str)
RunId = NewType("RunId", str)
OperationId = NewType("OperationId", str)
SnapshotId = NewType("SnapshotId", str)
TreeId = NewType("TreeId", str)
DatasetId = NewType("DatasetId", str)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"{prefix}:{digest}"


@dataclass(frozen=True, slots=True)
class ContentRef:
    content_id: ContentId
    byte_size: int
    storage_key: str
    media_type: str | None = None

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "content_id": str(self.content_id),
            "byte_size": self.byte_size,
            "storage_key": self.storage_key,
        }
        if self.media_type is not None:
            payload["media_type"] = self.media_type
        return payload


@dataclass(frozen=True, slots=True)
class ArtifactObservation:
    observation_id: ObservationId
    artifact_key: ArtifactKey
    content_id: ContentId
    source_id: SourceId | None
    run_id: RunId
    operation_id: OperationId
    observed_at: float
    source_path: str | None = None
    upstream_locator: str | None = None
    upstream_modified_at: float | None = None
    upstream_version: str | None = None
    media_type: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "observation_id": str(self.observation_id),
            "artifact_key": str(self.artifact_key),
            "content_id": str(self.content_id),
            "run_id": str(self.run_id),
            "operation_id": str(self.operation_id),
            "observed_at": self.observed_at,
            "metadata": dict(self.metadata),
        }
        if self.source_id is not None:
            payload["source_id"] = str(self.source_id)
        if self.source_path is not None:
            payload["source_path"] = self.source_path
        if self.upstream_locator is not None:
            payload["upstream_locator"] = self.upstream_locator
        if self.upstream_modified_at is not None:
            payload["upstream_modified_at"] = self.upstream_modified_at
        if self.upstream_version is not None:
            payload["upstream_version"] = self.upstream_version
        if self.media_type is not None:
            payload["media_type"] = self.media_type
        return payload


@dataclass(frozen=True, slots=True)
class ArtifactAbsence:
    observation_id: ObservationId
    artifact_key: ArtifactKey
    source_id: SourceId | None
    run_id: RunId
    operation_id: OperationId
    observed_at: float
    source_path: str | None = None
    upstream_locator: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "observation_id": str(self.observation_id),
            "artifact_key": str(self.artifact_key),
            "run_id": str(self.run_id),
            "operation_id": str(self.operation_id),
            "observed_at": self.observed_at,
            "absent": True,
            "metadata": dict(self.metadata),
        }
        if self.source_id is not None:
            payload["source_id"] = str(self.source_id)
        if self.source_path is not None:
            payload["source_path"] = self.source_path
        if self.upstream_locator is not None:
            payload["upstream_locator"] = self.upstream_locator
        return payload


type ArtifactState = ArtifactObservation | ArtifactAbsence


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    output_observation_id: ObservationId
    input_observation_id: ObservationId
    relationship: str = "derived-from"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    content_id: ContentId
    validator: str
    validator_version: str
    checked_at: float
    status: str
    details: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TreeEntry:
    relative_path: str
    kind: str
    content_id: ContentId | None = None
    byte_size: int | None = None
    target: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def identity_payload(self) -> JsonObject:
        payload: JsonObject = {"path": self.relative_path, "kind": self.kind}
        if self.content_id is not None:
            payload["content_id"] = str(self.content_id)
        if self.byte_size is not None:
            payload["byte_size"] = self.byte_size
        if self.target is not None:
            payload["target"] = self.target
        return payload


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    snapshot_id: SnapshotId
    source_id: SourceId
    run_id: RunId
    observed_at: float
    complete: bool
    tree_id: TreeId | None = None
    scope: tuple[str, ...] = ()
    evidence: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "snapshot_id": str(self.snapshot_id),
            "source_id": str(self.source_id),
            "run_id": str(self.run_id),
            "observed_at": self.observed_at,
            "complete": self.complete,
            "scope": list(self.scope),
            "evidence": dict(self.evidence),
        }
        if self.tree_id is not None:
            payload["tree_id"] = str(self.tree_id)
        return payload


def observation_id_for(
    *,
    artifact_key: ArtifactKey,
    content_id: ContentId,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    source_path: str | None,
    upstream_locator: str | None,
) -> ObservationId:
    return ObservationId(
        stable_id(
            "obs",
            {
                "kind": "content",
                "artifact_key": str(artifact_key),
                "content_id": str(content_id),
                "run_id": str(run_id),
                "operation_id": str(operation_id),
                "observed_at": observed_at,
                "source_path": source_path,
                "upstream_locator": upstream_locator,
            },
        )
    )


def absence_id_for(
    *,
    artifact_key: ArtifactKey,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
    source_path: str | None,
    upstream_locator: str | None,
) -> ObservationId:
    return ObservationId(
        stable_id(
            "obs",
            {
                "kind": "absence",
                "artifact_key": str(artifact_key),
                "run_id": str(run_id),
                "operation_id": str(operation_id),
                "observed_at": observed_at,
                "source_path": source_path,
                "upstream_locator": upstream_locator,
            },
        )
    )


def run_id_for(*, root: str, started_at: float, source_ids: tuple[str, ...]) -> RunId:
    return RunId(
        stable_id(
            "run",
            {"root": root, "started_at": started_at, "source_ids": list(source_ids)},
        )
    )


def operation_id_for(*, run_id: RunId, kind: str, subject: str) -> OperationId:
    return OperationId(
        stable_id(
            "op",
            {"run_id": str(run_id), "kind": kind, "subject": subject},
        )
    )


__all__ = [
    "ArtifactAbsence",
    "ArtifactKey",
    "ArtifactObservation",
    "ArtifactState",
    "ContentId",
    "ContentRef",
    "DatasetId",
    "ObservationId",
    "OperationId",
    "ProvenanceEdge",
    "RunId",
    "SnapshotId",
    "SourceId",
    "SourceSnapshot",
    "TreeEntry",
    "TreeId",
    "ValidationResult",
    "absence_id_for",
    "canonical_json_bytes",
    "observation_id_for",
    "operation_id_for",
    "run_id_for",
    "stable_id",
]
