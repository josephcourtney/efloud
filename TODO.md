# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Define the Phase 14 dataset-resolution vocabulary

Files: `src/efloud/datasets.py`, repository/query interfaces, focused dataset tests

- [x] define snapshot-backed selectors for an exact source snapshot and the latest complete source snapshot
- [x] define source/role/tag selection without introducing domain-specific semantics
- [x] keep namespace as an artifact-key prefix/filter convention unless implementation proves first-class metadata is necessary
- [x] make repository observation time the initial explicit temporal basis; do not silently substitute upstream modification time
- [x] keep all dataset resolution read-only, including through `ReadOnlyRepository`

Acceptance: every new selector has deterministic serialized form and resolution semantics that do not acquire, validate, migrate, or mutate repository state.

## 2. Implement snapshot-backed and source-metadata selection

Files: dataset resolver, repository metadata/query helpers, source/snapshot tests

- [x] resolve exact source-snapshot membership from recorded snapshot/tree evidence
- [x] resolve latest-complete snapshots without treating partial/failed coverage as absence
- [x] select by source, role, and tag using the source-definition revision associated with historical evidence rather than the current source definition
- [x] define behavior for migrated pre-v3 evidence whose source-definition revision is unknown
- [x] preserve frozen `DatasetId`, `DatasetSpecificationId`, and content-equivalence semantics from ADR-0008

Acceptance: later ingestion or later source-definition changes cannot alter an already resolved dataset, and incomplete source coverage cannot remove members by implication.

## 3. Add explicit dataset consistency constraints

Files: dataset definition/resolution types, validation query helpers, constraint tests

- [x] support required complete-snapshot evidence where requested
- [x] support optional same-run membership constraints
- [x] support optional maximum observation-time skew
- [x] support required existing validation evidence by validator identity/version
- [x] fail resolution with structured/explainable constraint results rather than triggering validation or acquisition

Acceptance: completeness, run coherence, skew, and validation requirements are deterministic, inspectable, and tested for both passing and failing cases.

## 4. Define and serialize detached dataset manifest v1

Files: dataset manifest/export module, JSON typing helpers, serialization tests

- [x] define a versioned deterministic detached manifest/lockfile format
- [x] include exact artifact keys, observation IDs, content IDs, roles, content metadata, relevant source-definition revision IDs and snapshot IDs, specification identity, and constraint results
- [x] assign explicit safe logical export paths without depending on repository/blob filesystem paths
- [x] canonicalize member ordering and JSON serialization
- [x] ensure the manifest can be interpreted without reading Efloud SQLite internals

Acceptance: serializing the same immutable dataset produces byte-identical metadata independent of repository root/blob placement.

## 5. Exercise the downstream handoff boundary

Files: generic acceptance fixture/tests; BVP-facing fixture only as an external consumer

- [ ] reproduce the catalog/verification information needed by BVP through generic immutable-dataset APIs and detached manifests
  - Generic standard-library consumer verification passes; the external BVP fixture has not been run.
- [x] do not add BVP-specific fields or repository semantics
- [x] verify the same dataset can be inspected through normal `Repository` and non-mutating `ReadOnlyRepository`

Acceptance: a downstream consumer can determine exact dataset membership and content identity from the generic API/manifest without importing private repository implementation details.

## 6. Verify Phase 14

- [ ] run the non-mutating Python 3.14 `just check` CI gate
- [x] run the complete suite on Python 3.12, 3.13, and 3.14 (186 passed on each)
- [x] verify focused snapshot, temporal, constraint, source-revision, detached-manifest, and read-only tests
- [x] verify compatibility manifests/state remain projections only

Acceptance: Phase 14 is green from a clean checkout and leaves `PLAN.md` Phase 15 materialization/export as the next frontier.

## 7. Phase 15 safe materialization

- [x] export through RepositoryView with explicit deterministic logical paths
- [x] support auto/CoW, copy, and private-content symlink strategies
- [x] reject traversal, reserved paths, case-folding collisions, and ancestor conflicts
- [x] publish a verified sibling tree atomically without replacing an existing destination
- [x] include detached provenance manifests and provide non-mutating dry-run plans
- [x] prove export edits cannot modify repository content

## 8. Phase 16 API finalization

- [x] route query/status, adapter contexts, and dataset consumers through RepositoryView
- [x] delegate deprecated sync(cfg) to Engine and isolate engine compatibility outputs
- [x] isolate historical projection/import helpers under explicit compatibility code
- [x] collapse SQLite implementation inheritance while preserving supported schema upgrades
- [x] remove storage-key and mirror-mode concepts from the stable semantic API
- [x] document public, extension, compatibility, and implementation boundaries
- [x] enforce all seven architecture contracts, including the new dataset/export modules

## 9. Phase 17 local durability

- [x] coordinate writers, initialization, validation staging, and maintenance with an OS lease
- [x] audit SQLite references, blobs, trees, datasets, source revisions, and complete snapshots
- [x] explain reachability through historical content references, validations, and provenance
- [x] detect orphan blobs and unreferenced content rows; require explicit grace periods for cleanup
- [x] refuse cleanup on unknown schemas and dangling metadata
- [x] repair abandoned run/operation status without claiming successful acquisition or snapshot completion
- [x] verify interrupted blob/metadata/snapshot writes, retry after recovery, and concurrent processes

The original Phase 14 acceptance statement above describes the former task scope;
this checkpoint also implements the Phase 15-17 items above. Individual checks and
interpreter matrix evidence are recorded in STATUS.md; the aggregate gate and
remote CI remain unverified. Further repairs stopped at the user's request.

## 10. Checkpoint follow-up verification

- [ ] exercise native Linux CoW and atomic no-replace publication branches on Linux
- [ ] run remote CI against the committed checkout
- [ ] assess remaining explicit compatibility facilities against Phase 16 removal criteria before declaring the entire compatibility cleanup complete

Local evidence at this checkpoint: Ruff, formatting, ty, seven import contracts,
and the 186-test matrix passed. Line coverage rose from 85.02% to 86.16%; branch
coverage rose from 60.44% to 62.80%. Three existing size-marker warnings remain.
