# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references (files/classes/tests) and explicit acceptance criteria.

## Phase 1: Introduce Internal Runtime Seams

### 1. Complete SourceKind value-comparison migration in `sync.py`

Files: `src/efloud/sync.py`

- `build_http_caches` (line 287): replace `source.kind not in {SourceKind.HTTP, SourceKind.REST, SourceKind.REST_BASE}` with value-based comparison
- `run_http_phase` (line 325): replace `source.kind not in {SourceKind.HTTP, SourceKind.REST}` with value-based comparison
- `run_http_phase` (line 341): replace `source.kind is SourceKind.REST` with value-based comparison
- `run_rsync_phase` (line 382): replace `source.kind is not SourceKind.RSYNC` with value-based comparison
- Consider consolidating `_kind_name` from `status.py` / `source_results.py` into a shared utility (e.g., `src/efloud/registry.py` or a new `src/efloud/kind_utils.py`) and importing it in all three files

Acceptance: existing tests pass; add a dry-run test using a `ForeignSourceKind` through the `sync()` path (see `test_summary_health_status_query.py` for pattern)

### 2. Extract `ManifestRecorder` to its own module

Files: `src/efloud/sync.py` → `src/efloud/manifest_recorder.py`

- Move `ManifestRecorder`, `_http_freshness_record`, `_http_manifest_entry`, `_rsync_manifest_entry`, `_rsync_freshness_record` out of `sync.py`
- `sync.py` imports and uses `ManifestRecorder` from the new module

Acceptance: `sync.py` no longer defines manifest-entry construction; all existing tests pass

### 3. Introduce internal `Runtime` skeleton

Files: `src/efloud/runtime.py` (new)

- Define a `Runtime` dataclass with placeholder fields for planner and executor
- `sync()` instantiates a `Runtime` and delegates the main orchestration call to it
- `sync()` continues to expose the same `SyncResult` and manifest/state outputs

Acceptance: `sync(cfg)` behavior unchanged; `runtime.py` exists and is reachable; at least one test exercises the delegation path
