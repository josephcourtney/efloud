# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Finish the Phase 16 compatibility boundary before final Phase 14-17 acceptance. `docs/compatibility-inventory.md` identifies facilities, callers, support requirements, and removal decisions. Canonical collection and derived execution now use repository-native contexts; compatibility outputs are explicit projections.

## Recently completed

- Immutable datasets support snapshot-backed selection, historical source metadata, coherence constraints, and deterministic detached manifests.
- Detached exports can be verified without Efloud SQLite internals; materialization validates paths and publishes atomically without replacing an existing destination.
- Query/status readers and adapter contexts use repository-facing reads; deprecated `sync(cfg)` delegates to `Engine`.
- Local writer leases, repository audit/reachability, orphan cleanup with grace periods, and abandoned-operation recovery are implemented.
- Historical import/projection helpers are isolated under compatibility code; duplicate sync orchestration was removed.

## Verified locally

- 186 tests passed on Python 3.12.12, 3.13.9, and 3.14.0.
- Ruff lint/format, ty, whitespace checks, and all 7 import-architecture contracts passed.
- Coverage is 86.16% lines / 62.80% branches, above the pre-change baseline.
- Failure injection covers interrupted writes, retry/recovery, concurrent processes, and export publication races.

## Remaining gaps

- Remaining Phase 16 facilities include historical importers, serializers, TTL/cache helpers, mirror-resolution helpers, and provenance adapters.
- Final Python 3.14 `just check` and remote CI have not run against the committed state.
- Linux-native CoW and atomic no-replace publication still need Linux evidence.
- External BVP acceptance has not run; the generic detached-consumer fixture passes.

## Resume point

Start with TODO 1 and `docs/compatibility-inventory.md`. Keep compatibility optional and explicit, preserve supported schema upgrades, and keep BVP-specific semantics out of Efloud.
