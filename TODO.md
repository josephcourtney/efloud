# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Verify the Phase 11 planner/executor/adapter cutover

Files: repository-wide as required

- run `just syntax; just format; just lint; just typecheck; just test`
- verify the adapter contract/runtime split imports cleanly:
  - `efloud.adapters` contains contracts, acquisition result types, and `AdapterRegistry`
  - `efloud.builtin_adapters` owns direct built-in registration
  - HTTP, rsync, and collection runtime implementations remain separate
- verify `tests/unit/test_phase11_planning_execution.py` remains green
- verify existing Engine, repository-output, rsync, collection, and Phase 10 authority-cutover tests remain green
- verify no new inline lint/type suppressions were introduced for the Phase 11 gate repairs

Acceptance: syntax, formatting, lint, typecheck, and the full test suite pass from a clean checkout. Planning remains mutation-free, dry-run persists no run/operations, adapter producer identities are recorded, dependencies/concurrency are explicit, and canonical `Engine` execution does not use the legacy transient manifest importer.

## 2. Begin Phase 12 validation-as-evidence work

Files: validation/repository/inventory/query modules plus focused tests

- inventory all current integrity/validation paths and distinguish:
  - storage integrity against `ContentId`
  - source `IntegrityExpectation` evaluation
  - generic encoding/container validation
  - domain-validator extensions
- define the canonical validator identity/version contract
- ensure validation evidence is keyed by content identity plus validator identity/version
- make required failed integrity expectations prevent successful source advancement
- reuse validation evidence for unchanged content under the same validator version
- expose repository-backed validation evidence through query APIs

Acceptance: validation is immutable repository evidence, unchanged content is not needlessly revalidated by the same validator version, and validation failures never mutate stored content.
