from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.json_types import JsonObject, copy_json_mapping, json_mapping_or_none
from efloud.repository_models import ArtifactAbsence, ContentId, RunId, SourceId

if TYPE_CHECKING:
    from efloud.models import EngineConfig, NormalizedManifest
    from efloud.registry import SourceDefinition
    from efloud.repository import Repository


def repository_exists(cfg: EngineConfig) -> bool:
    return (Path(cfg.root) / "metadata.sqlite").is_file()


def _latest_operation_payload(repository: Repository, source_id: SourceId) -> JsonObject | None:
    operations = repository.metadata.operations_for_source(source_id, limit=1)
    if not operations:
        return None
    operation = operations[0]
    payload: JsonObject = {
        "operation_id": str(operation.operation_id),
        "run_id": str(operation.run_id),
        "kind": operation.kind,
        "status": operation.status,
        "started_at": operation.started_at,
        "parameters": dict(operation.parameters),
        "details": dict(operation.details),
    }
    if operation.finished_at is not None:
        payload["finished_at"] = operation.finished_at
    return payload


def _materialized_path(repository: Repository, content_id: ContentId) -> str | None:
    materializations = repository.metadata.materializations_for(content_id)
    if not materializations:
        return None
    preferred = sorted(
        materializations,
        key=lambda item: (item.kind.startswith("compatibility-"), item.kind, item.path),
    )
    return preferred[0].path


def _http_entry(
    repository: Repository,
    source: SourceDefinition,
    snapshot_payload: JsonObject | None,
    operation_payload: JsonObject | None,
) -> JsonObject:
    state = repository.latest_state(f"source:{source.id}")
    entry: JsonObject = {
        "source_id": source.id,
        "kind": source.kind.value,
        "url": source.url,
        "ok": operation_payload is None or operation_payload.get("status") == "success",
        "repository_backed": True,
    }
    if state is not None and not isinstance(state, ArtifactAbsence):
        entry["observation_id"] = str(state.observation_id)
        entry["content_id"] = str(state.content_id)
        destination = _materialized_path(repository, state.content_id)
        if destination is not None:
            entry["dest"] = destination
        freshness: JsonObject = {"fetched_at_unix": state.observed_at}
        if state.upstream_version is not None:
            freshness["etag"] = state.upstream_version
        if state.upstream_modified_at is not None:
            freshness["upstream_modified_at_unix"] = state.upstream_modified_at
        if snapshot_payload is not None:
            evidence = snapshot_payload.get("evidence")
            if isinstance(evidence, dict):
                for key in ("etag", "last_modified", "status_code"):
                    value = evidence.get(key)
                    if isinstance(value, bool):
                        continue
                    if isinstance(value, str | int):
                        freshness[key] = value
        entry["freshness"] = freshness
    elif isinstance(state, ArtifactAbsence):
        entry["absent"] = True
    if operation_payload is not None:
        entry["operation"] = operation_payload
        if operation_payload.get("status") == "failed":
            details = operation_payload.get("details")
            if isinstance(details, dict) and isinstance(details.get("error"), str):
                entry["error"] = details["error"]
    return entry


def _rsync_entry(
    repository: Repository,
    source: SourceDefinition,
    cfg: EngineConfig,
    snapshot_payload: JsonObject | None,
    operation_payload: JsonObject | None,
) -> JsonObject:
    entry: JsonObject = {
        "source_id": source.id,
        "kind": source.kind.value,
        "url": source.url,
        "ok": operation_payload is None or operation_payload.get("status") == "success",
        "repository_backed": True,
    }
    if source.local_subpath is not None:
        entry["local"] = str(Path(cfg.root) / cfg.mirrors_dir / source.local_subpath)
    if source.mirror_mode is not None:
        entry["mode"] = source.mirror_mode.value
    if snapshot_payload is not None:
        entry["snapshot"] = snapshot_payload
        entry["scope"] = snapshot_payload.get("scope", [])
        entry["complete"] = snapshot_payload.get("complete", False)
        evidence = snapshot_payload.get("evidence")
        if isinstance(evidence, dict):
            entry["reconciliation_complete"] = evidence.get("reconciliation_complete") is True
            for key in (
                "inventory_entry_count",
                "ingested_file_count",
                "reused_content_count",
                "absence_count",
            ):
                value = evidence.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    entry[key] = value
    if operation_payload is not None:
        entry["operation"] = operation_payload
        if operation_payload.get("status") == "failed":
            details = operation_payload.get("details")
            if isinstance(details, dict) and isinstance(details.get("error"), str):
                entry["error"] = details["error"]
    return entry


