from __future__ import annotations

from importlib.metadata import version

from efloud.api import Dataset, DatasetManifest, DatasetSpec, Engine, Repository, SyncResult
from efloud.collections import CollectionContext, CollectionDefinition, CollectionInventory, CollectionItem
from efloud.errors import DatasetError, EfloudError, ExecutionError, ExportError, RepositoryError, VerificationError
from efloud.lockfile import LockfileError, ProjectLock
from efloud.planning import SyncRequest
from efloud.project import (
    CollectionProvider,
    Project,
    ProjectError,
    ProjectSchemaError,
    ProviderResolutionError,
)
from efloud.sources import CollectionSource, HttpSource, LocalSource, RestSource, RsyncSource, Source

__version__ = version("efloud")

__all__ = [
    "CollectionContext",
    "CollectionDefinition",
    "CollectionInventory",
    "CollectionItem",
    "CollectionProvider",
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
    "LockfileError",
    "Project",
    "ProjectError",
    "ProjectLock",
    "ProjectSchemaError",
    "ProviderResolutionError",
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
