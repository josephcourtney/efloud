from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from efloud.inventory import ChangeToken, IntegrityExpectation, InventoryCoverage, InventoryItem, SourceInventory
from efloud.repository_models import ArtifactKey, ArtifactObservation, SourceId

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from efloud.json_types import JsonObject
    from efloud.repository_capabilities import ExtensionReader
    from efloud.sources import CollectionSource

ResponseMode = Literal["json", "bytes"]
MIN_BUCKET_SOURCE_LENGTH = 3


@dataclass(frozen=True, slots=True)
class CollectionItem:
    item_id: str
    request_path: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    change_token: ChangeToken | None = None
    expected_integrity: tuple[IntegrityExpectation, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectionInventory:
    """Authoritative-or-partial membership evidence from a collection enumerator."""

    items: tuple[CollectionItem, ...]
    complete: bool = True
    upstream_identity: str | None = None

    def __post_init__(self) -> None:
        """Reject duplicate logical members before item acquisition."""
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            msg = "Collection inventory contains duplicate item identifiers."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CollectionContext:
    repository: ExtensionReader
    workspace: Path
    source: CollectionSource
    inputs: tuple[ArtifactObservation, ...]


class CollectionEnumerator(Protocol):
    async def __call__(
        self, *, context: CollectionContext
    ) -> Sequence[CollectionItem] | CollectionInventory: ...


class BucketStrategy(Protocol):
    def __call__(self, item_id: str) -> Path: ...


def two_char_bucket(item_id: str, *, suffix: str = ".json") -> Path:
    text = item_id.lower()
    bucket = text[1:3] if len(text) >= MIN_BUCKET_SOURCE_LENGTH else "xx"
    return Path(bucket) / f"{text}{suffix}"


@dataclass(frozen=True, slots=True)
class CollectionDefinition:
    """Collection membership and generic HTTP item-fetch configuration."""

    source_id: str
    enumerator: CollectionEnumerator
    input_source_ids: tuple[str, ...] = ()
    dest_subdir: str | None = None
    response_mode: ResponseMode = "json"
    bucket: BucketStrategy = two_char_bucket
    concurrency: int = 8
    cache_db_filename: str = "collection_http_cache.sqlite"
    rate_limit_db_filename: str = "collection_rate_limits.sqlite"
    timeout_seconds: float = 60.0
    retries: int = 5
    request_headers: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            msg = "CollectionDefinition.concurrency must be at least 1."
            raise ValueError(msg)
        object.__setattr__(self, "input_source_ids", tuple(sorted(set(self.input_source_ids))))


def normalize_collection_inventory(
    value: Sequence[CollectionItem] | CollectionInventory,
) -> CollectionInventory:
    if isinstance(value, CollectionInventory):
        return value
    return CollectionInventory(tuple(value))


def collection_source_inventory(
    *,
    source: CollectionSource,
    definition: CollectionDefinition,
    inventory: CollectionInventory,
    observed_at: float,
) -> SourceInventory:
    """Convert collection membership into generic reconciliation evidence."""
    source_id = SourceId(source.id)
    items = tuple(
        InventoryItem(
            item_id=item.item_id,
            artifact_key=ArtifactKey(f"source:{source_id}:item:{item.item_id}"),
            locator=f"{source.url.rstrip('/')}/{(item.request_path or item.item_id).lstrip('/')}",
            source_path=definition.bucket(item.item_id).as_posix(),
            change_token=item.change_token,
            expected_integrity=item.expected_integrity,
            metadata=dict(item.metadata),
        )
        for item in sorted(inventory.items, key=lambda candidate: candidate.item_id)
    )
    return SourceInventory(
        source_id=source_id,
        observed_at=observed_at,
        coverage=InventoryCoverage(complete=inventory.complete),
        items=items,
        upstream_identity=inventory.upstream_identity,
        metadata={"adapter_id": source.adapter_id, "collection": True},
    )


__all__ = [
    "BucketStrategy",
    "CollectionContext",
    "CollectionDefinition",
    "CollectionEnumerator",
    "CollectionInventory",
    "CollectionItem",
    "ResponseMode",
    "collection_source_inventory",
    "normalize_collection_inventory",
    "two_char_bucket",
]
