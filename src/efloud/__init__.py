from __future__ import annotations

from importlib.metadata import version

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    AdapterRegistry,
    CollectionAcquisition,
    HttpAcquisition,
    RsyncAcquisition,
    SourceAcquisition,
    SourceAdapter,
)
from efloud.blob_store import BlobStore, FilesystemBlobStore
from efloud.builtin_adapters import builtin_adapter_registry
from efloud.datasets import (
    DatasetDefinition,
    DatasetManifest,
    DatasetSelection,
    DatasetSelector,
    ExactObservation,
    ImmutableDataset,
    Latest,
    LatestAll,
    LatestBefore,
)
from efloud.derivation import DependencySemantics, DerivationKey, DerivedTaskSpec
from efloud.derived import RepositoryDerivedTask
from efloud.engine import Engine, EngineSyncResult
from efloud.executor import OperationExecutionResult, SyncExecutionResult, SyncExecutor
from efloud.fanout import RestBaseFanoutTask
from efloud.inventory import (
    AbsenceEvidence,
    AbsenceEvidenceKind,
    ChangeToken,
    ChangeTokenReliability,
    IntegrityExpectation,
    IntegrityExpectationError,
    InventoryCoverage,
    InventoryItem,
    SourceInventory,
)
from efloud.metadata_store import MetadataStore
from efloud.models import EngineConfig
from efloud.planner import SyncPlanner
from efloud.planning import PlannedOperation, PlanningDecision, SyncPlan, SyncRequest
from efloud.policy import DefaultSyncPolicy, RefreshDecision, RoleDrivenSyncPolicy
from efloud.read_only_repository import ReadOnlyRepository
from efloud.registry import MirrorMode, SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_models import (
    ArtifactAbsence,
    ArtifactKey,
    ArtifactObservation,
    ArtifactState,
    ContentId,
    ContentRef,
    DatasetId,
    DatasetSpecification,
    DatasetSpecificationId,
    ObservationId,
    OperationId,
    OperationStatus,
    ProducerRef,
    ProvenanceEdge,
    RunId,
    RunStatus,
    SnapshotId,
    SourceDefinitionRevision,
    SourceDefinitionRevisionId,
    SourceId,
    SourceSnapshot,
    TreeEntry,
    TreeId,
    ValidationResult,
    ValidationStatus,
)
from efloud.repository_query import RepositoryQueryService, repository_query
from efloud.repository_status import RepositoryStatusService
from efloud.repository_view import RepositoryView
from efloud.sqlite_metadata_v3 import SQLiteMetadataStore
from efloud.validation import (
    ContentValidator,
    ValidationRegistry,
    ValidationService,
    ValidationTarget,
    ValidatorDescriptor,
    builtin_validation_registry,
)

__version__ = version("efloud")

__all__ = [
    "AbsenceEvidence",
    "AbsenceEvidenceKind",
    "AdapterCapabilities",
    "AdapterDescriptor",
    "AdapterExecutionContext",
    "AdapterRegistry",
    "ArtifactAbsence",
    "ArtifactKey",
    "ArtifactObservation",
    "ArtifactState",
    "BlobStore",
    "ChangeToken",
    "ChangeTokenReliability",
    "CollectionAcquisition",
    "ContentId",
    "ContentRef",
    "ContentValidator",
    "DatasetDefinition",
    "DatasetId",
    "DatasetManifest",
    "DatasetSelection",
    "DatasetSelector",
    "DatasetSpecification",
    "DatasetSpecificationId",
    "DefaultSyncPolicy",
    "DependencySemantics",
    "DerivationKey",
    "DerivedTaskSpec",
    "Engine",
    "EngineConfig",
    "EngineSyncResult",
    "ExactObservation",
    "FilesystemBlobStore",
    "HttpAcquisition",
    "ImmutableDataset",
    "IntegrityExpectation",
    "IntegrityExpectationError",
    "InventoryCoverage",
    "InventoryItem",
    "Latest",
    "LatestAll",
    "LatestBefore",
    "MetadataStore",
    "MirrorMode",
    "ObservationId",
    "OperationExecutionResult",
    "OperationId",
    "OperationStatus",
    "PlannedOperation",
    "PlanningDecision",
    "ProducerRef",
    "ProvenanceEdge",
    "ReadOnlyRepository",
    "RefreshDecision",
    "Repository",
    "RepositoryDerivedTask",
    "RepositoryQueryService",
    "RepositoryStatusService",
    "RepositoryView",
    "RestBaseFanoutTask",
    "RoleDrivenSyncPolicy",
    "RsyncAcquisition",
    "RunId",
    "RunStatus",
    "SQLiteMetadataStore",
    "SnapshotId",
    "SourceAcquisition",
    "SourceAdapter",
    "SourceDefinition",
    "SourceDefinitionRevision",
    "SourceDefinitionRevisionId",
    "SourceId",
    "SourceInventory",
    "SourceKind",
    "SourceSnapshot",
    "SyncExecutionResult",
    "SyncExecutor",
    "SyncPlan",
    "SyncPlanner",
    "SyncRequest",
    "TreeEntry",
    "TreeId",
    "ValidationRegistry",
    "ValidationResult",
    "ValidationService",
    "ValidationStatus",
    "ValidationTarget",
    "ValidatorDescriptor",
    "__version__",
    "builtin_adapter_registry",
    "builtin_validation_registry",
    "repository_query",
]
