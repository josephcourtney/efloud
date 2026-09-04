from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from efloud.json_types import JsonObject
from efloud.repository_models import ArtifactAbsence, SourceId

if TYPE_CHECKING:
    from efloud.models import EngineConfig
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


def _materialized_path(repository: Repository, content_id: str) -> str | None:
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
        destination = _materialized_path(repository, str(state.content_id))
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
                if isinstance(value, int):
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


__all__ = ["repository_exists", "repository_source_entry"]
