from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from efloud.repository_models import ProducerRef

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.inventory import IntegrityExpectation, SourceInventory
    from efloud.json_types import JsonObject
    from efloud.planning import PlannedOperation
    from efloud.repository_capabilities import ExtensionReader
    from efloud.repository_models import ArtifactObservation, ObservationId
    from efloud.runtime import EngineRuntime
    from efloud.sources import Source
    from efloud.transport.rsync_inventory import RsyncInventory


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
    """Stable namespaced adapter identity, version, and capabilities."""

    adapter_id: str
    version: str
    capabilities: AdapterCapabilities

    def __post_init__(self) -> None:
        """Validate the persisted producer identity."""
        ProducerRef(self.adapter_id, self.version)

    @property
    def producer(self) -> ProducerRef:
        return ProducerRef(self.adapter_id, self.version)

    def to_dict(self) -> JsonObject:
        return {
            "adapter_id": self.adapter_id,
            "version": self.version,
            "capabilities": self.capabilities.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AdapterExecutionContext:
    """Narrow read/runtime context supplied to one source-adapter operation."""

    runtime: EngineRuntime
    repository: ExtensionReader
    source: Source
    operation: PlannedOperation
    inputs: tuple[ArtifactObservation, ...] = ()


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
class CollectionItemAcquisition:
    item_id: str
    status: Literal["ok", "error"]
    destination: Path | None = None
    status_code: int | None = None
    metadata: JsonObject = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionAcquisition:
    source_id: str
    status: AcquisitionStatus
    observed_at: float
    inventory: SourceInventory | None
    items: tuple[CollectionItemAcquisition, ...] = ()
    media_type: str | None = None
    input_observation_ids: tuple[ObservationId, ...] = ()
    error: str | None = None


type SourceAcquisition = HttpAcquisition | RsyncAcquisition | CollectionAcquisition


class SourceAdapter(Protocol):
    @property
    def descriptor(self) -> AdapterDescriptor: ...

    async def acquire(self, context: AdapterExecutionContext) -> SourceAcquisition: ...


class AdapterRegistry:
    """Direct registry keyed by stable namespaced adapter identity."""

    def __init__(self, adapters: tuple[SourceAdapter, ...] = ()) -> None:
        self._adapters: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: SourceAdapter) -> None:
        adapter_id = adapter.descriptor.adapter_id
        if adapter_id in self._adapters:
            existing = self._adapters[adapter_id]
            msg = f"Adapter {adapter_id!r} is already registered at version {existing.descriptor.version!r}."
            raise ValueError(msg)
        self._adapters[adapter_id] = adapter

    def adapter_for(self, source: Source) -> SourceAdapter | None:
        return self._adapters.get(source.adapter_id)

    def descriptors(self) -> tuple[AdapterDescriptor, ...]:
        return tuple(self._adapters[key].descriptor for key in sorted(self._adapters))


__all__ = [
    "AcquisitionStatus",
    "AdapterCapabilities",
    "AdapterDescriptor",
    "AdapterExecutionContext",
    "AdapterRegistry",
    "CollectionAcquisition",
    "CollectionItemAcquisition",
    "HttpAcquisition",
    "RsyncAcquisition",
    "SourceAcquisition",
    "SourceAdapter",
]
