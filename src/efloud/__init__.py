from __future__ import annotations

from importlib.metadata import version

from efloud.api import Dataset, DatasetManifest, DatasetSpec, Engine, Repository, SyncResult
from efloud.errors import DatasetError, EfloudError, ExecutionError, ExportError, RepositoryError, VerificationError
from efloud.planning import SyncRequest
from efloud.sources import CollectionSource, HttpSource, LocalSource, RestSource, RsyncSource, Source

__version__ = version("efloud")

__all__ = [
    "CollectionSource",
    "Dataset",
    "DatasetError",
    "DatasetManifest",
    "DatasetSpec",
    "EfloudError",
    "Engine",
    "ExecutionError",
    "ExportError",
    "HttpSource",
    "LocalSource",
    "Repository",
    "RepositoryError",
    "RestSource",
    "RsyncSource",
    "Source",
    "SyncRequest",
    "SyncResult",
    "VerificationError",
    "__version__",
]
