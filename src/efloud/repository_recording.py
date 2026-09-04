from __future__ import annotations

import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath

import anyio

from efloud.json_types import JsonMapping, JsonObject, json_mapping_or_none
from efloud.models import EngineConfig, SyncResult
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_derived import import_derived_results
from efloud.repository_models import ObservationId, OperationId, RunId, SourceId, TreeEntry
from efloud.rsync_reconciliation import reconcile_rsync_inventory
from efloud.transport.rsync import RsyncMirrorConfig
from efloud.transport.rsync_inventory import enumerate_rsync


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

    async def import_result(self, result: SyncResult) -> None:
        if self.config.dry_run:
            return
        results = result.manifest.get("results", {})
        http_results = results.get("http", {}) if isinstance(results, dict) else {}
        rsync_results = results.get("rsync", {}) if isinstance(results, dict) else {}
        derived_results = results.get("derived", {}) if isinstance(results, dict) else {}

        for source in self.config.sources:
            if source.kind in {SourceKind.HTTP, SourceKind.REST}:
                entry = http_results.get(source.id) if isinstance(http_results, dict) else None
                mapping = json_mapping_or_none(entry)
                if mapping is None:
                    self.skipped_source_ids.append(source.id)
                    continue
                self._import_http_source(source, mapping)
                continue
            if source.kind is SourceKind.RSYNC:
                entry = rsync_results.get(source.id) if isinstance(rsync_results, dict) else None
                mapping = json_mapping_or_none(entry)
                if mapping is None:
                    self.skipped_source_ids.append(source.id)
                    continue
                await self._import_rsync_source(source, mapping)
                continue
            if source.kind is SourceKind.REST_BASE:
                continue
            self.skipped_source_ids.append(source.id)

        derived_mapping = json_mapping_or_none(derived_results)
        handled_collection_sources: set[str] = set()
        if derived_mapping is not None:
            imported = import_derived_results(
                self.repository,
                config=self.config,
                run_id=self.run_id,
                started_at=self.started_at,
                derived_results=derived_mapping,
            )
            self.observations.extend(imported.observations)
            handled_collection_sources.update(imported.handled_source_ids)

        for source in self.config.sources:
            if source.kind is SourceKind.REST_BASE and source.id not in handled_collection_sources:
                self.skipped_source_ids.append(source.id)

        self._import_manifest_errors(result)

    def _import_manifest_errors(self, result: SyncResult) -> None:
        raw_errors = result.manifest.get("errors", [])
        if not isinstance(raw_errors, list):
            return

        operations = self.repository.metadata.operations_for_run(self.run_id)
        existing_keys = {
            (
                operation.kind,
                operation.subject,
                str(operation.source_id) if operation.source_id is not None else None,
            )
            for operation in operations
        }
        existing_source_failures = {
            (operation.kind, str(operation.source_id))
            for operation in operations
            if operation.source_id is not None and operation.status in {"failed", "partial"}
        }
        known_source_ids = {source.id for source in self.config.sources}

        for raw_error in raw_errors:
            error_mapping = json_mapping_or_none(raw_error)
            if error_mapping is None:
                continue
            phase_value = error_mapping.get("phase")
            phase = phase_value.strip().lower() if isinstance(phase_value, str) else "sync"
            source_value = error_mapping.get("source_id")
            source_text = source_value if isinstance(source_value, str) else None
            source_id = SourceId(source_text) if source_text in known_source_ids else None
            name_value = error_mapping.get("name")
            subject = (
                name_value
                if isinstance(name_value, str) and name_value
                else source_text or phase
            )
            key = (phase, subject, source_text if source_id is not None else None)
            if key in existing_keys:
                continue
            if source_text is not None and (phase, source_text) in existing_source_failures:
                continue

            operation_id = self.repository.start_operation(
                run_id=self.run_id,
                source_id=source_id,
                kind=phase,
                subject=subject,
                parameters={"compatibility_manifest_error": True},
            )
            error_value = error_mapping.get("error")
            error_text = error_value if isinstance(error_value, str) else "sync operation failed"
            self.repository.finish_operation(
                operation_id,
                status="failed",
                details={
                    "error": error_text,
                    "compatibility_manifest_error": True,
                },
            )
            existing_keys.add(key)
            if source_text is not None:
                existing_source_failures.add((phase, source_text))

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

    @staticmethod
    def _rsync_scope(entry: JsonMapping) -> tuple[str, ...]:
        request = json_mapping_or_none(entry.get("request")) or {}
        raw_paths = request.get("paths")
        if not isinstance(raw_paths, list):
            return ()
        normalized = {
            path.strip().strip("/") + "/"
            for path in raw_paths
            if isinstance(path, str) and path.strip().strip("/")
        }
        return tuple(sorted(normalized))

    @staticmethod
    def _rsync_updated_paths(entry: JsonMapping) -> tuple[str, ...]:
        results = json_mapping_or_none(entry.get("results")) or {}
        paths: set[str] = set()
        for result in results.values():
            mapping = json_mapping_or_none(result)
            if mapping is None or mapping.get("status") in {"failed", "timed_out"}:
                continue
            updated = mapping.get("updated")
            if not isinstance(updated, list):
                continue
            for raw in updated:
                if not isinstance(raw, str):
                    continue
                normalized = raw.strip().replace("\\", "/")
                if normalized.startswith("deleting "):
                    continue
                normalized = normalized.strip("/")
                if normalized and normalized != ".mirror_meta.json":
                    paths.add(normalized)
        return tuple(sorted(paths))

    @staticmethod
    def _safe_local_path(root: Path, relative_path: str) -> Path | None:
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        root_resolved = root.resolve()
        candidate = root_resolved.joinpath(*relative.parts).resolve(strict=False)
        return candidate if candidate.is_relative_to(root_resolved) else None

    def _legacy_rsync_delta(
        self,
        *,
        source: SourceDefinition,
        entry: JsonMapping,
        operation_id: OperationId,
        local_root: Path,
        scope: tuple[str, ...],
        observed_at: float,
        inventory_error: str,
    ) -> None:
        updated_paths = self._rsync_updated_paths(entry)
        tree_entries: list[TreeEntry] = []
        ingested = 0
        for relative_path in updated_paths:
            path = self._safe_local_path(local_root, relative_path)
            if path is None or not path.exists():
                continue
            if path.is_symlink():
                tree_entries.append(
                    TreeEntry(
                        relative_path=relative_path,
                        kind="symlink",
                        target=path.readlink().as_posix(),
                    )
                )
                continue
            if path.is_dir():
                tree_entries.append(TreeEntry(relative_path=relative_path, kind="directory"))
                continue
            if not path.is_file():
                continue
            observation = self.repository.ingest_path(
                f"source:{source.id}:path:{relative_path}",
                path,
                run_id=self.run_id,
                operation_id=operation_id,
                source_id=SourceId(source.id),
                observed_at=observed_at,
                source_path=relative_path,
                upstream_locator=f"{source.url.rstrip('/')}/{relative_path}",
                metadata={"transport": "RSYNC", "compatibility_import": True},
                materialization_kind="compatibility-rsync",
            )
            self.observations.append(observation.observation_id)
            tree_entries.append(
                TreeEntry(
                    relative_path=relative_path,
                    kind="file",
                    content_id=observation.content_id,
                    byte_size=path.stat().st_size,
                )
            )
            ingested += 1

        self.repository.record_tree_snapshot(
            source_id=SourceId(source.id),
            run_id=self.run_id,
            entries=tree_entries,
            complete=False,
            scope=scope,
            observed_at=observed_at,
            evidence={
                "transport": "RSYNC",
                "compatibility_import": True,
                "reconciliation_complete": False,
                "enumeration_complete": False,
                "inventory_error": inventory_error,
                "changed_entry_count": len(updated_paths),
                "ingested_file_count": ingested,
            },
        )
        self.repository.finish_operation(
            operation_id,
            status="success",
            details={
                "ingested_file_count": ingested,
                "reconciliation_complete": False,
                "inventory_error": inventory_error,
            },
        )

    async def _import_rsync_source(self, source: SourceDefinition, entry: JsonMapping) -> None:
        operation_id = self._start_source_operation(source)
        if entry.get("ok") is False:
            error = entry.get("error")
            details: JsonObject = {
                "error": error if isinstance(error, str) else "rsync acquisition failed"
            }
            self.repository.finish_operation(operation_id, status="failed", details=details)
            return

        local_value = entry.get("local")
        if not isinstance(local_value, str):
            self.repository.finish_operation(
                operation_id,
                status="failed",
                details={"error": "successful rsync result has no local mirror root"},
            )
            return
        local_root = Path(local_value)
        if not local_root.is_absolute():
            local_root = Path(self.config.root) / local_root
        scope = self._rsync_scope(entry)
        observed_at = time.time()
        inventory_cfg = RsyncMirrorConfig(
            name=source.id,
            remote=source.url,
            local=local_root,
            port=source.port,
            include=source.include or (),
            exclude=source.exclude or (),
        )
        inventory = await anyio.to_thread.run_sync(
            lambda: enumerate_rsync(inventory_cfg, scope=scope)
        )
        if not inventory.complete:
            self._legacy_rsync_delta(
                source=source,
                entry=entry,
                operation_id=operation_id,
                local_root=local_root,
                scope=scope,
                observed_at=observed_at,
                inventory_error=inventory.error or "rsync inventory unavailable",
            )
            return

        reconciled = reconcile_rsync_inventory(
            self.repository,
            source_id=SourceId(source.id),
            run_id=self.run_id,
            operation_id=operation_id,
            local_root=local_root,
            inventory=inventory,
            observed_at=observed_at,
            upstream_root=source.url,
        )
        self.observations.extend(reconciled.observations)
        self.repository.finish_operation(
            operation_id,
            status="success" if reconciled.complete else "failed",
            details={
                "reconciliation_complete": reconciled.complete,
                "ingested_file_count": reconciled.ingested_file_count,
                "reused_content_count": reconciled.reused_content_count,
                "absence_count": reconciled.absence_count,
                **({"error": reconciled.error} if reconciled.error is not None else {}),
            },
        )

    def finish(self, *, ok: bool) -> None:
        self.repository.finish_run(self.run_id, status="success" if ok else "failed")


__all__ = ["RepositorySyncRecorder"]
