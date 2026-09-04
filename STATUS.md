# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

The repository-centered migration has reached the authority-cutover stage. Core
repository reads and rsync reconciliation are implemented; the next work is to
record collection/derived outputs in the repository and make compatibility
manifests/state entirely repository-derived.

## Current State

Implemented on `main`:

- typed artifact/content/observation/run/snapshot/dataset identities, SHA-256 blob
  storage, SQLite metadata, provenance, validation, materialization, and absence
  records
- immutable datasets with exact/latest/as-of selection and separate provenance vs
  content-equivalence identities
- repository-native artifact, observation, snapshot, dataset, source, run, and
  status/query APIs, including blob-backed locator evaluation
- HTTP/REST dual-recording while existing sync outputs remain available
- rsync inventory and coverage-aware reconciliation with changed/new observations,
  unchanged-content reuse, scoped snapshots, and deletion observations only when
  enumeration proves absence
- conservative rsync delta fallback when authoritative enumeration fails
- `source:` query/status compatibility paths prefer repository state when
  `metadata.sqlite` exists and fall back to legacy manifests for old stores

Still transitional:

- `REST_BASE` fanout and generic derived-task outputs are still manifest-first
- canonical manifest, mirror-state, health, summary, and some resolver paths retain
  legacy authority or duplicate repository facts
- full repository lint/type/test gates have not been run for the latest migration
  tranche in the available execution environment

## Continuity

Next implement repository recording for fanout/derived artifacts, then generate
compatibility manifest/state facts from SQLite and source snapshots. After parity,
remove remaining normal read dependencies on canonical manifests and mirror metadata.
