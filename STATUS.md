# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Implement the clean-break public API in ADR-0010 and `docs/api.md`, migrate canonical execution to it, then delete all alpha compatibility and historical schema support. `docs/compatibility-inventory.md` is a deletion inventory, not a support matrix.

## Recently completed

- Repository-centered acquisition, immutable content/observations, provenance, validation, snapshots, datasets, detached exports, writer leases, audit/cleanup, and crash recovery are implemented on the canonical path.
- Collection/derived execution use repository-native contexts; compatibility outputs are already separated from canonical Engine execution.
- ADR-0010 fixes the target boundary: one explicitly opened repository type, `Engine` orchestration, open source/adapter identity, one `SyncResult`, `DatasetSpec`/`Dataset`/`DatasetManifest`, and no alpha compatibility requirement.

## Pre-cutover verification

- 186 tests passed on Python 3.12.12, 3.13.9, and 3.14.0.
- Ruff lint/format, ty, whitespace, and all 7 import contracts passed.
- Coverage was 86.16% lines / 62.80% branches.
- Failure injection covered interrupted writes, retry/recovery, concurrent processes, and export publication races.

These are baseline figures; compatibility deletion will intentionally remove code/tests before final verification.

## Remaining gaps

- The implementation/package root still expose transitional source/config, read-only/view, repository-writer, dataset selector/materializer, and planner/executor types.
- Compatibility/projection/presentation modules, adoption/aliases, TTL caches, and historical schema migrations still need deletion.
- Durability, detached export, Linux publication, quality gates, remote CI, and BVP acceptance must be rerun after the cutover.

## Resume point

Start with TODO 1: land enough of the new source/repository/result/dataset API to give canonical internals a stable target, then complete TODO 2 and delete compatibility under TODO 3 before acceptance work.
