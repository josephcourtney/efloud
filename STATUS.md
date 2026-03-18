# STATUS.md

File Purpose: Current project state, progress against `DESIGN.md`, and continuity notes for the next development pass.

Rules:

- Keep this short-horizon and high-signal.
- Do not use this as a task list (`TODO.md`) or execution strategy (`PLAN.md`).
- Remove stale historical detail as soon as it stops helping continuity.

## Current Focus

Phase 0 is complete. Phase 1 (Introduce Internal Runtime Seams) has not yet started.

Immediate entry point for Phase 1: `src/efloud/sync.py`. The goal is to introduce
internal orchestration boundaries without changing observable behavior. See PLAN.md
Phase 1 for scope.

## Current State Summary

The implementation is pre-Phase 1 alpha. `sync(cfg)` is the primary entrypoint and is
fully monolithic. All HTTP, rsync, derived task, manifest recording, and state update
logic lives directly in `sync.py`. No Runtime, Planner, Executor, or adapter
abstractions exist yet.

Recent work:
- `status.py` and `source_results.py` migrated to value-based `SourceKind` comparisons;
  test coverage added for foreign-but-value-compatible enum types. `sync.py` was not
  updated and still uses identity comparisons in `build_http_caches`,
  `run_http_phase`, and `run_rsync_phase`.
- `policy.py` already uses value-based comparisons throughout (`source.kind.value`).

Known gaps:
- `sync.py` identity comparisons (`is`, `in {...}`) for `SourceKind` are inconsistent
  with the fix applied elsewhere; these are the first concrete Phase 1 fix.
- `_kind_name` helper is duplicated in `status.py` and `source_results.py`; no shared
  utility location exists yet.
- `ManifestRecorder` lives in `sync.py` but is not behind a formal interface.
- No protocol adapters; transport dispatch is inline branching in `sync.py`.
- Artifact identity is fully path-based; no `ArtifactRef` or `ArtifactRecord` types.
- The Phase 0 compatibility inventory is implicit in the codebase (`__init__.py` is the
  canonical export list; manifest schema is `models.py`; query targets are
  `query_targets.py`) but was not produced as a standalone document.

## Continuity Notes

The current uncommitted diff (DESIGN.md, PLAN.md, `source_results.py`, `status.py`,
test) represents the Phase 0 completion work. It should be committed before Phase 1
work begins.

The SourceKind value-comparison fix in `sync.py` is the natural first Phase 1 task; it
mirrors the change already applied to `status.py` / `source_results.py` and is
low-risk. After that, introduce the `Runtime` seam and reduce `sync.py`'s direct
orchestration responsibility.
