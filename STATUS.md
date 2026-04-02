# STATUS.md

File Purpose: Current project state, progress against `DESIGN.md`, and continuity notes for the next development pass.

Rules:
- Keep this short-horizon and high-signal.
- Do not use this as a task list (`TODO.md`) or execution strategy (`PLAN.md`).
- Remove stale historical detail as soon as it stops helping continuity.

## Current Focus

Rsync transport hardening is complete. The immediate follow-up is to thread
first-class rsync port configuration through `SourceDefinition` and `sync.py`,
then resume Phase 1 runtime-seam work.

## Current State Summary

Alpha transport behavior is materially stronger than the previous baseline.
Rsync now retries transient connect failures, emits live diagnostics during
connect stalls, and supports explicit daemon ports at the transport-config
layer. `sync(cfg)` is still monolithic; no Runtime, Planner, Executor, or
adapter abstractions exist yet.

Recent:
- rsync transport now retries transient connect/socket failures with bounded backoff
- rsync diagnostics now include preflight connectivity checks, retry countdowns, and active connect heartbeat output
- `RsyncMirrorConfig` now supports explicit `port`, but `SourceDefinition` and `run_rsync_phase` do not yet thread that field through the higher-level runtime path
- `status.py` and `source_results.py` already use value-based `SourceKind` comparisons; `sync.py` still has remaining identity checks

Known gaps:
- `SourceDefinition` does not yet expose `port`, so higher-level callers cannot use the new rsync port support end to end
- `sync.py` still relies on `SourceKind` identity comparisons in a few paths
- `_kind_name` helper duplicated in `status.py` and `source_results.py`
- `ManifestRecorder` in `sync.py` is not behind a formal interface
- No protocol adapters; transport dispatch is inline branching in `sync.py`

## Continuity Notes

Complete the source-definition-to-runtime rsync port handoff first; it is the
smallest remaining gap in the recent transport work. After that, finish the
`sync.py` value-comparison cleanup and continue with the `Runtime` seam.
