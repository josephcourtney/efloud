# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

Phases 6 and 7 of the repository-centered migration are implemented. HTTP/REST,
rsync, and collection/fanout membership now share the normalized `SourceInventory`
and generic reconciliation semantics. The active implementation frontier is Phase 8:
formalizing producer identity, operation/run lifecycles, deterministic derivations,
and persistent semantic indexes as first-class repository concepts.

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
  shared by HTTP/REST, rsync, and collection/fanout evidence
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
- collection/fanout enumeration represented explicitly by `FanoutEnumeration`,
  including complete/partial coverage and optional upstream enumeration identity
- fanout serializes normalized collection `SourceInventory` immediately after
  enumeration and before per-item retrieval, keeping membership evidence independent
  from acquisition success/failure results
- collection membership is reconciled from that pre-fetch inventory; removed
  collection members are established only from generic `absent` decisions
- an enumerated item with no retrieval result remains unresolved rather than being
  inferred absent, while retrieval results not present in inventory cannot create
  authoritative collection membership
- partial collection enumerations and count-inconsistent inventory payloads cannot
  establish absence, and later complete enumerations continue to use the most recent
  complete snapshot as their baseline
- collection item change/integrity evidence is preserved through fanout inventory
  serialization and source-snapshot/tree evidence while current per-item
  observations, request metadata, and materializations remain compatible
- conservative rsync delta fallback when authoritative enumeration fails
- `source:` query/status compatibility paths prefer repository state when
  `metadata.sqlite` exists and fall back to legacy manifests for old stores

Still transitional:

- collection acquisition is still executed by the legacy derived-task/fanout path;
  normalized inventory/reconciliation is consumed at the repository boundary until
  the canonical planner/adapter runtime is introduced
- producer identity/version and operation lifecycle states are not yet enforced as
  first-class repository semantics
- deterministic derived-result reuse and derivation keys are not yet implemented
- `Engine.sync()` still invokes legacy acquisition before importing results into the
  repository rather than executing a canonical adapter/planner path
- compatibility manifests/state and some legacy resolver/control-flow mechanisms
  remain during the authority migration
- the full repository formatting, lint, type, and pytest quality gate has not been
  executed for the Phase 6/7 changes in the available execution environment

## Continuity

Next implement Phase 8: introduce stable producer identity/version, enforce run and
operation lifecycle transitions, define deterministic derivation identities and
reuse semantics, and migrate persistent semantic indexes away from TTL-based
validity where their outputs are deterministic.
