from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.json_types import JsonObject, JsonValue
from efloud.locator import apply_structured_locator, locator_candidates, split_locator
from efloud.repository_models import ArtifactAbsence, ArtifactObservation, ObservationId, SnapshotId

if TYPE_CHECKING:
    from efloud.metadata_store import DatasetMemberRecord
    from efloud.repository import Repository
    from efloud.repository_models import SourceSnapshot


def _member_payload(member: DatasetMemberRecord) -> JsonObject:
    payload: JsonObject = {
        "artifact_key": str(member.artifact_key),
        "observation_id": str(member.observation_id),
        "content_id": str(member.content_id),
    }
    if member.role is not None:
        payload["role"] = member.role
    return payload


def _snapshot_payload(repository: Repository, snapshot: SourceSnapshot) -> JsonObject:
    payload = snapshot.to_dict()
    if snapshot.tree_id is not None:
        payload["entries"] = [entry.identity_payload() for entry in repository.tree_entries(snapshot.tree_id)]
    return payload


def _payload_bytes(repository: Repository, observation: ArtifactObservation) -> bytes:
    with repository.open_content(observation.content_id) as stream:
        data = stream.read()
    name = observation.source_path or observation.upstream_locator or ""
    if name.lower().endswith(".gz"):
        try:
            return gzip.decompress(data)
        except OSError:
            return data
    return data


def _looks_json(observation: ArtifactObservation) -> bool:
    if observation.media_type is not None and "json" in observation.media_type.lower():
        return True
    name = (observation.source_path or observation.upstream_locator or "").lower()
    return name.endswith(".json") or name.endswith(".json.gz")


def _resolve_text_locator(text: str, locator: str) -> tuple[JsonValue | None, str | None]:
    loc = locator.strip()
    if loc == "text":
        return text, None
    if loc.startswith("line:"):
        value = loc.removeprefix("line:").strip()
        if not value.isdigit() or int(value) < 1:
            return None, f"Invalid line locator: {locator!r}"
        lines = text.splitlines()
        index = int(value) - 1
        if index >= len(lines):
            return None, f"Line {index + 1} out of range (1..{len(lines)})"
        return lines[index], None
    if loc.startswith("lines:"):
        value = loc.removeprefix("lines:").strip()
        match = re.fullmatch(r"(\d+)-(\d+)", value)
        if match is None:
            return None, f"Invalid lines locator: {locator!r}"
        start = int(match.group(1))
        end = int(match.group(2))
        lines = text.splitlines()
        if start < 1 or end < start or end > len(lines):
            return None, f"Line range {start}-{end} out of range (1..{len(lines)})"
        return "\n".join(lines[start - 1 : end]), None
    if loc.startswith("regex:"):
        pattern = loc.removeprefix("regex:")
        try:
            match = re.search(pattern, text, re.MULTILINE)
        except re.error as exc:
            return None, f"Invalid regex locator: {exc}"
        if match is None:
            return None, f"Regex locator did not match: {pattern!r}"
        return match.group(1) if match.lastindex else match.group(0), None
    return None, f"Unsupported text locator: {locator!r}"


def _resolve_locator(
    repository: Repository,
    observation: ArtifactObservation,
    locator: str,
) -> JsonObject:
    data = _payload_bytes(repository, observation)
    errors: list[str] = []
    if _looks_json(observation):
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {
                "requested": locator,
                "resolved": None,
                "value": None,
                "error": f"Failed to decode JSON content: {exc}",
            }
        for candidate in locator_candidates(locator):
            resolved, error = apply_structured_locator(value, candidate)
            if error is None:
                return {
                    "requested": locator,
                    "resolved": candidate,
                    "value": resolved,
                    "error": None,
                }
            errors.append(f"{candidate}: {error}")
    else:
        text = data.decode("utf-8", errors="replace")
        for candidate in locator_candidates(locator):
            resolved, error = _resolve_text_locator(text, candidate)
            if error is None:
                return {
                    "requested": locator,
                    "resolved": candidate,
                    "value": resolved,
                    "error": None,
                }
            errors.append(f"{candidate}: {error}")
    return {
        "requested": locator,
        "resolved": None,
        "value": None,
        "error": "Locator evaluation failed: " + " | ".join(errors),
    }


