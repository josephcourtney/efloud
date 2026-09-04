# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Route collection enumeration through `SourceInventory`

Files: `src/efloud/fanout.py`, `src/efloud/repository_derived.py`, `src/efloud/inventory.py`, `src/efloud/reconciliation.py`, tests

- convert collection/fanout enumeration into `SourceInventory` with explicit complete/partial coverage
- map collection item identities to deterministic logical artifact keys and locators
- pass collection membership through `reconcile_inventory()` instead of collection-specific absence logic
- preserve current item observations, request metadata, materialization paths, and source snapshots

Acceptance: HTTP, rsync, and collection enumeration all use the same inventory/reconciliation semantics, and a complete collection enumeration can prove removed items absent without a collection-specific repository model.

## 2. Remove `REST_BASE` reconciliation special cases

Files: `src/efloud/fanout.py`, `src/efloud/repository_derived.py`, `src/efloud/repository_recording.py`, tests

- separate collection enumeration from per-item retrieval
- use generic reconciliation decisions for new/changed/unchanged/absent collection members
- ensure failed or partial enumeration never establishes absence
- retain compatibility manifest/result serialization only at the compatibility boundary

Acceptance: `RestBaseFanoutTask` behavior is expressible through ordinary source inventory, artifact observation, absence, and source-snapshot records.

## 3. Run and repair the Phase 6/7 quality gate

Files: repository-wide as required

- run `.venv/bin/ruff format src/ tests/`
- run `.venv/bin/ruff check src/ tests/`
- run `.venv/bin/ty check src/ tests/`
- run focused inventory/reconciliation and rsync tests
- run `.venv/bin/pytest`
- verify the new public inventory/reconciliation imports and existing rsync behavior

Acceptance: the normal project quality gate passes from a clean checkout without regressions in existing HTTP, REST, collection/fanout, or rsync behavior.
