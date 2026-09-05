from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from efloud.repository_models import RunId, SourceId

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.metadata_store import OperationRecord, RunRecord, SourceRecord
    from efloud.repository import Repository
    from efloud.repository_models import SourceSnapshot


def _compatibility_status(status: str) -> str:
    return "success" if status == "succeeded" else status


def _source_record_payload(record: SourceRecord) -> JsonObject:
    return {
        "source_id": str(record.source_id),
        "definition": dict(record.definition),
    }


def _run_record_payload(record: RunRecord) -> JsonObject:
    payload: JsonObject = {
        "run_id": str(record.run_id),
        "started_at": record.started_at,
        "status": _compatibility_status(record.status),
        "lifecycle_status": record.status,
        "metadata": dict(record.metadata),
    }
    if record.finished_at is not None:
        payload["finished_at"] = record.finished_at
    return payload


def _operation_record_payload(record: OperationRecord) -> JsonObject:
    payload: JsonObject = {
        "operation_id": str(record.operation_id),
        "run_id": str(record.run_id),
        "kind": record.kind,
        "subject": record.subject,
        "started_at": record.started_at,
        "status": _compatibility_status(record.status),
        "lifecycle_status": record.status,
        "producer": record.producer.to_dict(),
        "parameters": dict(record.parameters),
        "details": dict(record.details),
    }
    if record.source_id is not None:
        payload["source_id"] = str(record.source_id)
    if record.finished_at is not None:
        payload["finished_at"] = record.finished_at
    return payload


def _snapshot_payload(snapshot: SourceSnapshot | None) -> JsonObject | None:
    return None if snapshot is None else snapshot.to_dict()


@dataclass(frozen=True, slots=True)
class RepositoryStatusService:
    repository: Repository

    def root_payload(self, *, run_limit: int = 20) -> JsonObject:
        return {
            "target_kind": "repository",
            "sources": [_source_record_payload(source) for source in self.repository.metadata.sources()],
            "recent_runs": [
                _run_record_payload(run) for run in self.repository.metadata.recent_runs(limit=run_limit)
            ],
        }

    def source_payload(self, source_id: SourceId | str) -> JsonObject:
        normalized = SourceId(str(source_id))
        source = self.repository.metadata.source(normalized)
        if source is None:
            msg = f"Unknown repository source: {source_id}"
            raise KeyError(msg)
        latest_snapshot = self.repository.latest_source_snapshot(normalized)
        return {
            "target_kind": "source",
            "source": _source_record_payload(source),
            "latest_snapshot": _snapshot_payload(latest_snapshot),
            "operations": [
                _operation_record_payload(operation)
                for operation in self.repository.metadata.operations_for_source(normalized)
            ],
        }

    def run_payload(self, run_id: RunId | str) -> JsonObject:
        normalized = RunId(str(run_id))
        run = self.repository.metadata.run(normalized)
        if run is None:
            msg = f"Unknown repository run: {run_id}"
            raise KeyError(msg)
        return {
            "target_kind": "run",
            "run": _run_record_payload(run),
            "operations": [
                _operation_record_payload(operation)
                for operation in self.repository.metadata.operations_for_run(normalized)
            ],
        }


__all__ = ["RepositoryStatusService"]
