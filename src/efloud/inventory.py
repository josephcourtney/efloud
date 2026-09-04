from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from efloud.repository_models import ArtifactKey, ContentId, ContentRef, SourceId

if TYPE_CHECKING:
    from collections.abc import Iterable

    from efloud.json_types import JsonObject

ChangeTokenReliability = Literal["weak", "strong"]


@dataclass(frozen=True, slots=True)
class InventoryCoverage:
    """Describe the source scope established by one inventory operation."""

    scope: tuple[str, ...] = ()
    complete: bool = True

    def contains(self, source_path: str | None) -> bool:
        if source_path is None or not self.scope:
            return True
        normalized = source_path.strip("/")
        return any(
            normalized == item.strip("/") or normalized.startswith(item.strip("/") + "/")
            for item in self.scope
        )

    def to_dict(self) -> JsonObject:
        return {"scope": list(self.scope), "complete": self.complete}


@dataclass(frozen=True, slots=True)
class ChangeToken:
    """Source-provided evidence that two inventory observations describe the same bytes.

    A change token is never content identity. ``strong`` means the source evidence is
    trusted for change detection and may therefore justify reusing already-known
    content. It does not imply cryptographic integrity.
    """

    kind: str
    value: str
    reliability: ChangeTokenReliability = "strong"

    def equivalent_to(self, other: ChangeToken | None) -> bool:
        return (
            other is not None
            and self.reliability == "strong"
            and other.reliability == "strong"
            and self.kind == other.kind
            and self.value == other.value
        )

    def to_dict(self) -> JsonObject:
        return {
            "kind": self.kind,
            "value": self.value,
            "reliability": self.reliability,
        }


@dataclass(frozen=True, slots=True)
class IntegrityExpectation:
    """Upstream integrity assertion to compare with independently computed content."""

    algorithm: str
    digest: str
    required: bool = True
    metadata: JsonObject = field(default_factory=dict)

    @classmethod
    def sha256(
        cls,
        digest: str,
        *,
        required: bool = True,
        metadata: JsonObject | None = None,
    ) -> IntegrityExpectation:
        normalized = digest.removeprefix("sha256:").lower()
        return cls("sha256", normalized, required=required, metadata=metadata or {})

    @property
    def expected_content_id(self) -> ContentId | None:
        if self.algorithm.lower() != "sha256":
            return None
        return ContentId(f"sha256:{self.digest.lower()}")

    def matches(self, actual_content_id: ContentId | str) -> bool:
        expected = self.expected_content_id
        return expected is not None and str(expected) == str(actual_content_id).lower()

    def to_dict(self) -> JsonObject:
        return {
            "algorithm": self.algorithm,
            "digest": self.digest,
            "required": self.required,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class InventoryItem:
    item_id: str
    artifact_key: ArtifactKey
    locator: str | None = None
    source_path: str | None = None
    change_token: ChangeToken | None = None
    expected_integrity: tuple[IntegrityExpectation, ...] = ()
    metadata: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "item_id": self.item_id,
            "artifact_key": str(self.artifact_key),
            "expected_integrity": [item.to_dict() for item in self.expected_integrity],
            "metadata": dict(self.metadata),
        }
        if self.locator is not None:
            payload["locator"] = self.locator
        if self.source_path is not None:
            payload["source_path"] = self.source_path
        if self.change_token is not None:
            payload["change_token"] = self.change_token.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class SourceInventory:
    source_id: SourceId
    observed_at: float
    coverage: InventoryCoverage
    items: tuple[InventoryItem, ...]
    upstream_identity: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            msg = "Source inventory contains duplicate item identifiers."
            raise ValueError(msg)
        artifact_keys = [str(item.artifact_key) for item in self.items]
        if len(set(artifact_keys)) != len(artifact_keys):
            msg = "Source inventory contains duplicate logical artifact keys."
            raise ValueError(msg)
        outside_scope = [
            item.source_path
            for item in self.items
            if item.source_path is not None and not self.coverage.contains(item.source_path)
        ]
        if outside_scope:
            msg = f"Source inventory contains items outside declared coverage: {sorted(outside_scope)!r}"
            raise ValueError(msg)

    def item_map(self) -> dict[str, InventoryItem]:
        return {item.item_id: item for item in self.items}

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "source_id": str(self.source_id),
            "observed_at": self.observed_at,
            "coverage": self.coverage.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "metadata": dict(self.metadata),
        }
        if self.upstream_identity is not None:
            payload["upstream_identity"] = self.upstream_identity
        return payload


@dataclass(frozen=True, slots=True)
class IntegrityCheck:
    expectation: IntegrityExpectation
    actual_content_id: ContentId
    ok: bool


class IntegrityExpectationError(ValueError):
    def __init__(self, checks: tuple[IntegrityCheck, ...]) -> None:
        self.checks = checks
        failed = [check for check in checks if check.expectation.required and not check.ok]
        summary = ", ".join(
            f"{check.expectation.algorithm}:{check.expectation.digest}" for check in failed
        )
        super().__init__(f"Required integrity expectation failed: {summary}")


def check_integrity(
    content: ContentRef,
    expectations: Iterable[IntegrityExpectation],
) -> tuple[IntegrityCheck, ...]:
    """Compare upstream assertions with the independently computed content identity."""

    return tuple(
        IntegrityCheck(
            expectation=expectation,
            actual_content_id=content.content_id,
            ok=expectation.matches(content.content_id),
        )
        for expectation in expectations
    )


def require_integrity(
    content: ContentRef,
    expectations: Iterable[IntegrityExpectation],
) -> tuple[IntegrityCheck, ...]:
    checks = check_integrity(content, expectations)
    if any(check.expectation.required and not check.ok for check in checks):
        raise IntegrityExpectationError(checks)
    return checks


__all__ = [
    "ChangeToken",
    "ChangeTokenReliability",
    "IntegrityCheck",
    "IntegrityExpectation",
    "IntegrityExpectationError",
    "InventoryCoverage",
    "InventoryItem",
    "SourceInventory",
    "check_integrity",
    "require_integrity",
]
