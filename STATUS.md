# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Close dataset and detached-export acceptance through the clean public API, with particular attention to native Linux CoW/no-replace publication and generic downstream manifest consumption.

## Recently completed

- The clean package-root API is implemented: one explicit `Repository` type with `create`/`open` and read/write modes, `Engine`, typed built-in sources, `SyncRequest`/`SyncResult`, `DatasetSpec`/`Dataset`/`DatasetManifest`, and public error categories.
- Canonical planner, executor, adapters, policy, validation, datasets, maintenance, derived work, and collection execution operate on typed sources, requests, runtime configuration, exact inputs, declared outputs, and narrow repository capabilities.
- Backwards compatibility has been removed rather than isolated: `src/efloud/compat/`, deprecated `sync(cfg)`, alpha config/source/manifest/fanout/derived/query/status/state/adoption modules, compatibility projections/materialization helpers, aliases, and TTL index types are deleted.
- Historical repository schemas are no longer migrated in place. Only the current schema is opened; non-current or non-empty unversioned metadata databases fail explicitly.
- The post-compatibility authoritative mutation surface has been audited and recorded in `docs/durability-audit.md`, covering repository opening, acquisition, validation, snapshots, derivation, dataset freeze, cleanup, and recovery.
- Every supported repository mutation path is coordinated by the writer lease; standalone byte staging now checks the active lease before touching blob storage.
- Destructive cleanup recomputes reachability under the writer lease and fails closed on SQLite/foreign-key errors, semantic identity/source/snapshot corruption, and missing or corrupt reachable content while preserving validation-only and provenance history.
- Recovery changes only abandoned `running` runs/operations to `failed`; failure-injection coverage verifies interrupted blob/metadata and snapshot boundaries, retry after recovery, writer exclusion, crash-release behavior, grace periods, and dry-run selection reasons.
- Missing producer metadata is rejected instead of receiving a synthetic legacy producer, and unbounded source snapshot history now uses `limit=None` through internal repository/storage contracts as well as the public facade.
- Transport staging, HTTP cache, and rate-limit state live under the non-authoritative `.efloud-runtime` operational root rather than legacy top-level mirror/cache layout fields.
- Installed-wheel contracts assert removed compatibility modules are absent and unimportable; architecture contracts describe only the surviving canonical modules.
- Canonical derived-index validity is derivation-key based; repository-backed index tests cover deterministic reuse and parameter-sensitive invalidation.
- Public temporal selection uses timezone-aware `datetime`; dataset resolve/freeze/export and detached manifest verification remain exposed through the clean facade.
- README and installed-wheel packaging examples use only the clean API, with an end-to-end regression covering acquire → freeze → export → detached verify → read-only reopen.
- The durability branch passed the full Python 3.12 and 3.13 suites and the Python 3.14 non-mutating `just check` gate before milestone bookkeeping was finalized.

## Pre-cutover baseline

- 186 tests passed on Python 3.12.12, 3.13.9, and 3.14.0 before the clean API work.
- Ruff lint/format, ty, whitespace, and all 7 import contracts passed.
- Coverage was 86.16% lines / 62.80% branches.
- Failure injection covered interrupted writes, retry/recovery, concurrent processes, and export publication races.

## Remaining gaps

- Dataset resolve/freeze/export semantics, detached handoff, incomplete-snapshot behavior, path/publication safety, and generic manifest consumption must be closed through the public API.
- Native Linux reflink and atomic no-replace publication still require acceptance on a filesystem that supports those primitives; unsupported CI filesystems skip only the explicit reflink case rather than silently falling back.
- Final packaging/coverage/release gates and external BVP acceptance remain after dataset/export acceptance.

## Resume point

Start with TODO 1: audit the existing dataset/export integration coverage against the public `repo.datasets`/`Dataset`/`DatasetManifest` API, then add only the missing acceptance cases and supported-Linux publication coverage.
