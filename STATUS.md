# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

Phases 6 through 10 of the repository-centered migration are implemented on
`main`. Phase 10 completes the authority cutover for the canonical `Engine` path:
repository records now determine current source state, status/query behavior, and
all published compatibility manifest/mirror-state views. Generated compatibility
files are no longer read as authoritative state by Engine, query, or status code.

The combined Phase 9/10 repository-wide quality gate still needs to be run
locally. Once clean, the active implementation frontier is Phase 11: formalizing
the planner, executor, source-adapter, and policy interfaces around the repository
and `SourceInventory` semantics that are now authoritative.

## Current State

Implemented on `main`:

- typed artifact/content/observation/run/snapshot/dataset identities, SHA-256 blob
  storage, SQLite metadata, provenance, validation, materialization, and absence
  records
- immutable datasets with exact/latest/as-of selection and separate provenance vs
  content-equivalence identities
- repository-native artifact, observation, snapshot, dataset, source, run, and
  status/query APIs, including blob-backed locator evaluation
- normalized source inventory and protocol-independent reconciliation shared by
  HTTP/REST, rsync, and collection/fanout membership evidence
- explicit `ChangeToken` evidence separated from content identity and
  `IntegrityExpectation` assertions checked against independently computed
  `ContentId` values
- coverage-aware absence semantics for rsync and collection/fanout, including
  partial-enumeration protection and complete-snapshot reconciliation baselines
- namespaced, versioned `ProducerRef` identity attached to every newly persisted
  operation; operation-kind defaults produce identities such as `efloud:http`,
  `efloud:rsync`, and `efloud:derived`
- explicit operation lifecycle `running -> succeeded|failed|cancelled` and run
  lifecycle `running -> succeeded|partial|failed|cancelled`, enforced by both the
  repository facade and SQLite metadata store
- legacy `success` spelling accepted at compatibility boundaries while canonical
  repository state stores `succeeded`; compatibility status/manifest projections
  continue to expose the legacy spelling where required
- run completion is rejected while operations remain running, second terminal
  transitions are rejected, Engine import failures close in-flight operations, and
  mixed operation outcomes produce a `partial` run
- canonical `DerivedTaskSpec` and `DerivationKey` identities covering task/version,
  normalized parameters, declared outputs, dependency semantics, and normalized
  input identities
- both content-sensitive and observation-sensitive derivation semantics
- deterministic derived-content reuse that records a new current-run observation
  and provenance edges even when the prior immutable content object is reused
- repository provenance-input inspection for verifying current derivation lineage
- repository-backed `DerivedIndexRegistry` semantic indexes represented as ordinary
  deterministic derived artifacts, with reuse governed by derivation identity rather
  than wall-clock TTL
- `index:<id>` queries prefer configured repository-backed derived indexes and report
  `validity="derivation-key"`; the older TTL index registry remains available for
  compatibility/source-refresh cache concerns
- deterministic semantic-index reuse is covered across repository close/reopen, so
  index persistence is repository history rather than process-local cache state
- a storage-location-independent `BlobStore` protocol with semantic
  `put_path`/`put_bytes`/`open`/`contains`/`verify`/`delete` operations
- `FilesystemBlobStore.path_for()` retained only as a concrete optional capability,
  not part of the generic blob-store contract
- `ContentRef` semantic equality and serialization independent of physical blob
  placement; obsolete `storage_key` constructor input is accepted only for legacy
  SQLite compatibility and is not retained
- pathless in-memory blob-store coverage proving repository ingestion, content
  opening/verification, immutable datasets, and backend replacement do not require a
  local blob path
- interrupted-ingestion coverage proving a successful blob write followed by a
  metadata failure can leave a safe unreachable orphan without committing content or
  observation metadata
- canonical Engine acquisition isolated as transient evidence: transport/fanout work
  may materialize bytes and return an in-memory compatibility-shaped result, but it
  does not publish or read canonical manifest/mirror-state files
- final canonical, timestamped, and optional requested manifests regenerated from
  repository state after the repository run is complete
- compatibility mirror-state regenerated from repository observations/snapshots
  without rescanning mirror files
- targeted sync compatibility output reconstructed from repository history, so
  untouched sources remain represented without reading or merging a prior manifest
- source query and status collection use repository state only; when repository
  metadata is absent they report an explicit uninitialized state rather than falling
  back to generated compatibility JSON
- explicit `store:sync_manifest` and `store:mirror_state` inspection remains available
  as diagnostic compatibility-file inspection, not as an authority path
- conservative retained-store adoption through `adopt_existing_store`: deterministic
  local HTTP/REST materializations and rsync files are hashed into the repository
  without moving originals or importing legacy manifest/mirror-state claims
- adopted local observations use a separate `adopted:` artifact namespace with no
  source identity, upstream locator, source snapshot, completeness, or absence; their
  metadata explicitly records that historical provenance is unknown
- repeated adoption of unchanged retained bytes is idempotent at the adopted-artifact
  observation boundary
- repository compatibility serialization no longer treats registration-without-an-
  operation as source success; unknown source state remains unknown
- Phase 10 regression coverage verifies that poisoned/deleted compatibility files do
  not affect authoritative query/status results, targeted syncs preserve untouched
  repository state, and adoption does not fabricate source history

Still transitional:

- transport and fanout acquisition still execute through legacy task functions before
  `RepositorySyncRecorder` imports their transient evidence; Phase 11 replaces this
  with explicit planner/executor/adapter interfaces
- direct legacy `efloud.sync.sync(cfg)` remains an explicit compatibility surface and
  still owns its historical manifest/mirror-state behavior; canonical `Engine` does
  not call it. Delegating/deprecating/removing that compatibility path is Phase 16
- the SQLite `content_objects.storage_key` column remains as a non-semantic legacy
  compatibility field so existing stores need no destructive schema migration
- deterministic derivation-key lookup currently uses persisted observation metadata
  rather than a dedicated relational lookup index; correctness is persistent even
  though lookup optimization can be added if measurements justify it
- the legacy TTL `IndexRegistry` remains supported for existing callers and
  source-refresh caches, but repository-backed semantic indexes are the preferred
  deterministic path
- explicit manifest/resolve/health helpers that accept caller-supplied compatibility
  data remain public for compatibility inspection; canonical internal status/query
  paths do not call them
- the combined Phase 9/10 changes have not yet been verified by the full local
  `just lint; just typecheck; just test` gate

## Continuity

Run the full Phase 9/10 quality gate and repair any reported issues. Once clean,
begin Phase 11 by defining deterministic `SyncRequest`/`SyncPlan`/planning decisions
from source definitions plus repository state, then place HTTP, REST, rsync, and
collection acquisition behind explicit `SourceAdapter` capabilities while preserving
the small `Engine` facade.
