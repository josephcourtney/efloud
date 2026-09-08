from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from efloud.repository_models import ProducerRef, stable_id

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.models import EngineConfig
    from efloud.policy import RefreshDecision


type PlannedOperationKind = Literal["source", "derived", "housekeeping"]


@dataclass(frozen=True, slots=True)
class SyncRequest:
    """Caller intent consumed by deterministic planning."""

    source_ids: tuple[str, ...] | None = None
    include_derived: bool = True
    dry_run: bool = False
    max_concurrency: int = 4

    def __post_init__(self) -> None:
        """Canonicalize target order and reject invalid concurrency."""
        if self.max_concurrency < 1:
            msg = "SyncRequest.max_concurrency must be at least 1."
            raise ValueError(msg)
        if self.source_ids is not None:
            object.__setattr__(self, "source_ids", tuple(sorted(set(self.source_ids))))

    @classmethod
    def from_config(cls, cfg: EngineConfig) -> SyncRequest:
        return cls(
            source_ids=None,
            include_derived=not cfg.skip_derived,
            dry_run=cfg.dry_run,
            max_concurrency=max(1, cfg.http_concurrency),
        )

    def to_dict(self) -> JsonObject:
        return {
            "source_ids": list(self.source_ids) if self.source_ids is not None else None,
            "include_derived": self.include_derived,
            "dry_run": self.dry_run,
            "max_concurrency": self.max_concurrency,
        }


@dataclass(frozen=True, slots=True)
class PlanningDecision:
    """Serializable explanation of whether and how a source is planned."""

    source_id: str
    selected: bool
    reason: str
    adapter_id: str | None = None
    adapter_version: str | None = None
    refresh: RefreshDecision | None = None
    scope: tuple[str, ...] = ()

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "source_id": self.source_id,
            "selected": self.selected,
            "reason": self.reason,
            "scope": list(self.scope),
        }
        if self.adapter_id is not None:
            payload["adapter_id"] = self.adapter_id
        if self.adapter_version is not None:
            payload["adapter_version"] = self.adapter_version
        if self.refresh is not None:
            payload["refresh"] = self.refresh.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class PlannedOperation:
    """Typed executable unit with explicit producer identity and dependencies."""

    operation_key: str
    kind: PlannedOperationKind
    subject: str
    producer: ProducerRef
    source_id: str | None = None
    dependencies: tuple[str, ...] = ()
    refresh: RefreshDecision | None = None
    scope: tuple[str, ...] = ()
    parameters: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Canonicalize dependencies and scope for stable plan identity."""
        object.__setattr__(self, "dependencies", tuple(sorted(set(self.dependencies))))
        object.__setattr__(self, "scope", tuple(sorted(set(self.scope))))
        if self.operation_key in self.dependencies:
            msg = f"Planned operation {self.operation_key!r} cannot depend on itself."
            raise ValueError(msg)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "operation_key": self.operation_key,
            "kind": self.kind,
            "subject": self.subject,
            "producer": self.producer.to_dict(),
            "dependencies": list(self.dependencies),
            "scope": list(self.scope),
            "parameters": dict(self.parameters),
        }
        if self.source_id is not None:
            payload["source_id"] = self.source_id
        if self.refresh is not None:
            payload["refresh"] = self.refresh.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class SyncPlan:
    """Immutable deterministic plan produced without acquisition or mutation."""

    plan_id: str
    request: SyncRequest
    decisions: tuple[PlanningDecision, ...]
    operations: tuple[PlannedOperation, ...]

    def operation(self, operation_key: str) -> PlannedOperation:
        for operation in self.operations:
            if operation.operation_key == operation_key:
                return operation
        msg = f"Unknown planned operation: {operation_key}"
        raise KeyError(msg)

    def to_dict(self) -> JsonObject:
        return {
            "plan_id": self.plan_id,
            "request": self.request.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "operations": [operation.to_dict() for operation in self.operations],
        }


def make_sync_plan(
    *,
    request: SyncRequest,
    decisions: tuple[PlanningDecision, ...],
    operations: tuple[PlannedOperation, ...],
) -> SyncPlan:
    """Construct a plan whose identity is derived entirely from semantic inputs."""
    canonical_decisions = tuple(sorted(decisions, key=lambda item: item.source_id))
    canonical_operations = tuple(sorted(operations, key=lambda item: item.operation_key))
    identity_payload: JsonObject = {
        "request": request.to_dict(),
        "decisions": [decision.to_dict() for decision in canonical_decisions],
        "operations": [operation.to_dict() for operation in canonical_operations],
    }
    return SyncPlan(
        plan_id=stable_id("plan", identity_payload),
        request=request,
        decisions=canonical_decisions,
        operations=canonical_operations,
    )


__all__ = [
    "PlannedOperation",
    "PlannedOperationKind",
    "PlanningDecision",
    "SyncPlan",
    "SyncRequest",
    "make_sync_plan",
]
