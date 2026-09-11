# CHANGELOG.md

All notable changes to Efloud are documented here following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Expose the declarative `Project`, `ProjectLock`, collection-provider protocol, and collection-definition/value types from the package root so applications can use `efloud.toml`/`efloud.lock` without importing focused implementation modules.
- Add `LocalSource` as a built-in single-file acquisition source that stages a stable local copy, validates and records it through ordinary Engine execution, and pins immutable bytes independently of the originating file.
- Make the existing `efloud.collections` contract a supported advanced extension surface and pass `CollectionDefinition` values through the public `Engine(..., collections=...)` facade.
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

- Add the clean-break `Repository`/`Engine`/typed-source/`DatasetSpec` public facade.
- Add immutable dataset freeze, detached export, and repository maintenance APIs.

### Changed

- Replace the alpha compatibility surface with the clean public repository/acquisition/dataset model.
