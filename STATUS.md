# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Re-verify durability and maintenance correctness on the reduced, compatibility-free mutation surface before closing detached export and final release acceptance.

## Recently completed

- The clean package-root API is implemented: one explicit `Repository` type with `create`/`open` and read/write modes, `Engine`, typed built-in sources, `SyncRequest`/`SyncResult`, `DatasetSpec`/`Dataset`/`DatasetManifest`, and public error categories.
- Canonical planner, executor, adapters, policy, validation, datasets, maintenance, derived work, and collection execution operate on typed sources, requests, runtime configuration, exact inputs, declared outputs, and narrow repository capabilities.
- Backwards compatibility has been removed rather than isolated: `src/efloud/compat/`, deprecated `sync(cfg)`, alpha config/source/manifest/fanout/derived/query/status/state/adoption modules, compatibility projections/materialization helpers, aliases, and TTL index types are deleted.
- Historical repository schemas are no longer migrated in place. Only the current schema is opened; non-current or non-empty unversioned metadata databases fail explicitly.
- Old terminal-status aliases and legacy producer fallback metadata are rejected rather than normalized into canonical records.
- Transport staging, HTTP cache, and rate-limit state live under the non-authoritative `.efloud-runtime` operational root rather than legacy top-level mirror/cache layout fields.
- Installed-wheel contracts assert removed compatibility modules are absent and unimportable; architecture contracts describe only the surviving canonical modules.
- Canonical derived-index validity is derivation-key based; repository-backed index tests cover deterministic reuse and parameter-sensitive invalidation.
- Public temporal selection uses timezone-aware `datetime`; unbounded snapshot history uses `limit=None`; dataset resolve/freeze/export and detached manifest verification remain exposed through the clean facade.
- README and installed-wheel packaging examples use only the clean API, with an end-to-end regression covering acquire → freeze → export → detached verify → read-only reopen.

## Pre-cutover baseline

- 186 tests passed on Python 3.12.12, 3.13.9, and 3.14.0 before the clean API work.
- Ruff lint/format, ty, whitespace, and all 7 import contracts passed.
- Coverage was 86.16% lines / 62.80% branches.
- Failure injection covered interrupted writes, retry/recovery, concurrent processes, and export publication races.

## Remaining gaps

- Durability and maintenance behavior must be re-audited after removal of the compatibility mutation/projection surface.
- Detached export, Linux publication, final quality gates, remote CI, and BVP acceptance must be re-verified on the compatibility-free runtime.

## Resume point

Start with TODO 1: enumerate the remaining authoritative mutation paths and re-run crash/recovery/cleanup acceptance against only the clean repository API.
