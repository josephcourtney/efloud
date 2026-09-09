# STATUS.md

File Purpose: Current implementation state and verified handoff evidence.

## Current Focus

Checkpoint of the Phase 14-17 work at version 0.1.0. Further repairs were stopped at the user's request on 2026-09-09; this records the implemented scope and remaining verification without declaring remote CI or every plan acceptance criterion complete.

## Implemented State

- Snapshot-backed datasets support exact/latest-complete source snapshots, exact observations, historical source/role/tag filters, artifact-key prefixes, and inclusive observation-time bounds.
- New snapshots bind exact observation IDs. Dataset constraints cover complete snapshots, same-run membership, maximum observation skew, and existing validator/version evidence, with structured failures.
- Detached manifest v1 supports deterministic export, read-only exact import into another repository, and content verification independent of SQLite. A standard-library-only consumer fixture exercises the detached handoff.
- Materialization consumes RepositoryView, validates paths/collisions, supports copy, native CoW, and private-content symlink exports, and atomically publishes without replacing existing destinations. Dry-run planning does not write.
- Query/status readers, adapter contexts, and index read contracts use RepositoryView. Deprecated sync(cfg) delegates to Engine. Engine projection output is isolated under compatibility; historical import helpers are under efloud.compat.
- The public API uses RsyncMode/rsync_mode/rsync_paths and semantic ContentRef fields. SQLite has one implementation with supported historical migrations and a compatibility import alias.
- Local writer leases cover repository initialization through close. Maintenance audits references/content, reports reachability, cleans unreferenced content with explicit grace periods, and repairs abandoned run/operation statuses.
- Recovery does not replay unknown transport side effects or promote partial snapshots. Retry acquisition through a fresh canonical Engine run. Historical retention/pruning remains deferred.

## Verified Locally

- Complete suite: **186 passed** on each of Python **3.12.12, 3.13.9, and 3.14.0**.
- Ruff lint and formatting checks, ty, and git diff whitespace checks passed.
- Import architecture: **7 contracts kept, 0 broken** after correcting the TOML namespace that previously loaded zero contracts.
- Comparable pytest coverage: lines **85.02% → 86.16%**; branches **60.44% → 62.80%**. No pre-existing coverage.xml was present; the baseline was generated before implementation.
- Failure-injection coverage includes blob-before-metadata failure, metadata-before-snapshot failure, abrupt process exit, recovery/retry, concurrent processes, and an export destination appearing during publication.
- Three pre-existing missing-size-marker warnings remain in test_absence_evidence.py. The baseline collection-completeness assertion was corrected to match unresolved acquisition semantics.

## Remaining Verification and Boundaries

- The aggregate Python 3.14 just check recipe and remote CI have **not** been run for this checkpoint. Individual required checks and the complete interpreter matrix above passed.
- Generic detached catalog/verification behavior is tested; an actual external BVP acceptance fixture has **not** been run.
- Native CoW and atomic publication were exercised on macOS. The Linux-specific native branches have not been exercised here; writer coordination is local POSIX, not distributed.
- Historical compatibility importers, projection serializers, TTL indexes, and manifest-based fanout extension seams remain explicit compatibility facilities. They are not asserted to have been fully removed.

See TODO.md for completed items and outstanding verification, docs/api.md for the public/compatibility boundary, and ADR-0009 for durability and handoff decisions.
