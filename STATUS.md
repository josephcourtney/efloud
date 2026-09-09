# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Run the final repository-wide quality, packaging, architecture, compatibility-removal, and coverage gates before external BVP acceptance.

## Recently completed

- The clean package-root API is implemented: one explicit `Repository` type with `create`/`open` and read/write modes, `Engine`, typed built-in sources, `SyncRequest`/`SyncResult`, `DatasetSpec`/`Dataset`/`DatasetManifest`, and public error categories.
- Canonical planner, executor, adapters, policy, validation, datasets, maintenance, derived work, and collection execution operate on typed sources, requests, runtime configuration, exact inputs, declared outputs, and narrow repository capabilities.
- Backwards compatibility has been removed rather than isolated: `src/efloud/compat/`, deprecated `sync(cfg)`, alpha config/source/manifest/fanout/derived/query/status/state/adoption modules, compatibility projections/materialization helpers, aliases, and TTL index types are deleted.
- Historical repository schemas are no longer migrated in place. Only the current schema is opened; non-current or non-empty unversioned metadata databases fail explicitly.
- The post-compatibility authoritative mutation surface has been audited and recorded in `docs/durability-audit.md`, covering repository opening, acquisition, validation, snapshots, derivation, dataset freeze, cleanup, and recovery.
- Every supported repository mutation path is coordinated by the writer lease; standalone byte staging now checks the active lease before touching blob storage.
- Destructive cleanup recomputes reachability under the writer lease and fails closed on SQLite/foreign-key errors, semantic identity/source/snapshot corruption, and missing or corrupt reachable content while preserving validation-only and provenance history.
- Recovery changes only abandoned `running` runs/operations to `failed`; failure-injection coverage verifies interrupted blob/metadata and snapshot boundaries, retry after recovery, writer exclusion, crash-release behavior, grace periods, and dry-run selection reasons.
- Missing producer metadata is rejected instead of receiving a synthetic legacy producer, and unbounded source snapshot history uses `limit=None` through internal repository/storage contracts as well as the public facade.
- Dataset acceptance now runs through `repo.datasets`, `Dataset`, and `DatasetManifest`: `resolve` is read-only, `freeze` persists the same resolved identity, and frozen membership/source-definition evidence remains stable after newer acquisition and source revisions.
- Snapshot-backed public dataset acceptance verifies incomplete coverage cannot imply absence or satisfy complete-snapshot reproducibility, including empty selections.
- Detached exports are verified after the source repository is removed; missing/corrupt repository or export content fails verification without acquisition or metadata mutation.
- Export acceptance covers unsafe paths (including `.`), reserved-layout collisions, concurrent destination creation, copy/symlink isolation from authoritative content, and strict explicit-reflink behavior.
- CI now creates a reflink-enabled XFS filesystem and exercises native Linux `FICLONE` through public `Dataset.export(strategy="reflink")` plus native `renameat2(RENAME_NOREPLACE)` publication.
- `docs/dataset-manifest-v1.md` specifies the portable manifest envelope, stable identity formulas, detached observation/source-revision evidence, path rules, and byte verification. A standard-library-only subprocess validates a real export without importing Efloud or reading SQLite.
- Detached `DatasetManifest.verify()` returns `False` for missing/non-directory roots as well as unavailable or corrupt members; public export/planning consistently surface manifest-layout failures as `ExportError`.
- Transport staging, HTTP cache, and rate-limit state live under the non-authoritative `.efloud-runtime` operational root rather than legacy top-level mirror/cache layout fields.
- Installed-wheel contracts assert removed compatibility modules are absent and unimportable; architecture contracts describe only the surviving canonical modules.
- Canonical derived-index validity is derivation-key based; repository-backed index tests cover deterministic reuse and parameter-sensitive invalidation.
- Public temporal selection uses timezone-aware `datetime`; dataset resolve/freeze/export and detached manifest verification remain exposed through the clean facade.
- README and installed-wheel packaging examples use only the clean API, with an end-to-end regression covering acquire → freeze → export → detached verify → read-only reopen.
- Substantive dataset/export acceptance run #200 at `cecda63f8409b7ff2f16d1f0ff56a24645d6e9bf` passed the full Python 3.12 and 3.13 suites, Python 3.14 `just check` with checkout cleanliness, and the native Linux XFS export-primitives job; subsequent commits only finalize TODO/STATUS/CHANGELOG bookkeeping.

## Pre-cutover baseline

- 186 tests passed on Python 3.12.12, 3.13.9, and 3.14.0 before the clean API work.
- Ruff lint/format, ty, whitespace, and all 7 import contracts passed.
- Coverage was 86.16% lines / 62.80% branches.
- Failure injection covered interrupted writes, retry/recovery, concurrent processes, and export publication races.

## Remaining gaps

- Final repository-wide packaging, architecture/import, installed-package compatibility-removal, coverage-comparison, and release evidence still need to be run and recorded against the committed clean-break implementation.
- External BVP acceptance remains after the Efloud release gates are finalized.

## Resume point

Start with TODO 1: run the complete final repository gates, compare coverage to the pre-cutover baseline with deleted compatibility code/tests accounted for separately, and record the resulting release evidence.
