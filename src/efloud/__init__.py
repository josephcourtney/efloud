from __future__ import annotations

from importlib.metadata import version

from efloud.artifacts import build_path_index, canonical_path, sha256_hex, verify_gzip
from efloud.blob_store import BlobStore, FilesystemBlobStore
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
from efloud.derived import RepositoryDerivedTask
from efloud.engine import Engine, EngineSyncResult
from efloud.fanout import (
    FanoutEnumeration,
    FanoutItem,
    RestBaseFanoutTask,
    fanout_source_inventory,
    normalize_fanout_enumeration,
    two_char_bucket,
)
from efloud.health import MirrorHealthSummary, build_mirror_health_summary
from efloud.indexing import IndexDefinition, IndexRegistry, IndexStatus, JsonTtlIndex
from efloud.inventory import (
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
from efloud.policy import DefaultSyncPolicy, RoleDrivenSyncPolicy
from efloud.query import query_target, root_payload, source_payload, store_payload
from efloud.query_targets import QueryTarget, parse_query_target
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
    ObservationId,
    OperationId,
    ProvenanceEdge,
    RunId,
    SnapshotId,
    SourceId,
    SourceSnapshot,
    TreeEntry,
    TreeId,
    ValidationResult,
)
from efloud.repository_query import RepositoryQueryService, repository_query
from efloud.repository_state import repository_mirror_state, write_repository_mirror_state
from efloud.repository_status import RepositoryStatusService
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
from efloud.sqlite_metadata import SQLiteMetadataStore
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

__version__ = version("efloud")

__all__ = [
    "AliasMap",
    "ArtifactAbsence",
    "ArtifactKey",
    "ArtifactObservation",
    "ArtifactState",
    "BlobStore",
    "ChangeToken",
    "ChangeTokenReliability",
    "ContentId",
    "ContentRef",
    "DatasetDefinition",
    "DatasetId",
    "DatasetManifest",
    "DatasetMemberRecord",
    "DatasetRecord",
    "DatasetSelection",
    "DatasetSelector",
    "DefaultSyncPolicy",
    "Engine",
    "EngineConfig",
    "EngineSyncResult",
    "ExactObservation",
    "FanoutEnumeration",
    "FanoutItem",
    "FilesystemBlobStore",
    "HttpCache",
    "HttpCacheConfig",
    "HttpFetchResult",
    "ImmutableDataset",
    "IndexDefinition",
    "IndexRegistry",
    "IndexStatus",
    "IntegrityCheck",
    "IntegrityExpectation",
    "IntegrityExpectationError",
    "InventoryCoverage",
    "InventoryItem",
    "JsonTtlIndex",
    "Latest",
    "LatestAll",
    "LatestBefore",
    "MaterializationRecord",
    "MetadataStore",
    "MirrorHealthSummary",
    "MirrorMode",
    "MirrorState",
    "MirrorStateNode",
    "ObservationId",
    "OpResult",
    "OperationId",
    "OperationRecord",
    "PreviousInventoryItem",
    "ProvenanceEdge",
    "QueryTarget",
    "ReconciliationDecision",
    "ReconciliationResult",
    "ReconciliationState",
    "Repository",
    "RepositoryDerivedTask",
    "RepositoryQueryService",
    "RepositoryStatusService",
    "RestBaseFanoutTask",
    "RoleDrivenSyncPolicy",
    "RsyncCommandConfig",
    "RsyncMirror",
    "RsyncMirrorConfig",
    "RunId",
    "RunRecord",
    "SQLiteMetadataStore",
    "SnapshotId",
    "SourceAliasResolver",
    "SourceDefinition",
    "SourceId",
    "SourceInventory",
    "SourceKind",
    "SourceRecord",
    "SourceSnapshot",
    "StoreMetadataProvider",
    "StorePathKind",
    "StoreSpec",
    "SyncResult",
    "TreeEntry",
    "TreeId",
    "ValidationResult",
    "__version__",
    "build_mirror_health_summary",
    "build_path_index",
    "build_summary",
    "cache_group_name",
    "canonical_path",
    "check_integrity",
    "collect_status_payload",
    "derived_summary",
    "dest_for_http_source",
    "fanout_source_inventory",
    "generic_store_metadata",
    "http_dest_for_source_url",
    "http_dests_for_source_urls",
    "iter_manifest_entries",
    "json_shape",
    "load_latest_manifest",
    "local_materialized_path",
    "manifest_entry_for_source",
    "manifest_entry_for_source_aliasable",
    "manifest_entry_for_source_id",
    "manifest_http_dest_for_url",
    "manifest_section_for_kind",
    "materialized_path_for_source",
    "merge_manifests",
    "mirror_dir",
    "mirror_root_subdir_for_source",
    "mirror_state_metadata",
    "normalize_fanout_enumeration",
    "normalize_manifest",
    "parse_query_target",
    "query_target",
    "reconcile_inventory",
    "rel_to_root",
    "repository_manifest",
    "repository_mirror_state",
    "repository_query",
    "require_integrity",
    "root_payload",
    "sha256_hex",
    "source_by_id_or_alias",
    "source_payload",
    "source_status_hint",
    "source_status_rows",
    "sqlite_meta",
    "sqlite_store_metadata",
    "store_payload",
    "store_payload_for_specs",
    "store_summary_entries",
    "sync",
    "sync_manifest_metadata",
    "two_char_bucket",
    "verify_gzip",
    "write_repository_manifest",
    "write_repository_mirror_state",
]
