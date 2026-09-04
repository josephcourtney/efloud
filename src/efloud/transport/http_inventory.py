from __future__ import annotations

from typing import TYPE_CHECKING

from efloud.inventory import (
    ChangeToken,
    IntegrityExpectation,
    InventoryCoverage,
    InventoryItem,
    SourceInventory,
)
from efloud.repository_models import ArtifactKey, SourceId

if TYPE_CHECKING:
    from efloud.json_types import JsonObject


def _http_change_token(etag: str | None, last_modified: str | None) -> ChangeToken | None:
    if etag:
        weak = etag.lstrip().startswith("W/")
        return ChangeToken(
            kind="http-etag",
            value=etag,
            reliability="weak" if weak else "strong",
        )
    if last_modified:
        return ChangeToken(
            kind="http-last-modified",
            value=last_modified,
            reliability="weak",
        )
    return None


def http_source_inventory(
    *,
    source_id: SourceId | str,
    artifact_key: ArtifactKey | str,
    url: str,
    observed_at: float,
    etag: str | None = None,
    last_modified: str | None = None,
    expected_sha256: str | None = None,
    status_code: int | None = None,
    metadata: JsonObject | None = None,
) -> SourceInventory:
    """Represent one HTTP/REST resource using the normalized inventory model."""

    expectations = (
        (IntegrityExpectation.sha256(expected_sha256),)
        if expected_sha256 is not None
        else ()
    )
    item_metadata: JsonObject = {}
    if status_code is not None:
        item_metadata["status_code"] = status_code
    if last_modified is not None:
        item_metadata["last_modified"] = last_modified
    return SourceInventory(
        source_id=SourceId(str(source_id)),
        observed_at=observed_at,
        coverage=InventoryCoverage(complete=True),
        items=(
            InventoryItem(
                item_id=str(artifact_key),
                artifact_key=ArtifactKey(str(artifact_key)),
                locator=url,
                change_token=_http_change_token(etag, last_modified),
                expected_integrity=expectations,
                metadata=item_metadata,
            ),
        ),
        upstream_identity=etag,
        metadata=metadata or {"transport": "HTTP"},
    )


__all__ = ["http_source_inventory"]
