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
from efloud.adoption import AdoptionResult, adopt_existing_store
from efloud.artifacts import build_path_index, canonical_path, sha256_hex, verify_gzip
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
from efloud.derivation import (
    DependencySemantics,
    DerivationKey,
    DerivedTaskSpec,
    derivation_key_for,
)
from efloud.derived import RepositoryDerivedTask
from efloud.engine import Engine, EngineSyncResult
from efloud.executor import OperationExecutionResult, SyncExecutionResult, SyncExecutor
from efloud.fanout import (
    FanoutEnumeration,
    FanoutItem,
    RestBaseFanoutTask,
    fanout_source_inventory,
    normalize_fanout_enumeration,
    two_char_bucket,
)
from efloud.health import MirrorHealthSummary, build_mirror_health_summary
from efloud.indexing import (
    DerivedIndexDefinition,
    DerivedIndexRegistry,
    DerivedIndexResult,
    IndexDefinition,
    IndexRegistry,
    IndexStatus,
    JsonTtlIndex,
)
from efloud.inventory import (
    AbsenceEvidence,
    AbsenceEvidenceKind,
    ChangeToken,
    ChangeTokenReliability,
    IntegrityCheck,
    IntegrityExpectation,
    IntegrityExpectationError,
    InventoryCoverage,
    InventoryItem,
    SourceInventory,
    check_integrity,
    require_integrity,
)
from efloud.manifest import load_latest_manifest, merge_manifests, normalize_manifest
from efloud.materialization import http_dest_for_source_url, http_dests_for_source_urls
from efloud.metadata_store import (
    DatasetMemberRecord,
    DatasetRecord,
    MaterializationRecord,
    MetadataStore,
    OperationRecord,
    RunRecord,
    SourceRecord,
)
from efloud.models import EngineConfig
from efloud.planner import SyncPlanner
from efloud.planning import PlannedOperation, PlanningDecision, SyncPlan, SyncRequest
from efloud.policy import DefaultSyncPolicy, RefreshDecision, RoleDrivenSyncPolicy
from efloud.query import query_target, root_payload, source_payload, store_payload
from efloud.query_targets import QueryTarget, parse_query_target
from efloud.read_only_repository import ReadOnlyRepository
from efloud.reconciliation import (
    PreviousInventoryItem,
    ReconciliationDecision,
    ReconciliationResult,
    ReconciliationState,
    reconcile_inventory,
)
from efloud.registry import MirrorMode, SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_compat import repository_manifest, write_repository_manifest
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
from efloud.repository_state import repository_mirror_state, write_repository_mirror_state
from efloud.repository_status import RepositoryStatusService
from efloud.repository_view import RepositoryView
from efloud.resolve import (
    manifest_entry_for_source_aliasable,
    manifest_http_dest_for_url,
    materialized_path_for_source,
    mirror_dir,
    mirror_root_subdir_for_source,
)
from efloud.source_aliases import AliasMap, SourceAliasResolver, source_by_id_or_alias
from efloud.source_results import (
    iter_manifest_entries,
    local_materialized_path,
    manifest_entry_for_source,
    manifest_entry_for_source_id,
    manifest_section_for_kind,
    source_status_hint,
)
from efloud.sqlite_metadata_v3 import SQLiteMetadataStore
from efloud.state import MirrorState, MirrorStateNode
from efloud.status import collect_status_payload, derived_summary, source_status_rows
from efloud.store_inspection import (
    StoreMetadataProvider,
    StorePathKind,
    StoreSpec,
    generic_store_metadata,
    json_shape,
    mirror_state_metadata,
    rel_to_root,
    sqlite_meta,
    sqlite_store_metadata,
    store_payload_for_specs,
    store_summary_entries,
    sync_manifest_metadata,
)
from efloud.summary import build_summary
from efloud.sync import SyncResult, sync
from efloud.transport.http import HttpCache, HttpCacheConfig
from efloud.transport.http_utils import HttpFetchResult, cache_group_name, dest_for_http_source
from efloud.transport.rsync import OpResult, RsyncCommandConfig, RsyncMirror, RsyncMirrorConfig
from efloud.validation import (
    ContentValidator,
    GzipValidator,
    IntegrityExpectationValidator,
    JsonValidator,
    StorageIntegrityValidator,
    ValidationBatch,
    ValidationCheck,
    ValidationOutcome,
    ValidationRegistry,
    ValidationService,
    ValidationTarget,
    ValidatorDescriptor,
    builtin_validation_registry,
)

__version__ = version("efloud")

# Compatibility imports above remain directly accessible during the pre-1.0
# migration. ``__all__`` deliberately advertises the smaller semantic surface
# new consumers should build against.
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
