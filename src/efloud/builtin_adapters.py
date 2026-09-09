from __future__ import annotations

from typing import TYPE_CHECKING

from efloud.adapters import AdapterRegistry, SourceAdapter
from efloud.collection_adapter import collection_source_adapter
from efloud.http_adapter import http_source_adapters
from efloud.rsync_adapter import rsync_source_adapter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from efloud.collections import CollectionDefinition


def builtin_adapter_registry(collections: Sequence[CollectionDefinition] = ()) -> AdapterRegistry:
    """Direct built-in registration keyed by namespaced adapter identity."""
    adapters: tuple[SourceAdapter, ...] = (
        *http_source_adapters(),
        rsync_source_adapter(),
        collection_source_adapter(collections),
    )
    return AdapterRegistry(adapters)


__all__ = ["builtin_adapter_registry"]
