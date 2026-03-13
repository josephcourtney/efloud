from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any

from efloud.json_types import JsonObject, JsonValue, json_mapping_or_none

if TYPE_CHECKING:
    from efloud.models import SyncResult


def _normalize_transport_section(raw: JsonValue | dict[str, Any] | None) -> dict[str, Any]:
    rows: list[JsonObject] = []
    raw_mapping = json_mapping_or_none(raw)
    if raw_mapping is not None:
        for source_id, value in sorted(raw_mapping.items(), key=operator.itemgetter(0)):
            value_mapping = json_mapping_or_none(value)
            if value_mapping is None:
                continue
            status_val = value_mapping.get("status")
            status = str(status_val) if isinstance(status_val, str) else None
            ok_val = value_mapping.get("ok")
            ok = bool(ok_val) if isinstance(ok_val, int | bool) else None
            updated = value_mapping.get("updated")
            updated_count = len(updated) if isinstance(updated, list) and _is_string_list(updated) else None
            row: dict[str, Any] = {
                "source_id": str(source_id),
                "status": status,
                "ok": ok,
                "updated_count": updated_count,
                "status_code": value_mapping.get("status_code"),
                "extensions": {
                    key: val
                    for key, val in value_mapping.items()
                    if key not in {"status", "ok", "updated", "status_code"}
                },
            }
            rows.append(row)

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


def _is_string_list(value: JsonValue | None) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def build_summary(result: SyncResult) -> dict[str, Any]:
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
