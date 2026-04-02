# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references (files/classes/tests) and explicit acceptance criteria.

## Phase 1: Close the Rsync Handoff Gap, Then Resume Runtime Seams

### 1. Thread first-class rsync port configuration through runtime planning

Files: `src/efloud/registry.py`, `src/efloud/sync.py`, `tests/unit/test_fanout_and_sync.py`

- add `port: int | None` to `SourceDefinition`
- pass `source.port` into `RsyncMirrorConfig` in `run_rsync_phase`
- add a sync-phase regression test that proves a configured port survives from source definition to rsync command construction

Acceptance: a `SourceDefinition(port=...)` reaches the constructed rsync command; existing tests pass

### 2. Complete SourceKind value-comparison migration in `sync.py`

Files: `src/efloud/sync.py`, `tests/unit/test_fanout_and_sync.py`

- replace the remaining identity comparisons in `build_http_caches`, `run_http_phase`, and `run_rsync_phase` with value-based checks
- consider consolidating `_kind_name` from `status.py` / `source_results.py` into a shared utility once the comparisons are aligned
- add a dry-run regression using a foreign-but-value-compatible `SourceKind` through the `sync()` path

Acceptance: `sync.py` no longer relies on enum identity; existing tests pass

### 3. Extract `ManifestRecorder` to its own module

Files: `src/efloud/sync.py` → `src/efloud/manifest_recorder.py`

- move `ManifestRecorder`, `_http_freshness_record`, `_http_manifest_entry`, `_rsync_manifest_entry`, `_rsync_freshness_record` out of `sync.py`
- keep `sync.py` focused on orchestration rather than manifest payload construction

Acceptance: `sync.py` no longer defines manifest-entry construction; all existing tests pass

### 4. Introduce internal `Runtime` skeleton

Files: `src/efloud/runtime.py` (new)

- define a `Runtime` dataclass with placeholder fields for planner and executor
- `sync()` instantiates a `Runtime` and delegates the main orchestration call to it
- `sync()` continues to expose the same `SyncResult` and manifest/state outputs

Acceptance: `sync(cfg)` behavior unchanged; `runtime.py` exists and is reachable; at least one test exercises the delegation path
