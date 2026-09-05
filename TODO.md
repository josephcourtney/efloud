# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Run and repair the combined Phase 9/10 quality gate

Files: repository-wide as required

- run `.venv/bin/ruff format src/ tests/`
- run `.venv/bin/ruff check src/ tests/`
- run `.venv/bin/ty check src/ tests/`
- run focused blob-store and authority-cutover tests, including
  `tests/unit/test_blob_store_contract.py` and
  `tests/unit/test_phase10_authority_cutover.py`
- run existing repository/query/status/manifest/engine/fanout/rsync compatibility
  tests
- run `.venv/bin/pytest`
- verify public imports for `AdoptionResult` and `adopt_existing_store`

Acceptance: the normal project quality gate passes from a clean checkout, and no
canonical Engine/query/status behavior changes when generated compatibility
manifest and mirror-state files are deleted or replaced with invalid claims.

## 2. Define the Phase 11 planning vocabulary

Files: new planning module plus Engine/orchestration tests

- define `SyncRequest`, `SyncPlan`, `PlanningDecision`, and typed operation records
- keep source definitions declarative and free of live clients/sessions
- make plan identity/output deterministic for the same request and repository state
- represent selected sources/scopes, refresh decisions, dependencies, and dry-run
  intent explicitly
- do not persist operations merely because a plan is inspected

Acceptance: identical repository state plus request yields an equivalent plan, and
planning performs no acquisition or authoritative mutation.

## 3. Formalize source adapter capabilities

Files: adapter protocol/registry plus HTTP/REST/rsync/collection implementations

- define `SourceAdapter` and `AdapterDescriptor`
- make inventory/enumeration and fetch/materialization capabilities explicit
- pass stable adapter identity/version into `ProducerRef`
- separate source configuration from runtime cache/client/transport instances
- register built-in adapters directly; defer external entry-point discovery until a
  concrete plugin requirement exists

Acceptance: adding a built-in source protocol does not require changing repository
semantics or generic reconciliation code.

## 4. Introduce an explicit executor over typed plans

Files: executor module, Engine integration, concurrency/failure tests

- execute the exact `SyncPlan` produced by planning
- make operation dependencies explicit
- add bounded concurrency where independent operations can run safely
- preserve operation/run lifecycle closure on failures and cancellation
- make dry-run render/use the same plan while executing no acquisition
- keep `Engine` as the small convenience facade

Acceptance: execution order/dependencies and concurrency limits are observable and
testable, and dry-run differs from execution only by whether planned operations are
performed.

## 5. Replace transient manifest-shaped acquisition evidence

Files: current `acquisition.py`, `RepositorySyncRecorder`, derived/fanout adapters,
compatibility serializers

- replace the Phase 10 transient compatibility-shaped acquisition result with typed
  adapter/executor results
- record repository evidence directly from typed results
- keep compatibility manifest construction exclusively in repository serializers
- remove same-run manifest-shaped coordination from adapter APIs where typed inputs
  can express the dependency instead

Acceptance: the canonical Engine ingestion path no longer needs an in-memory legacy
manifest shape even transiently; compatibility JSON exists only at explicit export
or inspection boundaries.
