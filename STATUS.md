# STATUS.md

File Purpose: Current project state and continuity notes for the next development pass.

## Current Focus

Phase 13 repository/persistence hardening is complete and CI-verified. The active frontier is `PLAN.md` Phase 14: complete immutable dataset selection, temporal/coherence policies, and the detached consumer manifest.

## Current State

- Canonical execution remains `Engine -> SyncPlanner -> SyncExecutor -> Repository`; compatibility manifests/mirror state are projections only.
- GitHub Actions uses a non-mutating Python 3.14 `just check` gate and runs the complete test suite on Python 3.12-3.14.
- SQLite metadata uses explicit schema version 3 migration from supported historical schemas; future unknown schema versions are rejected.
- Source definitions have immutable content-addressed revisions. New source-scoped operations, observations, absences, and snapshots retain the active revision; migrated pre-v3 evidence remains revision-unknown rather than receiving invented provenance. See ADR-0007.
- Dataset specification identity is distinct from exact frozen membership identity and content equivalence. Multiple specifications resolving to one membership are retained deterministically. See ADR-0008.
- `ReadOnlyRepository` provides repository inspection without directory creation, schema migration, or blob/metadata mutation.
- Existing immutable datasets still support exact/latest/latest-before/latest-all selection and repository-mediated open/verify.

## Important Gaps

- Dataset selection is not yet snapshot-backed and cannot yet select generically by historical source/role/tag metadata.
- Complete-snapshot, same-run, maximum-skew, and required-validation constraints are not yet part of dataset resolution.
- There is no versioned detached dataset manifest/lockfile suitable as the stable downstream handoff boundary.
- Legacy `sync(cfg)` and other migration/compatibility surfaces remain exported pending Phase 16 cleanup.
- Repository-wide maintenance locking, crash recovery, audit/fsck, and safe GC remain Phase 17 work.

## Continuity

Execute `TODO.md` as Phase 14. Preserve ADR-0007/0008 identity semantics, keep resolution read-only (including through `ReadOnlyRepository`), and use BVP only as an external acceptance fixture for generic dataset behavior.
