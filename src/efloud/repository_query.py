from __future__ import annotations

import gzip
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.json_types import JsonArray, JsonObject, JsonValue
from efloud.locator import apply_structured_locator, locator_candidates, split_locator
from efloud.repository_models import ArtifactAbsence, ArtifactObservation, ContentId, ObservationId, SnapshotId
from efloud.repository_status import RepositoryStatusService

if TYPE_CHECKING:
    from efloud.metadata_store import DatasetMemberRecord
    from efloud.repository_models import SourceSnapshot
    from efloud.repository_view import RepositoryView

TextLocatorHandler = Callable[[str, str, str], tuple[JsonValue | None, str | None]]
QueryHandler = Callable[[str, str | None], JsonObject]


def _member_payload(member: DatasetMemberRecord) -> JsonObject:
    payload: JsonObject = {
        "artifact_key": str(member.artifact_key),
        "observation_id": str(member.observation_id),
        "content_id": str(member.content_id),
    }
    if member.role is not None:
        payload["role"] = member.role
    return payload


def _snapshot_payload(repository: RepositoryView, snapshot: SourceSnapshot) -> JsonObject:
    payload = snapshot.to_dict()
    if snapshot.tree_id is not None:
        payload["entries"] = [entry.identity_payload() for entry in repository.tree_entries(snapshot.tree_id)]
    return payload


def _validation_payload(repository: RepositoryView, content_id: ContentId) -> JsonArray:
    payload: JsonArray = []
    payload.extend(result.to_dict() for result in repository.validations_for(content_id))
    return payload


def _payload_bytes(repository: RepositoryView, observation: ArtifactObservation) -> bytes:
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
    return name.endswith((".json", ".json.gz"))


def _resolve_line(text: str, value: str, locator: str) -> tuple[JsonValue | None, str | None]:
    if not value.isdigit() or int(value) < 1:
        return None, f"Invalid line locator: {locator!r}"
    lines = text.splitlines()
    index = int(value) - 1
    if index >= len(lines):
        return None, f"Line {index + 1} out of range (1..{len(lines)})"
    return lines[index], None


def _resolve_lines(text: str, value: str, locator: str) -> tuple[JsonValue | None, str | None]:
    match = re.fullmatch(r"(\d+)-(\d+)", value)
    if match is None:
        return None, f"Invalid lines locator: {locator!r}"
    start = int(match.group(1))
    end = int(match.group(2))
    lines = text.splitlines()
    if start < 1 or end < start or end > len(lines):
        return None, f"Line range {start}-{end} out of range (1..{len(lines)})"
    return "\n".join(lines[start - 1 : end]), None


def _resolve_regex(
    text: str,
    value: str,
    locator: str,
) -> tuple[JsonValue | None, str | None]:
    del locator
    try:
        match = re.search(value, text, re.MULTILINE)
    except re.error as exc:
        return None, f"Invalid regex locator: {exc}"
    if match is None:
        return None, f"Regex locator did not match: {value!r}"
    return match.group(1) if match.lastindex else match.group(0), None


def _resolve_text_locator(text: str, locator: str) -> tuple[JsonValue | None, str | None]:
    loc = locator.strip()
    if loc == "text":
        return text, None
    prefix, separator, value = loc.partition(":")
    handlers: dict[str, TextLocatorHandler] = {
        "line": _resolve_line,
        "lines": _resolve_lines,
        "regex": _resolve_regex,
    }
    handler = handlers.get(prefix) if separator else None
    if handler is None:
        return None, f"Unsupported text locator: {locator!r}"
    return handler(text, value.strip() if prefix != "regex" else value, locator)


def _locator_result(locator: str, resolved: str, value: JsonValue) -> JsonObject:
    return {
        "requested": locator,
        "resolved": resolved,
        "value": value,
        "error": None,
    }


def _resolve_json_locator(data: bytes, locator: str) -> JsonObject:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "requested": locator,
            "resolved": None,
            "value": None,
            "error": f"Failed to decode JSON content: {exc}",
        }
    errors: list[str] = []
    for candidate in locator_candidates(locator):
        resolved, error = apply_structured_locator(value, candidate)
        if error is None:
            return _locator_result(locator, candidate, resolved)
        errors.append(f"{candidate}: {error}")
    return _failed_locator(locator, errors)


def _resolve_plaintext_locator(data: bytes, locator: str) -> JsonObject:
    text = data.decode("utf-8", errors="replace")
    errors: list[str] = []
    for candidate in locator_candidates(locator):
        resolved, error = _resolve_text_locator(text, candidate)
        if error is None:
            return _locator_result(locator, candidate, resolved)
        errors.append(f"{candidate}: {error}")
    return _failed_locator(locator, errors)


