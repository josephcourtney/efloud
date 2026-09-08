# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

Phases 6 through 11 of the repository-centered migration are implemented on `main`.
Phase 10 completed the repository-authority cutover; Phase 11 now places canonical
`Engine` orchestration behind deterministic planning, typed operations, explicit
source adapters, structured refresh policy decisions, dependency-aware bounded
execution, and repository-native result recording.

The pre-repair Phase 11 gate reported 139/139 tests passing while lint and typecheck
found contract/typing/style issues in the new orchestration code. Those reported
issues have been repaired on `main`. The immediate task is to rerun the full normal
quality gate. Do not mark Phase 11 verified until that rerun is clean.

Once the gate is clean, the active implementation frontier is Phase 12: complete
validation as immutable repository evidence.

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
  refresh decisions, scopes, dependencies, and task inputs
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
- focused Phase 11 coverage for deterministic planning, repository-state-sensitive
  plan identity, dry-run mutation boundaries, concurrency, dependencies, producer
  identity, housekeeping, and declarative source definitions

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
- Phase 11 has not yet been verified by a post-repair full local quality gate

## Continuity

Run:

```text
just syntax; just format; just lint; just typecheck; just test
```

If clean, mark Phase 11 verified and begin Phase 12 by inventorying the current
validation/integrity paths, defining validator identity/version semantics, and making
validation evidence reusable by content identity plus validator version.
