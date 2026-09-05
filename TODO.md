# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Run and repair the Phase 9 quality gate

Files: repository-wide as required

- run `.venv/bin/ruff format src/ tests/`
- run `.venv/bin/ruff check src/ tests/`
- run `.venv/bin/ty check src/ tests/`
- run focused blob-store/content/repository/dataset tests, including
  `tests/unit/test_blob_store_contract.py`
- run existing repository/query/status/manifest/derived-index compatibility tests
- run `.venv/bin/pytest`
- verify a clean checkout can use `FilesystemBlobStore` normally and the pathless
  test store without requiring `path_for()`

Acceptance: the normal project quality gate passes without regressions, and generic
repository/content behavior has no dependency on a local blob path or backend
storage locator.

## 2. Inventory remaining Phase 10 authoritative legacy reads

Files: sync/orchestration, source result/status/freshness helpers, manifest/state
compatibility modules, tests

- identify every internal read of canonical/timestamped manifests, mirror-state
  files, and mirror filesystem rescans
- classify each as authoritative control-flow state, explicit compatibility export,
  or diagnostic-only inspection
- map every authoritative read to an existing repository query or a concrete
  repository API that still needs to be added
- preserve explicit compatibility serializers but prevent new internal consumers
  from depending on their output

Acceptance: every remaining legacy-state read has a named repository-backed
replacement and compatibility-only reads are clearly separated.

## 3. Cut current-state/freshness/status decisions over to repository state

Files: source-result/status/policy/resolution helpers and repository query services

- derive current source/artifact state from observations, absences, snapshots, runs,
  operations, validations, and materializations
- derive freshness/change evidence from repository snapshot/operation evidence rather
  than generated manifests
- remove control-flow fallbacks that consult compatibility JSON when equivalent
  repository evidence exists
- keep consumer-visible compatibility output unchanged where parity is required

Acceptance: deleting generated manifests and mirror-state exports cannot change
internal source-state, freshness, status, or query decisions.

## 4. Remove manifest merge from targeted-sync memory

Files: sync/planning compatibility path, repository source/snapshot APIs, tests

- preserve untouched source/artifact state through repository history rather than
  merging prior manifest entries into a new manifest
- ensure partial/targeted runs only advance scopes actually observed
- regenerate the compatibility manifest from repository state after the run
- add parity coverage for targeted syncs with untouched sources

Acceptance: a targeted sync remembers untouched authoritative state with no prior
manifest available, and the regenerated compatibility manifest still presents the
expected complete view.

## 5. Add conservative existing-store adoption

Files: repository adoption/import boundary and tests

- recognize existing retained content/materializations without destructive moves
- import only evidence that can be established from existing files/state
- do not invent acquisition provenance, observations, completeness, or absence
- make repeated adoption idempotent

Acceptance: an existing store can be adopted without reacquisition or relocation,
while uncertain historical facts remain explicitly unknown rather than fabricated.
