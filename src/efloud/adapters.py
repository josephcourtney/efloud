from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from efloud.json_types import JsonObject
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository_models import ProducerRef
from efloud.transport.rsync_inventory import RsyncInventory

if TYPE_CHECKING:
    from efloud.inventory import IntegrityExpectation
    from efloud.models import EngineConfig
    from efloud.planning import PlannedOperation
    from efloud.repository import Repository


type AcquisitionStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Protocol capabilities exposed to deterministic planning."""

    inventory: bool
    fetch: bool

    def to_dict(self) -> JsonObject:
        return {"inventory": self.inventory, "fetch": self.fetch}


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    """Stable adapter identity, version, supported source kinds, and capabilities."""

    adapter_id: str
    version: str
    source_kinds: tuple[SourceKind, ...]
    capabilities: AdapterCapabilities

    def __post_init__(self) -> None:
        """Validate producer identity and reject empty source-kind declarations."""
        ProducerRef(self.adapter_id, self.version)
        if not self.source_kinds:
            msg = "AdapterDescriptor.source_kinds must not be empty."
            raise ValueError(msg)

    @property
    def producer(self) -> ProducerRef:
        """Producer identity persisted for operations executed by this adapter."""
        return ProducerRef(self.adapter_id, self.version)

    def to_dict(self) -> JsonObject:
        return {
            "adapter_id": self.adapter_id,
            "version": self.version,
            "source_kinds": [kind.value for kind in self.source_kinds],
            "capabilities": self.capabilities.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AdapterExecutionContext:
    """Read/configuration context supplied to one source-adapter operation."""

    config: EngineConfig
    repository: Repository
    source: SourceDefinition
    operation: PlannedOperation


@dataclass(frozen=True, slots=True)
class HttpAcquisition:
    source_id: str
    status: AcquisitionStatus
    destination: Path | None
    observed_at: float
    status_code: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    request_headers: JsonObject | None = None
    media_type: str | None = None
    expected_integrity: tuple[IntegrityExpectation, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RsyncAcquisition:
    source_id: str
    status: AcquisitionStatus
    local_root: Path
    scope: tuple[str, ...]
    observed_at: float
    inventory: RsyncInventory | None = None
    updated_paths: tuple[str, ...] = ()
    transport_results: JsonObject | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionAcquisition:
    source_id: str
    status: AcquisitionStatus
    task_name: str
    observed_at: float
    payload: JsonObject | None = None
    error: str | None = None


type SourceAcquisition = HttpAcquisition | RsyncAcquisition | CollectionAcquisition


class SourceAdapter(Protocol):
    @property
    def descriptor(self) -> AdapterDescriptor: ...

    async def acquire(self, context: AdapterExecutionContext) -> SourceAcquisition: ...


class AdapterRegistry:
    """Direct registry of runtime adapters keyed by declarative source kind."""

    def __init__(self, adapters: tuple[SourceAdapter, ...] = ()) -> None:
        self._adapters: dict[SourceKind, SourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: SourceAdapter) -> None:
        for source_kind in adapter.descriptor.source_kinds:
            if source_kind in self._adapters:
                existing = self._adapters[source_kind]
                msg = (
                    f"Source kind {source_kind.value!r} already has adapter "
                    f"{existing.descriptor.adapter_id!r}."
                )
                raise ValueError(msg)
            self._adapters[source_kind] = adapter

    def adapter_for(self, source: SourceDefinition) -> SourceAdapter | None:
        return self._adapters.get(source.kind)

    def descriptors(self) -> tuple[AdapterDescriptor, ...]:
        unique = {adapter.descriptor.adapter_id: adapter.descriptor for adapter in self._adapters.values()}
        return tuple(sorted(unique.values(), key=lambda descriptor: descriptor.adapter_id))


__all__ = [
    "AcquisitionStatus",
    "AdapterCapabilities",
    "AdapterDescriptor",
    "AdapterExecutionContext",
    "AdapterRegistry",
    "CollectionAcquisition",
    "HttpAcquisition",
    "RsyncAcquisition",
    "SourceAcquisition",
    "SourceAdapter",
]
