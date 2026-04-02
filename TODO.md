# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references (files/classes/tests) and explicit acceptance criteria.

## Phase 1: Continue Runtime-Seam Decomposition After Rsync Stabilization

### 1. Extract manifest payload shaping from `sync.py`

Files: `src/efloud/sync.py` → `src/efloud/manifest_recorder.py`, `tests/unit/test_fanout_and_sync.py`

- move `ManifestRecorder`, `_http_freshness_record`, `_http_manifest_entry`, `_rsync_manifest_entry`, and `_rsync_freshness_record` to a dedicated module
- keep call sites in `sync.py` thin and orchestration-focused
- preserve existing manifest schema and compatibility behavior

Acceptance: `sync.py` no longer defines manifest-entry builders; current manifest-related tests pass unchanged

### 2. Introduce a lightweight runtime seam

Files: `src/efloud/runtime.py` (new), `src/efloud/sync.py`, `tests/unit/test_fanout_and_sync.py`

- add a minimal `Runtime` coordinator (dataclass or small class) that owns phase sequencing
- make `sync()` delegate to the runtime coordinator while preserving `SyncResult` semantics
- keep current transport behavior and manifest outputs identical

Acceptance: `sync(cfg)` behavior is unchanged from caller perspective; at least one test asserts runtime delegation

### 3. Cache discovered rsync shard inventories

Files: `src/efloud/sync.py`, `tests/unit/test_fanout_and_sync.py`

- add a short-TTL local cache for `pdb_mmcif` remote bucket discovery (`rsync --list-only`)
- key cache entries by remote root + port so discovery is reused across repeated sync invocations
- keep fallback behavior unchanged when discovery fails

Acceptance: repeated `pdb_mmcif` sync runs avoid redundant list-only discovery within cache TTL; tests cover hit/miss/fallback paths
