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
