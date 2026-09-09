# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Delete all remaining alpha compatibility and historical schema support now that canonical execution uses the clean typed source/repository/request contracts. `docs/compatibility-inventory.md` is a deletion inventory, not a support matrix.

## Recently completed

- The clean package-root API is implemented: one explicit `Repository` type with `create`/`open` and read/write modes, `Engine`, typed built-in sources, `SyncRequest`/`SyncResult`, `DatasetSpec`/`Dataset`/`DatasetManifest`, and public error categories.
- Canonical planner, executor, adapters, policy, validation, queries, datasets, and maintenance now operate on typed `Source`, `SyncRequest`, `EngineRuntime`, and narrow repository capabilities rather than `EngineConfig`, `SourceDefinition`/`SourceKind`, merged manifests, or broad `RepositoryView` contexts.
- Adapter dispatch is keyed by stable namespaced adapter identity; canonical derived tasks use exact inputs and declared outputs; collection execution separates inventory/enumeration from typed item acquisition and generic reconciliation.
- Canonical derived-index validity is derivation-key based; TTL-backed indexing is compatibility-only.
- Import contracts prevent canonical execution modules from depending back on alpha config/manifest/task modules.
- Public temporal selection uses timezone-aware `datetime`; unbounded snapshot history uses `limit=None`; dataset resolve/freeze/export and detached manifest verification remain exposed through the clean facade.
- README and installed-wheel packaging examples use only the clean API, with an end-to-end regression covering acquire → freeze → export → detached verify → read-only reopen.

## Pre-cutover baseline

- 186 tests passed on Python 3.12.12, 3.13.9, and 3.14.0 before the clean API work.
- Ruff lint/format, ty, whitespace, and all 7 import contracts passed.
- Coverage was 86.16% lines / 62.80% branches.
- Failure injection covered interrupted writes, retry/recovery, concurrent processes, and export publication races.

## Remaining gaps

- `src/efloud/compat/`, deprecated `sync(cfg)`, compatibility manifest/state/query/status projection code, adoption/aliases, TTL caches, alpha derived/fanout contracts, and historical schema migrations remain until TODO 1 deletion.
- Durability, detached export, Linux publication, final quality gates, remote CI, and BVP acceptance must be re-verified on the reduced post-compatibility mutation surface.

## Resume point

Start with TODO 1: execute `docs/compatibility-inventory.md` as a finite deletion plan, then re-run durability and detached-export acceptance against the compatibility-free runtime.
