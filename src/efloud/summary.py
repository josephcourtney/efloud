from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard

from efloud.json_types import JsonMapping, JsonValue, json_mapping_or_none

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.models import NormalizedManifest


class SummaryResult(Protocol):
    @property
    def ok(self) -> bool: ...

    @property
    def root(self) -> Path: ...

    @property
    def manifest_path(self) -> Path | None: ...

    @property
    def manifest(self) -> NormalizedManifest: ...


def _normalize_transport_section(raw: JsonValue | dict[str, Any] | None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    raw_mapping = json_mapping_or_none(raw)
    if raw_mapping is not None:
        for source_id, value in sorted(raw_mapping.items(), key=operator.itemgetter(0)):
            value_mapping = json_mapping_or_none(value)
            if value_mapping is None:
                continue
            rows.append(_normalize_transport_row(str(source_id), value_mapping))

    source_count = len(rows)
    ok_count = sum(1 for row in rows if row.get("ok") is True)
    error_count = sum(1 for row in rows if row.get("ok") is False)

    return {
        "core": {
            "source_count": source_count,
            "ok_count": ok_count,
            "error_count": error_count,
        },
        "entries": rows,
        "extensions": {},
    }


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _normalize_transport_row(source_id: str, value_mapping: JsonMapping) -> dict[str, Any]:
    results_mapping = json_mapping_or_none(value_mapping.get("results"))
    normalized: dict[str, Any] = {
        "source_id": source_id,
        "status": _transport_status(value_mapping, results_mapping),
        "ok": _transport_ok(value_mapping),
        "updated_count": _transport_updated(value_mapping, results_mapping),
        "status_code": value_mapping.get("status_code"),
        "phase": _transport_phase(results_mapping),
        "retry_count": _transport_retry_count(results_mapping),
        "request_count": _transport_request_count(results_mapping),
        "max_attempts": _transport_max_attempts(results_mapping),
        "last_error": _transport_last_error(results_mapping),
        "attempt_errors": _transport_attempt_errors(results_mapping),
        "detail": _transport_detail(results_mapping),
        "exit_code": _transport_exit_code(results_mapping),
    }
    normalized["extensions"] = {
        key: val
        for key, val in value_mapping.items()
        if key
        not in {
            "status",
            "ok",
            "updated",
            "status_code",
            "phase",
            "retry_count",
            "request_count",
            "max_attempts",
            "last_error",
            "attempt_errors",
            "detail",
            "exit_code",
        }
    }
    return normalized


def _transport_result_rows(results: JsonMapping) -> list[JsonMapping]:
    rows: list[JsonMapping] = []
    for value in results.values():
        value_mapping = json_mapping_or_none(value)
        if value_mapping is not None:
            rows.append(value_mapping)
    return rows


def _transport_status(value_mapping: JsonMapping, results_mapping: JsonMapping | None) -> str | None:
    status_val = value_mapping.get("status")
    fallback = str(status_val) if isinstance(status_val, str) else None
    if results_mapping is None:
        operation = json_mapping_or_none(value_mapping.get("operation"))
        if operation is not None:
            operation_status = operation.get("status")
            if isinstance(operation_status, str):
                return operation_status
        return fallback
    return _transport_result_status(results_mapping) or fallback


def _transport_ok(value_mapping: JsonMapping) -> bool | None:
    ok_val = value_mapping.get("ok")
    return bool(ok_val) if isinstance(ok_val, int | bool) else None


def _transport_updated(value_mapping: JsonMapping, results_mapping: JsonMapping | None) -> int | None:
    if results_mapping is not None:
        return _transport_updated_count(results_mapping)
    updated = value_mapping.get("updated")
    if _is_string_list(updated):
        return len(updated)
    ingested = value_mapping.get("ingested_file_count")
    reused = value_mapping.get("reused_content_count")
    if isinstance(ingested, int) and not isinstance(ingested, bool):
        return ingested + (reused if isinstance(reused, int) and not isinstance(reused, bool) else 0)
    return None


def _transport_retry_count(results_mapping: JsonMapping | None) -> int | None:
    request_count = _transport_request_count(results_mapping)
    if request_count is None:
        return None
    return max(0, request_count - 1)


def _transport_phase(results_mapping: JsonMapping | None) -> str | None:
    if results_mapping is None:
        return None
    for row in _transport_result_rows(results_mapping):
        phase = row.get("phase")
        if isinstance(phase, str) and phase:
            return phase
    return None


def _transport_detail(results_mapping: JsonMapping | None) -> str | None:
    if results_mapping is None:
        return None
    return _transport_result_detail(results_mapping)


def _transport_exit_code(results_mapping: JsonMapping | None) -> int | None:
    if results_mapping is None:
        return None
    return _transport_result_exit_code(results_mapping)


def _transport_result_status(results: JsonMapping) -> str | None:
    rows = _transport_result_rows(results)
    statuses = [str(status) for row in rows if isinstance((status := row.get("status")), str)]
    if not statuses:
        return None
    for candidate, aliases in (
        ("failed", {"failed", "timed_out"}),
        ("skipped_rate_limited", {"skipped_rate_limited"}),
        ("skipped_fresh", {"skipped_fresh"}),
        ("dry_run", {"dry_run"}),
        ("success", {"success"}),
    ):
        if any(status in aliases for status in statuses):
            return candidate
    return statuses[0]


def _transport_updated_count(results: JsonMapping) -> int:
    total = 0
    for row in _transport_result_rows(results):
        updated = row.get("updated")
        if _is_string_list(updated):
            total += len(updated)
    return total


def _transport_result_detail(results: JsonMapping) -> str | None:
    for row in _transport_result_rows(results):
        detail = row.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    return None


def _transport_result_exit_code(results: JsonMapping) -> int | None:
    for row in _transport_result_rows(results):
        exit_code = row.get("returncode")
        if isinstance(exit_code, int):
            return exit_code
    return None


def _transport_request_count(results: JsonMapping | None) -> int | None:
    if results is None:
        return None
    counts = [
        int(attempt_count)
        for row in _transport_result_rows(results)
        for attempt_count in [row.get("attempt_count")]
        if isinstance(attempt_count, int | float)
    ]
    if not counts:
        return None
    return max(counts)


def _transport_max_attempts(results: JsonMapping | None) -> int | None:
    if results is None:
        return None
    counts = [
        int(max_attempts)
        for row in _transport_result_rows(results)
        for max_attempts in [row.get("max_attempts")]
        if isinstance(max_attempts, int | float)
    ]
    if not counts:
        return None
    return max(counts)


def _transport_last_error(results: JsonMapping | None) -> str | None:
    if results is None:
        return None
    for row in _transport_result_rows(results):
        stderr = row.get("stderr")
        if isinstance(stderr, str) and stderr.strip():
            return stderr.strip()
        detail = row.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return None


def _transport_attempt_errors(results: JsonMapping | None) -> list[str]:
    if results is None:
        return []
    errors: list[str] = []
    for row in _transport_result_rows(results):
        attempt_errors = row.get("attempt_errors")
        if _is_string_list(attempt_errors):
            errors.extend(attempt_errors)
    return errors


def build_summary(result: SummaryResult) -> dict[str, Any]:
    """Build a stable summary from either legacy or repository-backed sync results."""
    errors = result.manifest.get("errors", [])
    results = result.manifest.get("results", {})
    rsync_payload = _normalize_transport_section(results.get("rsync"))
    http_payload = _normalize_transport_section(results.get("http"))

    return {
        "ok": result.ok,
        "mirror_root": str(result.root),
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "errors": errors,
        "rsync": rsync_payload,
        "http": http_payload,
    }


__all__ = ["SummaryResult", "build_summary"]
