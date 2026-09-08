from __future__ import annotations

from efloud.adapters import AdapterRegistry, SourceAdapter
from efloud.collection_adapter import collection_source_adapter
from efloud.http_adapter import http_source_adapters
from efloud.rsync_adapter import rsync_source_adapter


def builtin_adapter_registry() -> AdapterRegistry:
    """Direct built-in registration without external entry-point discovery."""
    adapters: tuple[SourceAdapter, ...] = (
        *http_source_adapters(),
        rsync_source_adapter(),
        collection_source_adapter(),
    )
    return AdapterRegistry(adapters)


__all__ = ["builtin_adapter_registry"]