# CHANGELOG.md

All notable changes to Efloud are documented here following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Add a post-compatibility durability audit enumerating the remaining authoritative mutation paths, crash boundaries, coordination requirements, and acceptance evidence.

### Changed

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
- Add deterministic detached dataset manifests, exact import, standalone verification, and safe materialization using copy, native CoW, or explicit private-content symlinks.
- Add repository-native inspection/status APIs and read-only repository access that can operate without canonical manifests or mirror-state files.
- Add local POSIX writer leases, repository audit/reachability, grace-period orphan cleanup, and abandoned-operation recovery.

### Changed

- Treat later authoritative absence as decisive during temporal dataset resolution instead of falling back to older content-bearing observations.
- Record source coverage conservatively: deletion/absence is inferred only when enumeration proves the relevant scope complete.
- Preserve source-definition revision evidence for historical source/role/tag interpretation instead of applying current source configuration retroactively.
- Route query/status readers, adapter contexts, dataset consumers, and repository-backed semantic indexes through repository-native interfaces.
- Consolidate SQLite persistence into one canonical implementation while retaining supported additive schema upgrades.
- Expose repository, dataset, query, and status semantics through the public API while isolating compatibility projections and historical import helpers.

### Deprecated

- Deprecate legacy `sync(cfg)` in favor of canonical `Engine` orchestration.

### Removed

- Remove storage placement and mirror-mode concepts from stable semantic content references and top-level APIs.
- Remove the unused transient acquisition path and isolate historical import/projection helpers under explicit compatibility code.

### Fixed

- Preserve frozen source-snapshot observation bindings after subsequent ingestion.
- Flush CAS directory entries before reporting durable content and reject corrupted reused blobs.
- Prevent temporal dataset selection from resurrecting artifacts with later authoritative absence evidence.
- Close in-flight repository operations when an Engine import run fails so lifecycle state cannot remain impossibly `running`.

## [0.0.9] - 2026-04-07

### Added

- Add macOS rsync indexing telemetry for temporary-file activity and active TCP connection state during long-running transfers.

### Changed

- Emit periodic indexing heartbeats while rsync is receiving the file list and reduce the file-list stall warning threshold from 300 seconds to 30 seconds.
- Normalize canonical paths consistently with `resolve()` plus `normpath()`.

### Fixed

- Surface elapsed, idle, and optional file-count progress while rsync is still building a remote file list.

## [0.0.7] - 2026-04-02

### Fixed

- Allow terminal SIGINT to reach child rsync processes so `bvp sync` can be interrupted normally with Ctrl-C.

## [0.0.6] - 2026-04-02

### Added

- Add compact shard-level runtime progress for `pdb_mmcif` path synchronization.

### Fixed

- Suppress per-shard transport chatter in normal `pdb_mmcif` output while retaining detailed debug diagnostics.

## [0.0.5] - 2026-04-02

### Added

- Add rsync transfer progress with handled-file fractions, transferred-file counts, cumulative bytes, throughput, and idle timing.
- Add mirror-state file/directory counts and manifest integrity counts for percentage-based downstream scans.
- Add `pdb_mmcif` remote-bucket discovery so nonexistent shards are skipped before transfer.

### Changed

- Disable rsync compression and copy-links for the `pdb_mmcif` runtime profile while preserving archive/itemize semantics.
- Report rsync heartbeat timeouts as remaining-time countdowns.

### Fixed

- Prefer transfer markers over earlier file-list text when classifying rsync failure phases.
- Treat missing remote `pdb_mmcif` bucket directories as skipped shards instead of source-fatal errors.
- Use the divided-structure PDB rsync root consistently, including legacy configuration canonicalization.

## [0.0.3] - 2026-04-01

### Added

- Add first-class rsync daemon port configuration.

### Changed

- Add rsync connection preflight diagnostics, bounded transient-failure retries, retry countdowns, and active-phase heartbeat output.
- Record rsync retry metadata and attempt history in manifests and normalized summaries.

### Removed

- Remove obsolete check-command behavior tied to the retired `efloud.app` and `efloud.cli.root` layout.

### Fixed

- Retry transient rsync socket/connect failures before marking mirror operations failed.
- Make path-scoped rsync diagnostics display the actual remote subtree being synchronized.

## [0.0.1] - 2026-04-01

### Changed

- Add bounded retries for transient rsync transport failures and expose retry/request counts through normalized summaries.

### Fixed

- Avoid treating intermittent rsync daemon connection timeouts as immediate mirror-operation failures.

## [0.0.0] - 2026-02-23

### Added

- Initial release.