def repository_source_entry(
    repository: Repository,
    source: SourceDefinition,
    *,
    cfg: EngineConfig,
) -> JsonObject:
    source_id = SourceId(source.id)
    snapshot = repository.latest_source_snapshot(source_id)
    snapshot_payload = snapshot.to_dict() if snapshot is not None else None
    operation_payload = _latest_operation_payload(repository, source_id)
    kind = source.kind.value
    if kind in {"HTTP", "REST"}:
        return _http_entry(repository, source, snapshot_payload, operation_payload)
    if kind == "RSYNC":
        return _rsync_entry(repository, source, cfg, snapshot_payload, operation_payload)
    entry: JsonObject = {
        "source_id": source.id,
        "kind": kind,
        "url": source.url,
        "repository_backed": True,
    }
    if snapshot_payload is not None:
        entry["snapshot"] = snapshot_payload
    if operation_payload is not None:
        entry["operation"] = operation_payload
        entry["ok"] = operation_payload.get("status") == "success"
    return entry


def _derived_result_payload(repository: Repository, task_name: str) -> JsonObject | None:
    observation = repository.latest_observation(f"derived:{task_name}:result")
    if observation is None:
        return None
    try:
        with repository.open_content(observation.content_id) as stream:
            decoded = json.loads(stream.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    mapping = json_mapping_or_none(decoded)
    return copy_json_mapping(mapping) if mapping is not None else None


def _run_for_manifest(repository: Repository, run_id: RunId | str | None):
    if run_id is not None:
        return repository.metadata.run(RunId(str(run_id)))
    runs = repository.metadata.recent_runs(limit=1)
    return runs[0] if runs else None


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


def _manifest_errors(repository: Repository, run_id: RunId) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    for operation in repository.metadata.operations_for_run(run_id):
        if operation.status not in {"failed", "partial"}:
            continue
        detail = operation.details.get("error")
        error = detail if isinstance(detail, str) else operation.status
        item: dict[str, object] = {
            "phase": operation.kind,
            "name": operation.subject,
            "error": error,
        }
        if operation.source_id is not None:
            item["source_id"] = str(operation.source_id)
        errors.append(item)
    return errors


def repository_manifest(
    repository: Repository,
    *,
    cfg: EngineConfig,
    run_id: RunId | str | None = None,
) -> NormalizedManifest:
    """Serialize current repository state into the legacy normalized manifest shape."""

    http: dict[str, JsonObject] = {}
    rsync: dict[str, JsonObject] = {}
    derived: dict[str, JsonObject] = {}

    for source in cfg.sources:
        if source.kind.value in {"HTTP", "REST"}:
            http[source.id] = repository_source_entry(repository, source, cfg=cfg)
        elif source.kind.value == "RSYNC":
            rsync[source.id] = repository_source_entry(repository, source, cfg=cfg)

    for task in cfg.derived_tasks:
        payload = _derived_result_payload(repository, task.name)
        if payload is not None:
            derived[task.name] = payload

    manifest: NormalizedManifest = {
        "version": 1,
        "root": str(Path(cfg.root).resolve()),
        "results": {
            "http": http,
            "rsync": rsync,
            "derived": derived,
        },
        "errors": [],
    }
    run = _run_for_manifest(repository, run_id)
    if run is not None:
        manifest["started_at_unix"] = int(run.started_at)
        manifest["started_at_iso"] = _iso_timestamp(run.started_at)
        if run.finished_at is not None:
            manifest["finished_at_unix"] = int(run.finished_at)
            manifest["finished_at_iso"] = _iso_timestamp(run.finished_at)
            manifest["duration_seconds"] = max(0.0, run.finished_at - run.started_at)
        manifest["errors"] = _manifest_errors(repository, run.run_id)
    return manifest


__all__ = [
    "repository_exists",
    "repository_manifest",
    "repository_source_entry",
]
