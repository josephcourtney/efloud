from __future__ import annotations

import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path

from efloud.json_types import JsonMapping, JsonObject, json_mapping_or_none
from efloud.models import EngineConfig, SyncResult
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_models import ObservationId, OperationId, RunId, SourceId


def _source_definition_payload(source: SourceDefinition) -> JsonObject:
    payload: JsonObject = {
        "description": source.description,
        "url": source.url,
        "kind": source.kind.value,
        "tags": list(source.tags),
    }
    if source.cache_name is not None:
        payload["cache_name"] = source.cache_name
    if source.local_subpath is not None:
        payload["local_subpath"] = source.local_subpath
    if source.mirror_mode is not None:
        payload["mirror_mode"] = source.mirror_mode.value
    if source.mirror_paths is not None:
        payload["mirror_paths"] = list(source.mirror_paths)
    if source.port is not None:
        payload["port"] = source.port
    if source.include is not None:
        payload["include"] = list(source.include)
    if source.exclude is not None:
        payload["exclude"] = list(source.exclude)
    if source.role is not None:
        payload["role"] = source.role
    return payload


def _http_modified_timestamp(last_modified: object) -> float | None:
    if not isinstance(last_modified, str) or not last_modified:
        return None
    try:
        return parsedate_to_datetime(last_modified).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: object, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


@dataclass(slots=True)
class RepositorySyncRecorder:
    repository: Repository
    config: EngineConfig
    started_at: float = field(default_factory=time.time)
    run_id: RunId = field(init=False)
    observations: list[ObservationId] = field(default_factory=list, init=False)
    skipped_source_ids: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        source_ids: list[SourceId] = []
        for source in self.config.sources:
            source_id = self.repository.register_source(
                SourceId(source.id),
                _source_definition_payload(source),
            )
            source_ids.append(source_id)
        self.run_id = self.repository.start_run(
            source_ids=source_ids,
            started_at=self.started_at,
            metadata={"compatibility_sync": True},
        )

    def _start_source_operation(self, source: SourceDefinition) -> OperationId:
        return self.repository.start_operation(
            run_id=self.run_id,
            source_id=SourceId(source.id),
            kind=source.kind.value.lower(),
            subject=source.id,
            parameters={"url": source.url},
        )

    def import_result(self, result: SyncResult) -> None:
        if self.config.dry_run:
            return
        results = result.manifest.get("results", {})
        http_results = results.get("http", {}) if isinstance(results, dict) else {}
        for source in self.config.sources:
            if source.kind not in {SourceKind.HTTP, SourceKind.REST}:
                self.skipped_source_ids.append(source.id)
                continue
            entry = http_results.get(source.id) if isinstance(http_results, dict) else None
            mapping = json_mapping_or_none(entry)
            if mapping is None:
                self.skipped_source_ids.append(source.id)
                continue
            self._import_http_source(source, mapping)

    def _import_http_source(self, source: SourceDefinition, entry: JsonMapping) -> None:
        operation_id = self._start_source_operation(source)
        if entry.get("ok") is False:
            error = entry.get("error")
            details: JsonObject = {
                "error": error if isinstance(error, str) else "source acquisition failed"
            }
            self.repository.finish_operation(operation_id, status="failed", details=details)
            return

        destination = entry.get("dest")
        if not isinstance(destination, str):
            self.repository.finish_operation(
                operation_id,
                status="failed",
                details={"error": "successful source result has no materialized destination"},
            )
            return

        freshness = json_mapping_or_none(entry.get("freshness")) or {}
        observed_at = _number(freshness.get("fetched_at_unix"), self.started_at)
        etag = freshness.get("etag")
        last_modified = freshness.get("last_modified")
        status_code = freshness.get("status_code")
        metadata: JsonObject = {
            "transport": source.kind.value,
            "compatibility_import": True,
        }
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            metadata["status_code"] = status_code
        observation = self.repository.ingest_path(
            f"source:{source.id}",
            Path(destination),
            run_id=self.run_id,
            operation_id=operation_id,
            source_id=SourceId(source.id),
            observed_at=observed_at,
            upstream_locator=source.url,
            upstream_modified_at=_http_modified_timestamp(last_modified),
            upstream_version=etag if isinstance(etag, str) else None,
            media_type="application/json" if source.kind is SourceKind.REST else None,
            metadata=metadata,
            materialization_kind="compatibility-http",
        )
        self.observations.append(observation.observation_id)
        evidence: JsonObject = {}
        if isinstance(etag, str):
            evidence["etag"] = etag
        if isinstance(last_modified, str):
            evidence["last_modified"] = last_modified
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            evidence["status_code"] = status_code
        self.repository.record_source_snapshot(
            source_id=SourceId(source.id),
            run_id=self.run_id,
            complete=True,
            observed_at=observed_at,
            evidence=evidence,
        )
        self.repository.finish_operation(operation_id, status="success", details={})

    def finish(self, *, ok: bool) -> None:
        self.repository.finish_run(self.run_id, status="success" if ok else "failed")


__all__ = ["RepositorySyncRecorder"]
