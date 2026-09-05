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
- add explicit `FanoutEnumeration` membership evidence with complete/partial coverage, upstream enumeration identity, change tokens, and integrity expectations

### Changed
- change temporal dataset resolution to treat an explicit later absence as authoritative instead of falling back to an older content-bearing observation
- record legacy rsync changes as scoped, incomplete repository snapshots; source-relative paths are preserved, but deletion is not inferred when the existing rsync mode cannot prove upstream absence
- add additive SQLite schema migration support for repository metadata evolution
- change `Engine.sync()` rsync recording to attempt authoritative remote enumeration after successful transfer and fall back to conservative delta recording when enumeration is incomplete or unavailable
- change initialized-repository `source:` queries and source status rows to prefer SQLite/blob repository state while preserving manifest fallback for older stores without repository metadata
- expose the repository, immutable dataset selectors/types, repository identities, query service, and repository status service through the package public API
- route rsync inventory classification through the generic reconciliation layer while preserving repository observations, unchanged-content reuse, scoped snapshots, and deletion semantics
- route collection/fanout membership through `SourceInventory` and generic reconciliation so removed-item absence is inferred only from complete enumeration coverage
- preserve the latest complete collection snapshot as the reconciliation baseline across intervening partial enumerations

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
- fix low-visibility rsync indexing behavior by surfacing elapsed-time, idle-time, and optional file-list-count progress while the remote file list is still being built
- fix path canonicalization edge cases by normalizing resolved artifact paths before indexing

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

### Added

### Changed
- change rsync subprocess spawning to avoid `start_new_session=True` so terminal interrupts can propagate to the active transfer process

### Deprecated

### Removed

### Fixed
- fix `bvp sync` Ctrl-C interruption behavior by allowing SIGINT delivery to child rsync processes instead of isolating them in a separate session
- add regression coverage that asserts rsync process launch arguments do not enable `start_new_session`

### Security

## [0.0.6] - 2026-04-02

### Added
- add compact shard-level runtime progress for `pdb_mmcif` path syncs so normal output reports one continuously updating overall shard status line instead of per-shard transport chatter

### Changed
- change `run_rsync_phase` orchestration structure by extracting per-source rsync execution helpers, keeping behavior stable while reducing inline branching complexity

### Deprecated

### Removed

### Fixed
- fix normal `pdb_mmcif` runtime output flooding by suppressing per-shard transport progress in non-debug mode while retaining detailed per-shard diagnostics in debug logging mode

### Security

## [0.0.5] - 2026-04-02

### Added
- add rsync transfer-progress enrichment with handled-file fractions, transferred-file counts, cumulative bytes, throughput, and idle-since-last-output timing in runtime progress output
- add mirror-state subtree file and directory counts plus manifest integrity count payloads so downstream integrity scans can report percentage completion
- add an rsync prefilter for `pdb_mmcif` bucket paths that discovers existing remote `mmCIF` buckets via one `--list-only` request and skips non-existent shards before transfer

### Changed
- change `pdb_mmcif` runtime command profile to disable `--compress` and `--copy-links` while keeping archive/itemize semantics
- change rsync heartbeat timeout bars to countdown semantics (remaining time) instead of elapsed-fill semantics

### Deprecated

### Removed

### Fixed
- fix rsync phase reporting so transfer markers (`xfr#`, `to-check`) take precedence over earlier file-list text when classifying failure phase
- fix `pdb_mmcif` shard handling so missing remote bucket directories (`code 23` `change_dir` no-such-file) are normalized to skipped shards instead of source-fatal errors
- fix default PDB rsync roots and source defaults to use `.../data/structures/divided/` consistently, including legacy-config canonicalization from `.../all/`

### Security

## [0.0.3] - 2026-04-01

### Added
- add first-class rsync port support so callers can target non-default rsync daemon ports without encoding transport details into remote strings

### Changed
- add rsync connect preflight diagnostics, retry countdowns, and active-phase heartbeat output so connect stalls remain visible while a sync is running
- record rsync retry metadata and attempt history in manifests and normalized summaries so callers can explain retry behavior in higher-level status output

### Deprecated

### Removed
- remove obsolete check-command tests that still targeted the retired `efloud.app` and `efloud.cli.root` package layout

### Fixed
- fix intermittent rsync daemon connect failures by retrying transient socket and connect errors before marking mirror operations as failed
- fix path-scoped rsync diagnostics so the displayed target matches the actual remote subtree being synced
- fix lint violations across sync, locator, query, status, and transport helpers by extracting smaller helper routines and cleaning import/docstring issues
- fix pytest warning noise by installing `pytest-test-categories`, adding explicit size markers to the unit suite, and aligning pytest category enforcement settings with the current medium-sized test mix

### Security

## [0.0.1] - 2026-04-01

### Added

### Changed
- add bounded retries for transient rsync transport failures and persist retry metadata in sync manifests and summaries
- expose rsync retry counts and request counts through the normalized summary payload so callers can report successful retries distinctly from first-attempt success

### Deprecated

### Removed

### Fixed
- fix intermittent rsync daemon connect timeouts by retrying transient socket and connect failures before marking the mirror operation as failed

### Security

## [0.0.0] - 2026-02-23

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security
