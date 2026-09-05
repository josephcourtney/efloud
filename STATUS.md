# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

Phases 6 through 8 of the repository-centered migration are implemented, and the
reported Phase 8 quality-gate regressions have been repaired. Phase 9 is now
implemented on `main`: generic blob/content semantics no longer require local
filesystem paths or backend storage locators. The Phase 9 repository-wide quality
gate remains to be run locally. Once clean, the active implementation frontier is
Phase 10: completing the repository-authority cutover for internal reads and
compatibility exports.

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
- compatibility manifests/state and source status serializers remain reproducible
  from canonical repository lifecycle state
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

Still transitional:

- acquisition still executes through the legacy sync/fanout machinery before
  repository recording; planner/adapter cutover remains later work
- the SQLite `content_objects.storage_key` column remains as a non-semantic legacy
  compatibility field so existing stores need no destructive schema migration
- deterministic derivation-key lookup currently uses persisted observation metadata
  rather than a dedicated relational lookup index; correctness is persistent even
  though lookup optimization can be added if measurements justify it
- the legacy TTL `IndexRegistry` remains supported for existing callers and
  source-refresh caches, but repository-backed semantic indexes are the preferred
  deterministic path
- compatibility manifests/state and some legacy resolver/control-flow mechanisms
  remain during the authority migration
- the Phase 9 changes have not yet been verified by the full local
  `just lint; just typecheck; just test` gate

## Continuity

Run the full Phase 9 quality gate and repair any reported issues. Once clean,
implement Phase 10 by moving remaining current-state/freshness/status/planning reads
off compatibility manifests, mirror-state files, and mirror rescans; those files
should become generated compatibility/export views of authoritative repository
state.
