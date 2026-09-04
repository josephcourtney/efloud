# CHANGELOG.md

Curated, user-facing record, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

All notable changes to this project will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/)

Items should be categorized under these headings:

- **Added** - new features
- **Changed** - changes in existing functionality
- **Deprecated** - soon-to-be removed features
- **Removed** - now removed features
- **Fixed** - any bug fixes
- **Security** - in case of vulnerabilities

## Unreleased

### Added
- add a repository-centered storage foundation with stable source/artifact/content/observation/run/operation/snapshot/dataset identities, SHA-256 content-addressed blob storage, and SQLite metadata persistence
- add provenance edges, validation records, materialization records, source/tree snapshots, and explicit artifact-absence states so repository history can distinguish unchanged content, changed content, and known absence
- add immutable datasets with exact, latest, latest-before, and latest-all selection plus separate provenance-sensitive dataset identity and content-equivalence identity
- add a transitional `Engine` that preserves existing sync outputs while recording HTTP/REST acquisitions and rsync file deltas into the repository
- add repository-native artifact, observation, source-snapshot/tree, dataset, source, and run inspection APIs, including locator evaluation directly against immutable blob content
- add repository-backed source/run status reporting that works after reopening a repository without canonical manifests or mirror-state files
- add authoritative rsync inventory and coverage-aware reconciliation, including complete/scoped source snapshots, unchanged-content reuse, and explicit absence observations when enumeration proves deletion
- add normalized `SourceInventory`, `InventoryCoverage`, `InventoryItem`, `ChangeToken`, and `IntegrityExpectation` models for protocol-independent source evidence
- add generic reconciliation that classifies normalized inventory items as new, changed, unchanged, or absent while restricting absence to proven complete coverage

### Changed
- change temporal dataset resolution to treat an explicit later absence as authoritative instead of falling back to an older content-bearing observation
- record legacy rsync changes as scoped, incomplete repository snapshots; source-relative paths are preserved, but deletion is not inferred when the existing rsync mode cannot prove upstream absence
- add additive SQLite schema migration support for repository metadata evolution
- change `Engine.sync()` rsync recording to attempt authoritative remote enumeration after successful transfer and fall back to conservative delta recording when enumeration is incomplete or unavailable
- change initialized-repository `source:` queries and source status rows to prefer SQLite/blob repository state while preserving manifest fallback for older stores without repository metadata
- expose the repository, immutable dataset selectors/types, repository identities, query service, and repository status service through the package public API
- route rsync inventory classification through the generic reconciliation layer while preserving repository observations, unchanged-content reuse, scoped snapshots, and deletion semantics

### Deprecated

### Removed

### Fixed
- prevent temporal dataset selection from resurrecting files that have a later authoritative absence observation
- restore `sqlite_metadata.py` as valid importable source while preserving the schema-v2 absence migration and repository metadata behavior

### Security

## [0.0.9] - 2026-04-07

### Added
- add macOS-specific rsync indexing telemetry that can report local temporary-file activity and active TCP connection state during long-running transfers
- add more flexible `just` developer workflows for linting, formatting, testing, docs, complexity, and coverage via flag-driven recipes instead of parallel command aliases

### Changed
- change rsync runtime progress to emit periodic indexing heartbeats during `receiving file list` and reduce the file-list stall warning threshold from 300s to 30s
- change `just fix` to run the fast test subset by default and consolidate several recipe variants into parameterized commands
- change `canonical_path()` normalization to use `resolve()` plus `normpath()` consistently

### Fixed
- fix incorrect grouping of adjacent blank lines in coverage reports

## [0.0.8] - 2026-04-02

### Added

### Changed
- clarify subprocess-security suppression rationale in sync and rsync transport
  modules so retained `noqa` directives document why argv construction remains
  bounded and shell-free

### Deprecated

### Removed

### Fixed

### Security

## [0.0.7] - 2026-04-02