def _failed_locator(locator: str, errors: list[str]) -> JsonObject:
    return {
        "requested": locator,
        "resolved": None,
        "value": None,
        "error": "Locator evaluation failed: " + " | ".join(errors),
    }


def _resolve_locator(
    repository: RepositoryView,
    observation: ArtifactObservation,
    locator: str,
) -> JsonObject:
    data = _payload_bytes(repository, observation)
    if _looks_json(observation):
        return _resolve_json_locator(data, locator)
    return _resolve_plaintext_locator(data, locator)


def _require_no_locator(locator: str | None, target_kind: str) -> None:
    if locator is not None:
        msg = f"Locators are not supported for repository {target_kind} targets."
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RepositoryQueryService:
    repository: RepositoryView

    def query(self, raw: str) -> JsonObject:
        target, locator = split_locator(raw.strip())
        if not target:
            msg = "Repository query target must not be empty."
            raise ValueError(msg)
        if target == "root":
            return self._root("", locator)

        prefix, separator, identifier = target.partition(":")
        if not separator or not identifier:
            msg = (
                "Repository query targets must use one of: root, source:<id>, run:<id>, "
                "artifact:<key>, observation:<id>, content:<id>, snapshot:<id>, "
                "source-snapshot:<source-id>, dataset:<id>."
            )
            raise ValueError(msg)
        handlers: dict[str, QueryHandler] = {
            "source": self._source,
            "run": self._run,
            "artifact": self._artifact,
            "observation": self._observation,
            "content": self._content,
            "snapshot": self._snapshot,
            "source-snapshot": self._source_snapshot,
            "dataset": self._dataset,
        }
        handler = handlers.get(prefix)
        if handler is None:
            msg = f"Unsupported repository query target: {raw!r}"
            raise ValueError(msg)
        return handler(identifier, locator)

    def _root(self, _identifier: str, locator: str | None) -> JsonObject:
        _require_no_locator(locator, "root")
        return RepositoryStatusService(self.repository).root_payload()

    def _source(self, source_id: str, locator: str | None) -> JsonObject:
        _require_no_locator(locator, "source")
        return RepositoryStatusService(self.repository).source_payload(source_id)

    def _run(self, run_id: str, locator: str | None) -> JsonObject:
        _require_no_locator(locator, "run")
        return RepositoryStatusService(self.repository).run_payload(run_id)

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
            "validations": _validation_payload(self.repository, observation.content_id),
        }
        if locator is not None:
            payload["locator"] = _resolve_locator(self.repository, observation, locator)
        return payload

    def _content(self, content_id: str, locator: str | None) -> JsonObject:
        _require_no_locator(locator, "content")
        normalized = ContentId(content_id)
        content = self.repository.content(normalized)
        if content is None:
            msg = f"Unknown repository content: {content_id}"
            raise KeyError(msg)
        return {
            "target_kind": "content",
            "content": content.to_dict(),
            "available": self.repository.contains_content(normalized),
            "validations": _validation_payload(self.repository, normalized),
        }

    def _snapshot(self, snapshot_id: str, locator: str | None) -> JsonObject:
        _require_no_locator(locator, "source snapshot")
        snapshot = self.repository.source_snapshot(SnapshotId(snapshot_id))
        if snapshot is None:
            msg = f"Unknown source snapshot: {snapshot_id}"
            raise KeyError(msg)
        return {
            "target_kind": "snapshot",
            "snapshot": _snapshot_payload(self.repository, snapshot),
        }

    def _source_snapshot(self, source_id: str, locator: str | None) -> JsonObject:
        _require_no_locator(locator, "source snapshot")
        snapshot = self.repository.latest_source_snapshot(source_id)
        return {
            "target_kind": "source-snapshot",
            "source_id": source_id,
            "snapshot": _snapshot_payload(self.repository, snapshot) if snapshot is not None else None,
        }

    def _dataset(self, dataset_id: str, locator: str | None) -> JsonObject:
        _require_no_locator(locator, "dataset")
        dataset = self.repository.dataset(dataset_id)
        specifications: JsonArray = []
        specifications.extend(
            specification.to_dict() for specification in self.repository.dataset_specifications(dataset.id)
        )
        return {
            "target_kind": "dataset",
            "dataset_id": str(dataset.id),
            "specification_id": str(dataset.specification_id),
            "content_identity": dataset.content_identity,
            "created_at": dataset.manifest.created_at,
            "definition": dict(dataset.manifest.definition),
            "specifications": specifications,
            "metadata": dict(dataset.manifest.metadata),
            "members": [_member_payload(member) for member in dataset.artifacts()],
        }


def repository_query(raw: str, *, repository: RepositoryView) -> JsonObject:
    return RepositoryQueryService(repository).query(raw)


__all__ = ["RepositoryQueryService", "repository_query"]
