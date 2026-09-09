# PLAN.md

Purpose: define how the current design will be completed, including milestone ordering, dependencies, and contingent follow-on work. Current completion state belongs in `STATUS.md`; concrete execution tasks belong in `TODO.md`.

`DESIGN.md` is authoritative for architecture, requirements, and invariants. ADR-0007, ADR-0008, and ADR-0009 record durable decisions relevant to the remaining work.

## Execution strategy

Complete the repository-centered architecture by stabilizing the compatibility boundary first, then re-validating durability and consumer handoff against that final boundary.

### Milestone 1 — Finalize the canonical API and compatibility boundary

Complete the remaining Phase 16 cleanup using `docs/compatibility-inventory.md` as the support/caller inventory.

- Keep `Engine`, `Repository`, read-only repository views, immutable datasets, and deliberate adapter/validator interfaces as the canonical surfaces.
- Remove obsolete migration/import implementations when no supported path requires them.
- Keep required schema upgrades and intentionally supported legacy entry points behind explicit compatibility adapters.
- Prevent canonical execution and extension contracts from depending on compatibility manifests, mirrors, caches, or serializers.

Exit condition: compatibility is optional and isolated, with one canonical execution/state path and a deliberately small public semantic API.

### Milestone 2 — Re-validate durability on the finalized mutation paths

After Milestone 1, re-audit writer coordination, crash boundaries, recovery, reachability, and cleanup against the actual final execution paths.

Do not broaden this milestone into historical retention/pruning. Safe cleanup may remove only storage objects that are not required by surviving authoritative metadata.

Exit condition: destructive maintenance cannot race supported writers, and recovery/cleanup cannot invalidate or fabricate historical repository evidence.

### Milestone 3 — Close immutable dataset and detached-export acceptance

After the public boundary and durability paths are stable, exercise the complete freeze → export → reopen elsewhere → verify workflow through public interfaces.

Include incomplete-coverage behavior, source-definition changes, missing/corrupt content, export collision/path safety, concurrent destination publication, and native Linux publication/CoW branches.

Exit condition: a generic downstream consumer can interpret and validate a reproducible detached export without Efloud internals, mutation, or domain-specific semantics.

### Milestone 4 — Complete release verification

Run the repository's non-mutating quality gate, supported-Python matrix, packaging checks, architecture contracts, coverage comparison, and remote CI against the committed checkout.

Exit condition: Phase 14-17 acceptance evidence distinguishes implementation completion, local verification, and committed-checkout CI verification.

### Milestone 5 — Validate the external consumer boundary

Run the BVP acceptance fixture only after the generic Efloud boundary is complete. Treat it as external integration evidence, not as a source of BVP-specific behavior for Efloud.

Any failure must first be classified as either a generic Efloud capability gap or a BVP-specific interpretation requirement.

Exit condition: BVP can implement its workflow through Efloud public APIs and detached manifests without private SQLite or compatibility representations.

## Contingent later milestones

These are activated only by concrete requirements; they are not part of current Phase 14-17 completion.

### Historical retention and pruning

If storage pressure requires deletion of valid historical state, define explicit retention roots and policies before implementation. Preserve retained datasets and their required transitive provenance, and require dry-run impact reporting before destructive pruning.

### Additional source adapters

Add a protocol adapter only when an actual upstream source cannot be represented by existing adapters. Protocol-specific evidence must fit the existing normalized coverage/reconciliation model without protocol-specific repository semantics.

### Advanced storage and distribution

Recursive Merkle trees, mutable references, replica tracking, alternate blob stores, plugin discovery, and distributed coordination remain deferred until measurements or concrete workflows justify their complexity.

## Verification policy

Every active milestone must preserve the architecture and invariants in `DESIGN.md` and relevant ADRs. Completion requires focused regression tests for changed repository invariants, non-mutating read-only behavior, migration coverage for schema changes, and downstream fixtures that use generic public interfaces rather than private implementation details.
