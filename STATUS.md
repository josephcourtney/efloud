# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

Phase 6 of the repository-centered migration is implemented: source membership,
coverage, change evidence, integrity expectations, and reconciliation now have a
protocol-independent model. The active implementation frontier is Phase 7:
migrating collection/fanout acquisition through `SourceInventory` and the generic
reconciler.

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
- normalized `InventoryCoverage`, `InventoryItem`, and `SourceInventory` models
  shared by HTTP/REST, rsync, and synthetic collection evidence
- explicit `ChangeToken` evidence separated from content identity and
  `IntegrityExpectation` assertions checked against independently computed
  `ContentId` values
- protocol-independent reconciliation that deterministically classifies inventory
  members as new, changed, unchanged, or absent
- absence inference restricted to successful complete coverage of the relevant
  source scope, including conservative handling of unknown paths under partial
  scopes
- rsync inventory routed through generic reconciliation while retaining changed/new
  observations, unchanged-content reuse, scoped snapshots, and deletion evidence
- conservative rsync delta fallback when authoritative enumeration fails
- `source:` query/status compatibility paths prefer repository state when
  `metadata.sqlite` exists and fall back to legacy manifests for old stores

Still transitional:

- collection/fanout enumeration has not yet been routed through `SourceInventory`;
  its repository recording remains a compatibility import path
- `Engine.sync()` still invokes legacy acquisition before importing results into the
  repository rather than executing a canonical adapter/planner path
- compatibility manifests/state and some legacy resolver/control-flow mechanisms
  remain during the authority migration
- the full repository formatting, lint, type, and pytest quality gate has not been
  executed for the Phase 6 changes in the available execution environment

## Continuity

Next implement Phase 7 by expressing collection enumeration as `SourceInventory`,
using generic reconciliation for membership and absence, and preserving current
per-item acquisition/provenance behavior. Then run the full project quality gate
before depending on the normalized inventory layer in later phases.
