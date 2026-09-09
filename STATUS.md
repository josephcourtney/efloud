# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Implement the clean-break public API in ADR-0010 and `docs/api.md`, then delete all alpha compatibility rather than preserving it behind adapters. `docs/compatibility-inventory.md` is now a deletion/replacement inventory, not a support matrix.

## Recently completed

- Repository-centered acquisition, immutable observations/content, provenance, validation, snapshots, datasets, detached manifests/exports, writer leases, audit/cleanup, and crash recovery are implemented on the canonical path.
- Canonical collection and derived execution now use repository-native contexts rather than requiring merged manifests.
- Compatibility output generation has already been separated from canonical Engine execution.
- ADR-0010 now fixes the target public boundary: one public repository type with explicit mode, `Engine` orchestration, open source/adapter identity, one `SyncResult`, `DatasetSpec`/`Dataset`/`DatasetManifest`, and no alpha compatibility or historical repository upgrade requirement.

## Verified before the API cutover

- 186 tests passed on Python 3.12.12, 3.13.9, and 3.14.0.
- Ruff lint/format, ty, whitespace checks, and all 7 import-architecture contracts passed.
- Coverage was 86.16% lines / 62.80% branches, above the pre-change baseline.
- Failure injection covered interrupted writes, retry/recovery, concurrent processes, and export publication races.

These figures are the pre-cutover baseline; compatibility deletion will intentionally remove code and tests before final verification is rerun.

## Remaining gaps

- The current implementation and package root still expose transitional alpha API types such as `EngineConfig`, `SourceKind`/`SourceDefinition`, `ReadOnlyRepository`, broad `RepositoryView`, low-level repository writer methods, selector/materializer classes, and detailed planner/executor result types.
- Compatibility modules, old presentation/query helpers, mirror/manifest/state projections, adoption/alias support, TTL caches, and historical schema migrations are still present and must be deleted.
- Final durability, dataset/export, Linux-native publication, complete quality gates, and remote CI must be rerun after the clean break.
- BVP still needs migration to the new public boundary.

## Resume point

Start with TODO 1. Establish enough of the new source/repository/result/dataset API to give canonical internals a stable migration target; then follow TODO 2 and delete compatibility completely under TODO 3 before re-running acceptance.
