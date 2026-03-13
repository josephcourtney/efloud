from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from efloud.models import SyncResult


def _normalize_transport_section(raw: object) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    if isinstance(raw, Mapping):
        for source_id, value in sorted(raw.items(), key=lambda item: str(item[0])):
            if not isinstance(value, Mapping):
                continue
            status_val = value.get("status")
            status = str(status_val) if isinstance(status_val, str) else None
            ok_val = value.get("ok")
            ok = bool(ok_val) if isinstance(ok_val, bool | int) else None
            row: dict[str, object] = {
                "source_id": str(source_id),
                "status": status,
                "ok": ok,
                "updated_count": len(value["updated"]) if isinstance(value.get("updated"), list) else None,
                "status_code": value.get("status_code"),
                "extensions": {
                    key: val
                    for key, val in value.items()
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


def build_summary(result: SyncResult) -> dict[str, object]:
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
