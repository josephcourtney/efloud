# TODO.md

Purpose: ephemeral, execution-level tasks for the next development work. Completed items are removed rather than retained as history.

## 1. Re-verify durability on the reduced mutation surface

- [ ] Enumerate every remaining authoritative mutation path and verify writer/maintenance coordination covers repository creation/opening, acquisition, validation staging, metadata commit, dataset freeze, and maintenance.
- [ ] Review crash boundaries and recovery transitions so recovery cannot invent successful operations or complete snapshots.
- [ ] Verify cleanup reachability preserves all current historical references, including validation-only content and transitive provenance.
- [ ] Test dry-run reason codes, grace-period handling, and fail-closed cleanup for invalid metadata.
- [ ] Add failure-injection coverage for any gaps found, including concurrent writers and retry after recovery.

Acceptance: destructive maintenance cannot race a supported writer, and recovery/cleanup preserve historical correctness through only the new repository API.

## 2. Close dataset and export acceptance through the new API

Depends on TODO 1.

- [ ] Verify `resolve` versus `freeze` side effects and identities through `repo.datasets`.
- [ ] Verify freeze → export → reopen/verify elsewhere through public interfaces only.
- [ ] Verify frozen membership and detached metadata remain stable after newer ingestion and source-definition changes.
- [ ] Verify incomplete snapshots cannot imply absence or satisfy reproducibility requirements, including empty selections.
- [ ] Verify missing/corrupt content produces explicit verification failures without acquisition or repository mutation.
- [ ] Verify export path safety, collision handling, concurrent destination creation, and isolation from authoritative content.
- [ ] Exercise native Linux CoW and atomic no-replace publication branches.
- [ ] Verify a generic downstream consumer can interpret and validate `DatasetManifest` without importing Efloud or reading SQLite.

Acceptance: generic domain-neutral handoff is reproducible, detached, and independent of compatibility representations.

## 3. Run final repository gates

Depends on TODO 1-2.

- [ ] Run the non-mutating Python 3.14 `just check` gate.
- [ ] Run the complete suite on every Python minor version declared by `project.requires-python`.
- [ ] Run packaging checks and all architecture/import contracts.
- [ ] Compare coverage with the pre-cutover baseline and explain the expected reduction from deleted compatibility tests/code separately from genuine coverage regressions.
- [ ] Verify installed-package root exports and failures for removed compatibility imports.
- [ ] Run remote CI against the committed checkout.
- [ ] Record acceptance evidence for the clean API, compatibility deletion, durability, and detached consumer boundary.

Acceptance: all required checks pass against the committed clean-break implementation.

## 4. Migrate and run external BVP acceptance

Depends on the finalized clean API and generic acceptance above.

- [ ] Replace BVP legacy manifest/tree/fanout imports with Efloud public source/repository/dataset APIs and detached manifests.
- [ ] Verify BVP does not require private SQLite details, compatibility mirrors, old query/status helpers, or legacy extension interfaces.
- [ ] Classify any failure as a generic Efloud capability gap or BVP-specific interpretation before assigning a fix.
- [ ] Keep BVP catalog rules, artifact requirements, domain validation, and naming conventions in BVP.
- [ ] Record the external result separately from Efloud's core release-gate evidence.

Acceptance: BVP implements its workflow through the clean public boundary without reintroducing backwards compatibility into Efloud.
