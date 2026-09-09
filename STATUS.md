# STATUS.md

Purpose: compact handoff record of the current project state, active focus, verified evidence, and immediate gaps.

## Current focus

Complete the Phase 16 compatibility boundary before final Phase 14-17 acceptance. `docs/compatibility-inventory.md` now identifies compatibility facilities, callers, support requirements, and removal decisions. Canonical collection and derived execution use repository-native contexts; compatibility outputs are explicit projections.

## Recently completed

- Immutable datasets support snapshot-backed selection, historical source metadata, coherence constraints, and deterministic detached manifests.
- Detached exports can be verified without reading Efloud SQLite internals; materialization validates paths and publishes atomically without replacing an existing destination.
- Query/status readers and adapter contexts use repository-facing read interfaces; deprecated `sync(cfg)` delegates to `Engine`.
- Local writer leases, repository audit/reachability, orphan cleanup with grace periods, and abandoned-operation recovery are implemented.
- Historical import/projection helpers are isolated under explicit compatibility code; duplicate sync orchestration was removed.

## Verified locally

- Complete suite: 186 passed on Python 3.12.12, 3.13.9, and 3.14.0.
- Ruff lint/format, ty, whitespace checks, and all 7 import-architecture contracts passed.
- Comparable coverage: lines 86.16%, branches 62.80%; both exceed the pre-change baseline.
- Failure-injection coverage includes interrupted metadata/snapshot writes, retry/recovery, concurrent processes, and export publication races.

## Remaining gaps

- Phase 16 still has explicit compatibility facilities to assess/remove or retain deliberately, including historical importers, serializers, TTL/cache helpers, mirror-resolution helpers, and provenance adapters.
- The aggregate Python 3.14 `just check` gate and remote CI have not yet been run against the final committed state.
- Linux-native CoW and atomic no-replace publication branches still need Linux execution evidence.
- External BVP acceptance has not been run; Efloud's generic detached-consumer fixture already passes.

## Resume point

Start with TODO 1 and `docs/compatibility-inventory.md`. Keep compatibility optional and explicit, preserve supported schema upgrades, and do not move BVP-specific semantics into Efloud.
