# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

Phases 6 through 12 of the repository-centered migration are implemented on `main`.
Phase 11 is verified by a clean local syntax/format/lint/typecheck/test gate. Phase 12
adds validation as immutable repository evidence and keeps validation failure separate
from successful source advancement.

The immediate task is to run the full normal quality gate against the Phase 12 changes.
Do not advance implementation into Phase 13 until that gate is clean; repair any Phase
12 lint, typing, or regression failures first.

After a clean gate, the active implementation frontier is Phase 13: complete immutable
datasets and temporal policies.

## Current State

Implemented on `main`:

- typed source/artifact/content/observation/run/operation/snapshot/dataset identities
- immutable SHA-256 content storage with storage-location-independent `BlobStore`
  semantics and SQLite metadata
- normalized `SourceInventory`, change-token, integrity-expectation, coverage, and
  protocol-independent reconciliation semantics
- coverage-aware absence for rsync and collection/fanout sources
- explicit producer identity and run/operation lifecycle enforcement
- deterministic derived-task identities and persistent repository-backed semantic
  indexes
- repository-authoritative query/status/current-state behavior and compatibility
  manifest/mirror-state serialization
- conservative retained-store adoption without invented historical provenance
- deterministic `SyncRequest`, `PlanningDecision`, `PlannedOperation`, and `SyncPlan`
- plan identity derived from request, repository state, adapter capabilities,
  refresh decisions, scopes, dependencies, task inputs, and configured source
  integrity expectations
- planning that performs no acquisition or authoritative mutation
- structured `RefreshDecision` values rather than bare refresh booleans in the
  canonical planner
- `SourceAdapter`, `AdapterDescriptor`, capability declarations, and direct
  `AdapterRegistry`
- declarative `SourceDefinition` values that contain no live transport clients or
  sessions
- direct built-in registration in `builtin_adapters.py`; external entry-point
  discovery remains deliberately deferred
- separate HTTP/REST, rsync, and collection adapter runtime modules
- typed adapter acquisition results recorded into repository state without using
  `RepositorySyncRecorder` on the canonical Engine path
- rsync protocol execution isolated under `transport/rsync_runtime.py` rather than
  imported from legacy orchestration helpers
- explicit housekeeping operations in plans for cache deletion and orphan-mirror
  pruning
- explicit operation dependencies with dependency blocking and bounded concurrency
- dry-run using the same plan while creating no repository run or operations
- adapter descriptor identity/version flowing into persisted `ProducerRef`
- collection acquisition recorded directly as ordinary observations, absences,
  tree snapshots, and execution evidence
- canonical `Engine` flow of `plan -> execute -> repository-derived outputs`
- compatibility manifest and mirror-state JSON retained only as projections/exports
  on the canonical path
- Phase 11 verified locally with syntax, format, lint, typecheck, and full tests clean
- immutable `ValidationResult` evidence keyed by content identity plus validator
  identity/version
- repository lookup/reuse of prior validation evidence for unchanged content and
  validator versions
- explicit staged-content repository operations that register immutable content
  without creating a logical-artifact observation or advancing source state
- ordinary ingestion still atomically records content metadata with observations;
  failed observation metadata commits may leave only an unreferenced blob, preserving
  the Phase 9 failure invariant
- built-in storage-integrity, gzip-container, and JSON validators
- source `IntegrityExpectation` validation against independently computed content
  identity
- source-configured HTTP/REST integrity expectations enforced at the repository
  recording boundary even when a custom adapter omits them
- adapter-provided additional HTTP/REST integrity expectations merged without
  overriding duplicate configured expectations
- configured source integrity expectations persisted in repository source definitions
  and included in deterministic plan identity
- collection-item integrity expectations evaluated before content observations are
  recorded; failed validation remains unresolved evidence rather than current content
- failed required HTTP/REST validation records immutable content plus validation
  evidence but creates no successful source observation or source snapshot
- failed collection-item validation prevents a complete successful collection
  snapshot while preserving explicit unresolved evidence
- reusable generic validation through `ValidationService` and injectable
  `ValidationRegistry`
- domain-validator extension contract via `ContentValidator`, `ValidatorDescriptor`,
  and Engine validator-registry injection without domain-library dependencies
- repository/query exposure of validation evidence for `content:<content-id>` and
  observation queries
- focused Phase 12 coverage for validator-version reuse, required source-integrity
  failure, invalid JSON/gzip preservation, query exposure, source-definition
  persistence, custom-adapter omission, and collection-item integrity gating

## Still Transitional

- direct legacy `efloud.sync.sync(cfg)` remains an explicit compatibility surface
  with its historical implementation; canonical `Engine` no longer depends on it
- `RepositorySyncRecorder` and transient manifest import code remain for legacy
  compatibility paths but are no longer part of canonical Engine execution
- the SQLite `content_objects.storage_key` column remains as non-semantic schema
  compatibility for existing repositories
- the legacy TTL `IndexRegistry` remains available for existing callers and
  source-refresh cache concerns; deterministic repository-backed indexes are the
  preferred semantic path
- explicit manifest/resolve/health helpers that accept caller-supplied compatibility
  data remain available for compatibility inspection
- rsync's existing reconciliation path computes/verifies actual content identity during
  ingestion; no upstream rsync checksum expectation source is currently configured, so
  Phase 12 adds no synthetic rsync expectation mechanism
- Phase 12 has not yet been verified by a post-implementation full local quality gate

## Continuity

Run:

```text
just syntax; just format; just lint; just typecheck; just test
```

If clean, mark Phase 12 verified and begin Phase 13. Phase 13 should build on the
existing immutable dataset foundation rather than changing validation or acquisition
semantics: add source/tag/role/namespace selection where justified, explicit temporal
time basis, complete-snapshot requirements, optional skew/same-run constraints, and
deterministic dataset export metadata.
