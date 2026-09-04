# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

The repository-centered migration is in the read/cutover stage. Acquisition can now
populate the new repository while legacy manifests and mirrors remain available for
compatibility. The next work is to make repository-backed queries/status the normal
read path, then replace legacy rsync delta import with authoritative reconciliation.

## Current State

Implemented on `main`:

- typed repository identities and immutable SHA-256 content-addressed blob storage
- SQLite metadata persistence with schema migration support
- logical artifacts, observations, provenance edges, validations, materializations,
  source/tree snapshots, and explicit artifact-absence states
- immutable datasets with exact, latest, and temporal selection; dataset provenance
  identity is distinct from content-equivalence identity
- transitional `Engine` integration that dual-records HTTP/REST acquisition into the
  repository while preserving existing sync outputs
- conservative rsync delta ingestion: changed files and scoped tree evidence are
  recorded, but legacy rsync snapshots remain incomplete and do not infer deletion

Legacy manifest, mirror-state, query, and status paths still exist and are not yet
fully derived from repository state.

## Validation / Risks

Focused repository/Engine tests passed during implementation, but the complete
repository quality gate has not been run in the available execution environment.
Authoritative rsync deletion semantics remain blocked on explicit enumeration and
coverage-aware reconciliation.

## Continuity

A repository-native read/query layer has been drafted and exercised locally but is
not committed. Resume by landing that layer and public exports, then migrate
source/run/status reads before changing rsync reconciliation semantics.
