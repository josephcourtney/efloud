# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## Remaining work — execution order

This is the active queue for completing Phases 14-17. Finish the Phase 16
compatibility boundary before final acceptance of the execution paths, durability,
and consumer APIs. The checkpoint entries below are preserved as history; their
checked boxes record individual accomplishments, not complete phase sign-off.
Outstanding items in that record are scheduled here rather than separate work.

### 1. Inventory and classify compatibility dependencies

Scope: `src/efloud/compat/`, `repository_compat.py`, `repository_state.py`,
`manifest.py`, `resolve.py`, `state.py`, and their execution/configuration callers.

- [x] inventory compatibility modules, public interfaces, and direct/transitive callers
- [x] classify each facility as required by canonical execution, a supported external compatibility adapter, obsolete migration code, or a supported schema-upgrade mechanism
- [x] record the support requirement and intended destination or removal decision for each facility before changing it
- [x] turn the inventory into a finite caller-migration and removal checklist

Acceptance: every retained compatibility dependency has an explicit purpose and
owner; every proposed removal has identified callers and support consequences.
Evidence: `docs/compatibility-inventory.md` records callers, support owners, decisions,
and the finite migration checklist.

### 2. Remove compatibility manifests from canonical execution

Scope: `collection_adapter.py`, `operation_recording.py`, `derived.py`,
`fanout.py`, and the corresponding extension contracts and tests.

- [x] define canonical collection-enumerator inputs using repository reads and explicit semantic inputs instead of `NormalizedManifest`
- [x] define canonical derived-task inputs using repository reads and explicit artifact/observation dependencies instead of `NormalizedManifest`
- [x] migrate collection acquisition and derived-operation execution to those contracts
- [x] move any required legacy manifest interface behind an explicit compatibility adapter
- [x] test canonical collection and derived execution with compatibility manifest generation unavailable

Acceptance: normal collection and derived execution no longer constructs or
consumes compatibility manifests; supported legacy callers enter through adapters.

### 3. Finish Phase 16 API and compatibility cleanup

Depends on steps 1-2.

- [ ] remove historical importers and duplicate implementations whose support/caller inventory permits removal
- [ ] isolate supported serializers, inspectors, and legacy adapters from canonical implementation dependencies
- [ ] resolve the inventory decisions for TTL indexes, cache/status helpers, mirror-resolution helpers, and provenance compatibility abstractions
- [ ] retain and test schema upgrades required by supported existing repositories
- [ ] finalize stable public APIs and deliberate adapter/validator extension contracts
- [ ] update documentation and examples to use the canonical model and identify supported compatibility entry points explicitly
- [ ] extend architecture contracts to prevent canonical execution and extension contracts from regaining compatibility dependencies
- [ ] verify canonical ingestion, queries, datasets, and exports operate with compatibility support disabled

Acceptance: compatibility is an optional boundary with defined support, not an
execution representation hidden behind renamed modules. Phase 16 removal criteria
are assessed explicitly before marking the phase complete.

### 4. Verify Phase 17 durability against the finalized execution paths

Depends on steps 2-3.

- [ ] enumerate authoritative mutation paths and verify writer/maintenance coordination covers each one, including initialization, migration, acquisition, validation staging, and metadata commit
- [ ] review crash boundaries and recovery transitions without inventing successful operations or complete snapshots
- [ ] verify cleanup reachability preserves every supported historical reference, including validation-only content and transitive provenance
- [ ] test dry-run reason codes, grace-period handling, and fail-closed cleanup behavior for invalid metadata
- [ ] add failure-injection coverage for any gaps found in the finalized paths, including concurrent writers and retry after recovery

Acceptance: destructive maintenance cannot race a supported writer; recovery and
cleanup preserve historical correctness, with evidence for each mutation boundary.

### 5. Close generic Phase 14/15 dataset and export acceptance

Depends on the finalized consumer APIs and durability review.

- [ ] verify the complete freeze → export → reopen elsewhere → verify workflow through public interfaces
- [ ] verify frozen membership and detached metadata remain stable after newer ingestion and changed source definitions
- [ ] verify incomplete snapshots cannot imply absence or satisfy reproducibility requirements, including empty selections
- [ ] verify missing/corrupt content produces explicit verification failures without acquisition or repository mutation
- [ ] verify export path safety, collision handling, concurrent destination creation, and isolation from authoritative content
- [ ] exercise native Linux CoW and atomic no-replace publication branches alongside the macOS paths
- [ ] verify a generic downstream consumer can interpret and validate the detached export without importing Efloud or reading SQLite

Acceptance: generic handoff behavior is established with domain-neutral fixtures;
Efloud tests contain no BVP catalog rules or BVP dependency.

### 6. Run complete gates and committed-checkout CI

Depends on steps 1-5; run focused checks during those steps as appropriate.

- [ ] run the non-mutating Python 3.14 `just check` gate
- [ ] run the complete suite across every supported Python minor version
- [ ] run the repository-required packaging checks and strengthened architecture contracts
- [ ] compare coverage with the recorded baseline and resolve any decrease according to repository policy
- [ ] run remote CI against the committed checkout
- [ ] record evidence against each Phase 14-17 acceptance criterion, distinguishing implementation completion, local verification, and CI verification

Acceptance: required checks pass on the final implementation and committed
checkout; phase completion claims identify any remaining external acceptance.

### 7. Run external BVP acceptance in BVP's environment

Depends on the finalized public APIs and generic acceptance above. This is
downstream integration evidence, not permission to add BVP functionality to Efloud.

- [ ] run BVP's catalog/verification fixture externally using only Efloud public APIs and detached manifests
- [ ] verify BVP does not require private SQLite details or compatibility mirrors
- [ ] classify any gap as a generic Efloud capability or BVP-specific interpretation before assigning a fix
- [ ] keep BVP catalog rules, artifact requirements, domain validation, and naming conventions in BVP
- [ ] record the external result separately from Efloud's core test and release-gate evidence

Acceptance: BVP can implement its workflow through the public boundary; Efloud's
generic functionality and core verification do not depend on BVP.

## Preserved checkpoint record — 2026-09-09

The following entries retain the previous checkpoint and its evidence. Use the
ordered queue above for new work; earlier completion wording is not a substitute
for the remaining phase acceptance checks.

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
