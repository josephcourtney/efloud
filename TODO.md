# TODO.md

Purpose: ephemeral, execution-level tasks for the next development work. Completed items are removed rather than retained as history.

## 1. Finish the Phase 16 compatibility boundary

Use `docs/compatibility-inventory.md` as the caller/support inventory.

- [ ] Remove historical importers and duplicate implementations whose support inventory permits removal.
- [ ] Isolate supported serializers, inspectors, and legacy adapters from canonical implementation dependencies.
- [ ] Resolve the inventory decisions for TTL indexes, cache/status helpers, mirror-resolution helpers, and provenance compatibility abstractions.
- [ ] Retain and test schema upgrades required by supported existing repositories.
- [ ] Finalize the stable public API and deliberate adapter/validator extension contracts.
- [ ] Update documentation and examples to use the canonical model and identify supported compatibility entry points explicitly.
- [ ] Extend architecture contracts so canonical execution and extension contracts cannot regain compatibility dependencies.
- [ ] Verify canonical ingestion, queries, datasets, and exports with compatibility support disabled.

Acceptance: compatibility is an optional, explicit boundary; canonical execution does not depend on compatibility representations.

## 2. Re-verify Phase 17 durability on the finalized paths

Depends on TODO 1.

- [ ] Enumerate every authoritative mutation path and verify writer/maintenance coordination covers initialization, migration, acquisition, validation staging, and metadata commit.
- [ ] Review crash boundaries and recovery transitions to ensure recovery cannot invent successful operations or complete snapshots.
- [ ] Verify cleanup reachability preserves all supported historical references, including validation-only content and transitive provenance.
- [ ] Test dry-run reason codes, grace-period handling, and fail-closed cleanup for invalid metadata.
- [ ] Add failure-injection coverage for any gaps found, including concurrent writers and retry after recovery.

Acceptance: destructive maintenance cannot race a supported writer, and recovery/cleanup preserve historical correctness.

## 3. Close Phase 14/15 dataset and export acceptance

Depends on the finalized consumer API and durability review.

- [ ] Verify freeze → export → reopen elsewhere → verify through public interfaces.
- [ ] Verify frozen membership and detached metadata remain stable after newer ingestion and source-definition changes.
- [ ] Verify incomplete snapshots cannot imply absence or satisfy reproducibility requirements, including empty selections.
- [ ] Verify missing/corrupt content produces explicit verification failures without acquisition or repository mutation.
- [ ] Verify export path safety, collision handling, concurrent destination creation, and isolation from authoritative content.
- [ ] Exercise native Linux CoW and atomic no-replace publication branches.
- [ ] Verify a generic downstream consumer can interpret and validate a detached export without importing Efloud or reading SQLite.

Acceptance: generic, domain-neutral handoff is reproducible and independent of Efloud internals.

## 4. Run final repository gates

Depends on TODO 1-3.

- [ ] Run the non-mutating Python 3.14 `just check` gate.
- [ ] Run the complete suite on every Python minor version declared by `project.requires-python`.
- [ ] Run packaging checks and architecture contracts.
- [ ] Compare coverage with the recorded baseline and resolve any decrease according to repository policy.
- [ ] Run remote CI against the committed checkout.
- [ ] Record evidence for each Phase 14-17 acceptance criterion, distinguishing implementation, local verification, and CI verification.

Acceptance: all required checks pass against the committed implementation.

## 5. Run external BVP acceptance

Depends on the finalized public APIs and generic acceptance above.

- [ ] Run BVP's catalog/verification fixture using only Efloud public APIs and detached manifests.
- [ ] Verify BVP does not require private SQLite details or compatibility mirrors.
- [ ] Classify any gap as a generic Efloud capability or BVP-specific interpretation before assigning a fix.
- [ ] Keep BVP catalog rules, artifact requirements, domain validation, and naming conventions in BVP.
- [ ] Record the external result separately from Efloud's core release-gate evidence.

Acceptance: BVP can implement its workflow through the public boundary without introducing BVP-specific behavior into Efloud.
