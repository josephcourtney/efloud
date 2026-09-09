"""Versioned detached dataset handoff without a dependency on SQLite layout."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from efloud.datasets import DatasetManifest, ImmutableDataset
from efloud.json_types import JsonObject, is_json_object
from efloud.metadata_envelopes import dataset_specification_id, source_definition_revision_id
from efloud.metadata_store import DatasetMemberRecord
from efloud.repository_models import (
    ArtifactKey,
    ContentId,
    DatasetId,
    ObservationId,
    OperationId,
    RunId,
    canonical_json_bytes,
    observation_id_for,
    stable_id,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from efloud.repository_capabilities import DatasetRepository as RepositoryView

_CONTROL_CHARACTER_LIMIT = 32
_SHA256_HEX_LENGTH = 64

MANIFEST_FILENAME = "dataset-manifest.json"


def safe_export_path(value: str) -> str:
    """Reject platform-dependent and escaping paths instead of normalizing them."""
    path = PurePosixPath(value)
    if (
        not value
        or value == "."
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {".", ".."} or part.endswith((".", " ")) for part in path.parts)
        or any(char in "\\:\x00" or ord(char) < _CONTROL_CHARACTER_LIMIT for char in value)
    ):
        msg = f"Unsafe logical export path: {value!r}"
        raise ValueError(msg)
    return value


def _object(value: object) -> JsonObject:
    if not is_json_object(value):
        msg = "Manifest requires a JSON object"
        raise ValueError(msg)
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        msg = "Manifest requires a string"
        raise TypeError(msg)
    return value


@dataclass(frozen=True, slots=True)
class DetachedMember:
    artifact_key: str
    observation_id: str
    content_id: str
    role: str | None
    path: str
    byte_size: int
    media_type: str | None
    observation: JsonObject
    source_revision: JsonObject | None

    def to_dict(self) -> JsonObject:
        return {
            "artifact_key": self.artifact_key,
            "observation_id": self.observation_id,
            "content_id": self.content_id,
            "role": self.role,
            "path": self.path,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "observation": self.observation,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, value: JsonObject) -> DetachedMember:
        size = value.get("byte_size")
        if type(size) is not int or size < 0:
            msg = "Manifest content size must be a nonnegative integer"
            raise ValueError(msg)
        role = value.get("role")
        media_type = value.get("media_type")
        revision = value.get("source_revision")
        return cls(
            _text(value.get("artifact_key")),
            _text(value.get("observation_id")),
            _text(value.get("content_id")),
            None if role is None else _text(role),
            safe_export_path(_text(value.get("path"))),
            size,
            None if media_type is None else _text(media_type),
            _object(value.get("observation")),
            None if revision is None else _object(revision),
        )


def _validate_observation_identity(member: DetachedMember) -> None:
    evidence = member.observation
    observed_at = evidence.get("observed_at")
    if not isinstance(observed_at, int | float) or not math.isfinite(observed_at):
        msg = "Detached observation time must be finite"
        raise ValueError(msg)
    source_path = evidence.get("source_path")
    locator = evidence.get("upstream_locator")
    expected = observation_id_for(
        artifact_key=ArtifactKey(member.artifact_key),
        content_id=ContentId(member.content_id),
        run_id=RunId(_text(evidence.get("run_id"))),
        operation_id=OperationId(_text(evidence.get("operation_id"))),
        observed_at=observed_at,
        source_path=None if source_path is None else _text(source_path),
        upstream_locator=None if locator is None else _text(locator),
    )
    if str(expected) != member.observation_id:
        msg = "Detached observation identity mismatch"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DetachedDatasetManifest:
    dataset_id: str
    content_identity: str
    definition: JsonObject
    members: tuple[DetachedMember, ...]
    resolution: JsonObject

    def to_dict(self) -> JsonObject:
        return {
            "version": 1,
            "dataset_id": self.dataset_id,
            "content_identity": self.content_identity,
            "specification_id": str(dataset_specification_id(self.definition)),
            "definition": self.definition,
            "members": [member.to_dict() for member in self.members],
            "resolution": self.resolution,
        }

    def to_bytes(self) -> bytes:
        payload = self.to_dict()
        return canonical_json_bytes({**payload, "manifest_id": stable_id("dataset-manifest-v1", payload)}) + b"\n"

    def validate(self) -> None:
        exact = [
            {"artifact_key": member.artifact_key, "observation_id": member.observation_id, "role": member.role}
            for member in self.members
        ]
        content = [
            {"artifact_key": member.artifact_key, "content_id": member.content_id, "role": member.role}
            for member in self.members
        ]
        keys = [member.artifact_key for member in self.members]
        if (
            keys != sorted(set(keys))
            or stable_id("dataset", exact) != self.dataset_id
            or stable_id("dataset-content", content) != self.content_identity
        ):
            msg = "Detached dataset membership identity mismatch"
            raise ValueError(msg)
        for member in self.members:
            if member.source_revision is not None:
                revision = member.source_revision
                source_id = _text(member.observation.get("source_id"))
                expected = source_definition_revision_id(source_id, _object(revision.get("definition")))
                if revision.get("revision_id") != str(expected):
                    msg = "Detached source revision identity mismatch"
                    raise ValueError(msg)
            _validate_observation_identity(member)
            safe_export_path(member.path)
            digest = member.content_id.removeprefix("sha256:")
            if (
                not member.content_id.startswith("sha256:")
                or len(digest) != _SHA256_HEX_LENGTH
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                msg = "Invalid detached content identity"
                raise ValueError(msg)
            for key, expected in (
                ("artifact_key", member.artifact_key),
                ("observation_id", member.observation_id),
                ("content_id", member.content_id),
            ):
                if member.observation.get(key) != expected:
                    msg = f"Detached observation disagrees with member {key}"
                    raise ValueError(msg)

    @classmethod
    def from_bytes(cls, data: bytes) -> DetachedDatasetManifest:
        value = _object(json.loads(data))
        identity = value.pop("manifest_id", None)
        if (
            type(value.get("version")) is not int
            or value.get("version") != 1
            or identity != stable_id("dataset-manifest-v1", value)
        ):
            msg = "Unsupported or damaged detached dataset manifest"
            raise ValueError(msg)
        raw_members = value.get("members")
        if not isinstance(raw_members, list):
            msg = "Manifest members must be an array"
            raise TypeError(msg)
        result = cls(
            _text(value.get("dataset_id")),
            _text(value.get("content_identity")),
            _object(value.get("definition")),
            tuple(DetachedMember.from_dict(_object(item)) for item in raw_members),
            _object(value.get("resolution")),
        )
        if value.get("specification_id") != str(dataset_specification_id(result.definition)):
            msg = "Detached specification identity mismatch"
            raise ValueError(msg)
        result.validate()
        return result

    def verify(self, root: Path) -> bool:
        """Verify a detached export using only its manifest and local bytes."""
        self.validate()
        try:
            resolved_root = root.resolve(strict=True)
        except OSError:
            return False
        if not resolved_root.is_dir():
            return False
        for member in self.members:
            path = root / member.path
            try:
                if not path.resolve(strict=True).is_relative_to(resolved_root):
                    return False
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if path.stat().st_size != member.byte_size or f"sha256:{digest}" != member.content_id:
                    return False
            except OSError:
                return False
        return True


def export_dataset_manifest(
    dataset: ImmutableDataset, *, paths: Mapping[str, str] | None = None
) -> DetachedDatasetManifest:
    members: list[DetachedMember] = []
    for member in dataset.artifacts():
        observation = dataset.repository.observation(member.observation_id)
        content = dataset.repository.content(member.content_id)
        if observation is None or content is None:
            msg = f"Dataset evidence unavailable: {member.artifact_key}"
            raise ValueError(msg)
        source = dataset.repository.source(observation.source_id) if observation.source_id is not None else None
        revision = (
            next(
                (
                    item
                    for item in source.revisions
                    if item.revision_id == observation.metadata.get("source_definition_revision_id")
                ),
                None,
            )
            if source
            else None
        )
        path = (
            paths[str(member.artifact_key)]
            if paths is not None
            else ("artifacts/" + hashlib.sha256(str(member.artifact_key).encode()).hexdigest())
        )
        members.append(
            DetachedMember(
                str(member.artifact_key),
                str(member.observation_id),
                str(member.content_id),
                member.role,
                safe_export_path(path),
                content.byte_size,
                content.media_type,
                observation.to_dict(),
                revision.to_dict() if revision is not None else None,
            )
        )
    result = DetachedDatasetManifest(
        str(dataset.id),
        dataset.content_identity,
        dataset.manifest.definition,
        tuple(members),
        _object(dataset.manifest.metadata.get("resolution", {})),
    )
    result.validate()
    return result


def import_dataset_manifest(repository: RepositoryView, manifest: DetachedDatasetManifest) -> ImmutableDataset:
    """Reopen exact membership in another repository without acquiring or writing."""
    manifest.validate()
    members: list[DatasetMemberRecord] = []
    for member in manifest.members:
        observation = repository.observation(member.observation_id)
        content = repository.content(member.content_id)
        if (
            observation is None
            or content is None
            or content.byte_size != member.byte_size
            or content.media_type != member.media_type
        ):
            msg = f"Detached member cannot be verified: {member.artifact_key}"
            raise ValueError(msg)
        if observation.to_dict() != member.observation or not repository.verify_content(member.content_id):
            msg = f"Detached member cannot be verified: {member.artifact_key}"
            raise ValueError(msg)
        source_id = observation.source_id
        source = repository.source(source_id) if source_id is not None else None
        revision = (
            next(
                (
                    item
                    for item in source.revisions
                    if str(item.revision_id) == observation.metadata.get("source_definition_revision_id")
                ),
                None,
            )
            if source
            else None
        )
        if member.source_revision != (revision.to_dict() if revision is not None else None):
            msg = f"Detached source revision cannot be verified: {member.artifact_key}"
            raise ValueError(msg)
        members.append(
            DatasetMemberRecord(
                ArtifactKey(member.artifact_key),
                ObservationId(member.observation_id),
                ContentId(member.content_id),
                member.role,
            )
        )
    return ImmutableDataset(
        repository,
        DatasetManifest(
            DatasetId(manifest.dataset_id),
            manifest.content_identity,
            0.0,
            manifest.definition,
            tuple(members),
            {"resolution": manifest.resolution},
        ),
    )
