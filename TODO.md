# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Define the Phase 14 dataset-resolution vocabulary

Files: `src/efloud/datasets.py`, repository/query interfaces, focused dataset tests

- define snapshot-backed selectors for an exact source snapshot and the latest complete source snapshot
- define source/role/tag selection without introducing domain-specific semantics
- keep namespace as an artifact-key prefix/filter convention unless implementation proves first-class metadata is necessary
- make repository observation time the initial explicit temporal basis; do not silently substitute upstream modification time
- keep all dataset resolution read-only, including through `ReadOnlyRepository`

Acceptance: every new selector has deterministic serialized form and resolution semantics that do not acquire, validate, migrate, or mutate repository state.

## 2. Implement snapshot-backed and source-metadata selection

Files: dataset resolver, repository metadata/query helpers, source/snapshot tests

- resolve exact source-snapshot membership from recorded snapshot/tree evidence
- resolve latest-complete snapshots without treating partial/failed coverage as absence
- select by source, role, and tag using the source-definition revision associated with historical evidence rather than the current source definition
- define behavior for migrated pre-v3 evidence whose source-definition revision is unknown
- preserve frozen `DatasetId`, `DatasetSpecificationId`, and content-equivalence semantics from ADR-0008

Acceptance: later ingestion or later source-definition changes cannot alter an already resolved dataset, and incomplete source coverage cannot remove members by implication.

## 3. Add explicit dataset consistency constraints

Files: dataset definition/resolution types, validation query helpers, constraint tests

- support required complete-snapshot evidence where requested
- support optional same-run membership constraints
- support optional maximum observation-time skew
- support required existing validation evidence by validator identity/version
- fail resolution with structured/explainable constraint results rather than triggering validation or acquisition

Acceptance: completeness, run coherence, skew, and validation requirements are deterministic, inspectable, and tested for both passing and failing cases.

## 4. Define and serialize detached dataset manifest v1

Files: dataset manifest/export module, JSON typing helpers, serialization tests

- define a versioned deterministic detached manifest/lockfile format
- include exact artifact keys, observation IDs, content IDs, roles, content metadata, relevant source-definition revision IDs and snapshot IDs, specification identity, and constraint results
- assign explicit safe logical export paths without depending on repository/blob filesystem paths
- canonicalize member ordering and JSON serialization
- ensure the manifest can be interpreted without reading Efloud SQLite internals

Acceptance: serializing the same immutable dataset produces byte-identical metadata independent of repository root/blob placement.

## 5. Exercise the downstream handoff boundary

Files: generic acceptance fixture/tests; BVP-facing fixture only as an external consumer

- reproduce the catalog/verification information needed by BVP through generic immutable-dataset APIs and detached manifests
- do not add BVP-specific fields or repository semantics
- verify the same dataset can be inspected through normal `Repository` and non-mutating `ReadOnlyRepository`

Acceptance: a downstream consumer can determine exact dataset membership and content identity from the generic API/manifest without importing private repository implementation details.

## 6. Verify Phase 14

- run the non-mutating Python 3.14 `just check` CI gate
- run the complete suite on Python 3.12, 3.13, and 3.14
- verify focused snapshot, temporal, constraint, source-revision, detached-manifest, and read-only tests
- verify compatibility manifests/state remain projections only

Acceptance: Phase 14 is green from a clean checkout and leaves `PLAN.md` Phase 15 materialization/export as the next frontier.
