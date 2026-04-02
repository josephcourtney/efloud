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

### Changed

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