@dataclass(frozen=True, slots=True)
class RepositoryQueryService:
    repository: Repository

    def query(self, raw: str) -> JsonObject:
        target, locator = split_locator(raw.strip())
        if not target:
            msg = "Repository query target must not be empty."
            raise ValueError(msg)
        prefix, separator, identifier = target.partition(":")
        if not separator or not identifier:
            msg = (
                "Repository query targets must use one of: artifact:<key>, observation:<id>, "
                "snapshot:<id>, source-snapshot:<source-id>, dataset:<id>."
            )
            raise ValueError(msg)
        if prefix == "artifact":
            return self._artifact(identifier, locator)
        if prefix == "observation":
            return self._observation(identifier, locator)
        if prefix == "snapshot":
            return self._snapshot(identifier, locator)
        if prefix == "source-snapshot":
            return self._source_snapshot(identifier, locator)
        if prefix == "dataset":
            return self._dataset(identifier, locator)
        msg = f"Unsupported repository query target: {raw!r}"
        raise ValueError(msg)

    def _artifact(self, artifact_key: str, locator: str | None) -> JsonObject:
        state = self.repository.latest_state(artifact_key)
        payload: JsonObject = {
            "target_kind": "artifact",
            "artifact_key": artifact_key,
            "state": state.to_dict() if state is not None else None,
            "history": [observation.to_dict() for observation in self.repository.observations_for(artifact_key)],
        }
        if locator is None:
            return payload
        if state is None:
            payload["locator"] = {
                "requested": locator,
                "resolved": None,
                "value": None,
                "error": "Artifact has never been observed.",
            }
        elif isinstance(state, ArtifactAbsence):
            payload["locator"] = {
                "requested": locator,
                "resolved": None,
                "value": None,
                "error": "Artifact is currently absent.",
            }
        else:
            payload["locator"] = _resolve_locator(self.repository, state, locator)
        return payload

    def _observation(self, observation_id: str, locator: str | None) -> JsonObject:
        observation = self.repository.observation(ObservationId(observation_id))
        if observation is None:
            msg = f"Unknown content observation: {observation_id}"
            raise KeyError(msg)
        payload: JsonObject = {
            "target_kind": "observation",
            "observation": observation.to_dict(),
        }
        if locator is not None:
            payload["locator"] = _resolve_locator(self.repository, observation, locator)
        return payload

    def _snapshot(self, snapshot_id: str, locator: str | None) -> JsonObject:
        if locator is not None:
            msg = "Locators are not supported for source snapshots."
            raise ValueError(msg)
        snapshot = self.repository.metadata.source_snapshot(SnapshotId(snapshot_id))
        if snapshot is None:
            msg = f"Unknown source snapshot: {snapshot_id}"
            raise KeyError(msg)
        return {
            "target_kind": "snapshot",
            "snapshot": _snapshot_payload(self.repository, snapshot),
        }

    def _source_snapshot(self, source_id: str, locator: str | None) -> JsonObject:
        if locator is not None:
            msg = "Locators are not supported for source snapshots."
            raise ValueError(msg)
        snapshot = self.repository.latest_source_snapshot(source_id)
        return {
            "target_kind": "source-snapshot",
            "source_id": source_id,
            "snapshot": _snapshot_payload(self.repository, snapshot) if snapshot is not None else None,
        }

    def _dataset(self, dataset_id: str, locator: str | None) -> JsonObject:
        if locator is not None:
            msg = "Locators are not supported for dataset targets."
            raise ValueError(msg)
        dataset = self.repository.dataset(dataset_id)
        return {
            "target_kind": "dataset",
            "dataset_id": str(dataset.id),
            "content_identity": dataset.content_identity,
            "created_at": dataset.manifest.created_at,
            "definition": dict(dataset.manifest.definition),
            "metadata": dict(dataset.manifest.metadata),
            "members": [_member_payload(member) for member in dataset.artifacts()],
        }


def repository_query(raw: str, *, repository: Repository) -> JsonObject:
    return RepositoryQueryService(repository).query(raw)


__all__ = ["RepositoryQueryService", "repository_query"]
