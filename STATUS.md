# STATUS.md

File Purpose: Current project state, progress against `DESIGN.md`, and continuity notes for the next development pass.

Rules:
- Keep this short-horizon and high-signal.
- Do not use this as a task list (`TODO.md`) or execution strategy (`PLAN.md`).
- Remove stale historical detail as soon as it stops helping continuity.

## Current Focus

Rsync transport hardening for large PDB mirrors is complete. The immediate
follow-up is to continue decomposing `sync.py` orchestration seams (manifest
writer/runtime split) and to reduce repeated remote-discovery overhead for
high-cardinality path syncs.

## Current State Summary

Alpha transport behavior is materially stronger than the previous baseline.
Rsync now retries transient connect failures, emits live diagnostics during
connect stalls, supports explicit daemon ports end-to-end, and handles large
PDB mmCIF syncs via shard-prefiltered path updates. `sync(cfg)` remains
monolithic; no Runtime, Planner, Executor, or adapter abstractions exist yet.

Recent:
- rsync now reports transfer-phase counters (handled/total files, transferred files, bytes, rate) plus idle-since-last-output timing
- rsync heartbeat progress bars now reflect timeout countdown semantics
- mirror-state nodes now persist file/dir counts and manifests include source/subtree integrity counts
- `pdb_mmcif` now uses path-sharded sync with remote bucket discovery (`--list-only`) and prefiltering of non-existent remote buckets
- missing remote mmCIF bucket directories are normalized to skipped shard results instead of source-fatal errors
- normal runtime output now uses a compact aggregate shard-status line for `pdb_mmcif`; detailed per-shard transport chatter remains available in debug logging mode

Known gaps:
- `sync.py` still combines orchestration, path-preparation policy, and manifest shaping in one module
- remote bucket discovery currently runs per sync invocation and is not cached across runs
- compact shard progress currently exists only for `pdb_mmcif`; no equivalent aggregation path exists yet for other high-cardinality rsync sources
- `_kind_name` helper remains duplicated in `status.py` and `source_results.py`
- `ManifestRecorder` in `sync.py` is not behind a formal interface
- No protocol adapters; transport dispatch is inline branching in `sync.py`

## Continuity Notes

Next pass should extract manifest payload building from `sync.py`, then isolate
source/path preparation policy behind a small helper boundary. If remote bucket
listing remains a measurable cost, introduce a short-TTL local cache for
`pdb_mmcif` bucket discovery keyed by remote root and port.
