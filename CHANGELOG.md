# CHANGELOG.md

All notable changes to Efloud are documented here following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Add `LocalSource` as a built-in single-file acquisition source that validates and records a stable git-annex snapshot directly from the declared local file, pinning immutable bytes independently of later mutation or deletion without retaining a runtime staging copy.
- Make the existing `efloud.collections` contract a supported advanced extension surface and pass `CollectionDefinition` values through the public `Engine(..., collections=...)` facade.
- Add a post-compatibility durability audit enumerating the remaining authoritative mutation paths, crash boundaries, coordination requirements, and acceptance evidence.

### Changed

- Make git-annex path ingestion derive its custody key from an Efloud-owned temporary snapshot of the caller bytes, so caller-file mutation cannot make the recorded key disagree with the bytes transferred into custody.
- Route byte-preserving built-in `HttpSource` acquisition directly into git-annex URL custody rather than materializing a persistent HTTP staging copy; retain adapter-side canonicalization for `RestSource`.
- Replace custom SQLite tree identity/storage with canonical semantic tree manifests retained in Git object history; source snapshots now persist the Git tree object ID directly, and schema 4 removes the `tree_snapshots` and `tree_entries` tables.
- Replaced filesystem-CAS maintenance with git-annex custody enumeration and key-level cleanup; deleted the superseded filesystem blob store.
- Cut Repository content custody over to the internal git-annex ContentStore on the experimental redesign branch; semantic ContentRef identity remains path-independent while opaque annex custody keys are retained as infrastructure evidence.
- Close dataset/export acceptance through the clean public API: verify resolve-versus-freeze semantics, frozen historical evidence, incomplete-snapshot behavior, detached handoff, missing/corrupt content, safe exclusive publication, and a standard-library-only manifest consumer.
- Exercise explicit Linux reflink export on a reflink-enabled XFS CI filesystem and atomic `renameat2(RENAME_NOREPLACE)` publication; document detached dataset manifest v1 as a repository-independent contract.
- Reject `.` as an export member path, return `False` when detached verification has no usable root, and report public manifest-layout export failures consistently as `ExportError`.
- Reject historical and non-empty unversioned repository schemas instead of migrating or partially interpreting them; require canonical terminal statuses and producer metadata.
- Keep transport staging, HTTP cache, and rate-limit state under the explicitly non-authoritative `.efloud-runtime` operational root.
- Use `limit=None` for unbounded source-snapshot history throughout repository, storage, dataset-selection, constraint, and maintenance internals rather than retaining a negative sentinel below the public facade.
- Make explicit `reflink` export remain strict when native CoW is unsupported; capability-dependent integration tests skip that strategy instead of silently substituting copy semantics.

### Removed

- Remove all maintained alpha backwards-compatibility implementation, including `efloud.compat`, deprecated `sync(cfg)`, `EngineConfig`, merged manifests and mirror-state projections, old source/fanout/derived contracts, query/status/health/summary facades, aliases/adoption, path materialization helpers, TTL cache/index compatibility, and historical schema migrations.
- Remove compatibility-only tests and architecture exceptions; installed-wheel contracts now require the deleted modules to be absent and unimportable.

### Fixed

- Retain Git-backed source-tree snapshots through a dedicated Efloud Git ref so ordinary Git garbage collection cannot prune tree objects referenced by repository metadata.
- Ignore declared adapter-version constraints for sources explicitly unselected by a selective project plan while continuing to fail closed for selected version mismatches.
- Require an active repository writer lease before standalone byte content staging can mutate the content-addressed store.
- Make destructive cleanup fail closed on SQLite/foreign-key failures, semantic tree/dataset/source/snapshot corruption, and missing or corrupt reachable content while preserving validation-only and provenance history.
- Reject operation records with missing producer metadata instead of manufacturing a synthetic legacy producer identity.

## [0.3.0] - 2026-09-09

### Added

- Add the clean pre-1.0 public facade with explicit `Repository.create`/`Repository.open` modes, `Engine`, typed HTTP/REST/rsync/collection sources, one ordinary `SyncResult`, compositional `DatasetSpec`, `Dataset`, detached `DatasetManifest`, and public error categories.
- Add timezone-aware public temporal dataset selection, `limit=None` for unbounded snapshot history, and dataset-level export/verification convenience.
- Add stable namespaced adapter registration/dispatch and separate `EngineRuntime` runtime/storage configuration.
- Add narrow repository capability contracts for adapters, execution, validation, datasets, queries, maintenance, and extension contexts.
- Add canonical exact-input/declared-output derived-task contracts and typed collection inventory/acquisition contracts.
- Add architecture contracts preventing canonical execution modules from depending on alpha config, manifest, registry, and extension contracts.

### Changed

- Reduce the package-root API from the transitional implementation surface to ordinary repository, acquisition, source, dataset, request/result, version, and error concepts.
- Make README and installed-wheel examples use the clean public API exclusively.
- Migrate canonical planner, executor, adapters, policy, validation, queries, datasets, and maintenance from `EngineConfig`, `SourceDefinition`/`SourceKind`, merged manifests, and broad `RepositoryView` contexts to typed sources, `SyncRequest`, `EngineRuntime`, and narrow repository capabilities.
- Dispatch source acquisition by stable namespaced adapter identity and capability metadata instead of the closed `SourceKind` enum.
- Make canonical derived work record exact inputs, declared outputs, namespaced producer identity/version, and deterministic derivation evidence.
- Separate collection enumeration/inventory from typed item acquisition and reconcile collection state through generic inventory and absence semantics.
- Make canonical derived-index validity derivation-key based; retain TTL-backed index behavior only in compatibility code.
- Route deprecated `sync(EngineConfig)` through an explicit compatibility converter that constructs typed sources, `EngineRuntime`, and `SyncRequest` before delegating to the canonical engine.
- Keep legacy alpha configuration, manifest/state projection, derived/fanout, registry, and TTL-index types only in compatibility or transitional modules pending deletion.

### Removed

- Remove package-root exposure of `EngineConfig`, `SourceDefinition`, `SourceKind`, `ReadOnlyRepository`, `RepositoryView`, low-level storage/registry/validator/planner/executor records, and selector/materializer implementation classes. Their implementation modules are not yet deleted.
- Remove canonical execution dependencies on `SourceKind` dispatch, manifest-shaped policy inputs, broad extension `RepositoryView` contexts, and the alpha fanout execution contract.

## [0.2.0] - 2026-09-09

### Added

- Add repository-native extension contexts, exact input observations, typed derived outputs, and explicit legacy extension adapters.

### Changed

- Make compatibility output publication an explicit post-execution operation through `compat.outputs.project_execution`.
- Require Hishel's HTTPX extra and compatible AnyIO so fresh installations support async SQLite acquisition caches.

### Removed

- Remove the unused duplicate sync runtime while retaining the canonical transport behavior.

## [0.1.0] - 2026-09-09

### Added

- Add repository-centered immutable storage with stable source, artifact, content, observation, run, operation, snapshot, and dataset identities; SHA-256 content-addressed blobs; and SQLite metadata.
- Add provenance, validation evidence, source/tree snapshots, source-definition revisions, and explicit artifact-absence states so repository history distinguishes unchanged, changed, and proven-absent content.
- Add normalized source inventory and coverage-aware reconciliation for protocol-independent new/changed/unchanged/absent classification, including authoritative rsync and collection membership evidence.
- Add immutable datasets with exact/latest temporal selection, snapshot-backed and historical source metadata selection, coherence constraints, and distinct specification, membership, and content-equivalence identities.
- Add deterministic derived-task identities, provenance-aware reuse, and repository-backed semantic indexes.
