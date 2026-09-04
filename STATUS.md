# STATUS.md

File Purpose: Current project state, progress against `DESIGN.md`, and continuity notes for the next development pass.

Rules:
- Keep this short-horizon and high-signal.
- Do not use this as a task list (`TODO.md`) or execution strategy (`PLAN.md`).
- Remove stale historical detail as soon as it stops helping continuity.

## Current Focus

The repository-centered architecture is now being implemented. Immutable content
identity and the filesystem blob-store foundation are present; the immediate
next step is to land the SQLite metadata/repository layer and route existing
acquisition results through it without breaking compatibility outputs.

## Current State Summary

Implemented so far:

- stable typed identifiers for sources, artifacts, content, observations, runs,
  operations, snapshots, trees, and datasets
- immutable artifact-observation/content records
- deterministic ID canonicalization
- portable SHA-256 content-addressed filesystem blob storage
- atomic blob installation and content verification

Still pending in the current implementation tranche:

- SQLite metadata persistence
- Repository service facade
- source/tree snapshots and materialization records
- immutable dataset API
- Engine integration with the existing sync pipeline
- repository-focused tests and public exports

Legacy transport, manifest, mirror-state, query, and status behavior remains
unchanged at this point.

## Validation Notes

The new primitive modules were syntax-checked and their content-addressed storage
behavior was exercised locally. The full repository gate cannot be run in the
current environment because the repository cannot be cloned and lint/type
dependencies cannot be downloaded.

## Continuity Notes

Continue the current implementation tranche before starting transport-native
repository commits. The next commit should add SQLite metadata and the semantic
Repository API, followed by dataset and Engine compatibility integration.
