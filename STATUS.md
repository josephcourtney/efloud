# STATUS.md

File Purpose: Current project state, progress against `DESIGN.md`, and continuity notes for the next development pass.

Rules:
- Keep this short-horizon and high-signal.
- Do not use this as a task list (`TODO.md`) or execution strategy (`PLAN.md`).
- Remove stale historical detail as soon as it stops helping continuity.

## Current Focus

Rsync transport observability for large mirrors is materially improved. The
immediate follow-up is to finish splitting `sync.py` orchestration seams
(manifest/runtime/policy boundaries), and to decide whether path-discovery and
transport telemetry should be generalized beyond the current PDB-heavy rsync
paths.

## Current State Summary

Alpha transport behavior is materially stronger than the previous baseline.
Rsync now retries transient connect failures, emits live diagnostics during
connect stalls, supports explicit daemon ports end-to-end, handles large PDB
mmCIF syncs via shard-prefiltered path updates, and now surfaces more useful
runtime indexing telemetry during long-running file-list phases. Developer
workflow ergonomics also improved through a more composable `just` interface
for lint, format, test, docs, complexity, and coverage commands. `sync(cfg)`
remains monolithic; no Runtime, Planner, Executor, or adapter abstractions
exist yet.

Recent:
- rsync file-list/indexing progress now emits periodic heartbeat updates and
  warns much sooner when the transport remains in `receiving file list`
- rsync runtime telemetry now has hooks for richer local activity reporting
  during long-running transfers
- developer task recipes were consolidated into flag-driven `just` commands for
  linting, formatting, testing, docs, complexity, and coverage
- `just fix` now runs the fast test subset by default
- artifact path canonicalization now normalizes resolved paths more consistently

Known gaps:
- `sync.py` still combines orchestration, path-preparation policy, and manifest shaping in one module
- remote bucket discovery currently runs per sync invocation and is not cached across runs
- compact shard progress currently exists only for `pdb_mmcif`; no equivalent aggregation path exists yet for other high-cardinality rsync sources
- `_kind_name` helper remains duplicated in `status.py` and `source_results.py`
- `ManifestRecorder` in `sync.py` is not behind a formal interface
- no protocol adapters; transport dispatch is inline branching in `sync.py`
- rsync indexing telemetry is still transport-specific and not yet reflected in higher-level normalized status summaries

## Continuity Notes

Next pass should extract manifest payload building from `sync.py`, then isolate
source/path preparation policy behind a small helper boundary. If remote bucket
listing remains a measurable cost, introduce a short-TTL local cache for
`pdb_mmcif` bucket discovery keyed by remote root and port.
observability continues to matter operationally, promote rsync transport
telemetry into a small reusable runtime-status abstraction instead of leaving it
entirely transport-local.
