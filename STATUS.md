# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

The repository-centered migration through validation is complete and CI-verified. The active frontier is `PLAN.md` Phase 13: repository and persistence hardening before richer dataset semantics.

## Current State

- Canonical execution is `Engine -> SyncPlanner -> SyncExecutor -> Repository`.
- Repository state, not compatibility manifests/mirror-state files, is authoritative.
- Source inventory/reconciliation, producer/lifecycle semantics, path-independent blob storage, derivations, and validation evidence are repository-native.
- Immutable datasets already support exact/latest/latest-before/latest-all selection, frozen observation membership, content equivalence, and repository-mediated reads.
- GitHub Actions runs the development gate on Python 3.14 and full tests on Python 3.12-3.14.

## Important Gaps

- The Python 3.14 CI job currently runs mutating formatter/linter recipes; CI must be changed to verify rather than repair the checkout.
- SQLite schema evolution is still largely additive initialization rather than explicit ordered migrations.
- Registering a source replaces its stored definition, so historical observations do not yet retain an explicit source-definition revision.
- Dataset membership identity can collide for different specifications that resolve to the same observations, leaving specification identity ambiguous.
- Legacy `sync(cfg)` and other migration/compatibility surfaces remain exported even though canonical execution no longer depends on them.
- Repository-wide maintenance locking, crash recovery, audit/fsck, and safe GC are not implemented.

## Continuity

Execute `TODO.md` as Phase 13: make CI non-mutating, add schema migrations, preserve source-definition revisions, and settle dataset specification/membership/content identity semantics. Capture durable choices in ADRs where `POLICY.md` requires them.

After Phase 13 is green in CI, proceed to `PLAN.md` Phase 14: snapshot-backed immutable datasets, explicit temporal/coherence policies, validation requirements, and deterministic detached dataset manifests.
