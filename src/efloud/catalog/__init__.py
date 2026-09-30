"""Internal semantic catalog contracts and test implementations."""

from efloud.catalog.memory import MemoryCatalog
from efloud.catalog.protocol import Catalog

__all__ = ["Catalog", "MemoryCatalog"]
