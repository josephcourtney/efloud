# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Make CI prove a clean committed checkout

Files: `.github/workflows/ci.yml`, `justfile`, formatter/linter configuration, affected source/tests

- run the repository formatter and lint autofixes locally and commit all resulting changes
- change the Python 3.14 CI job from mutating `just format` / `just lint` execution to non-mutating checks (`just check` or equivalent explicit check-only recipes)
- add an explicit clean-tree assertion after quality checks if needed so CI cannot hide mutations
- keep full pytest coverage on Python 3.12, 3.13, and 3.14 while those versions remain supported

Acceptance: a clean checkout passes without modification; deliberately unformatted or autofixable code fails CI instead of being repaired by CI.

## 2. Establish explicit SQLite schema migrations

Files: `src/efloud/sqlite_metadata.py`, metadata-store tests, migration fixtures

- replace additive schema initialization as the only upgrade mechanism with ordered schema migrations
- define the next schema version needed for source-definition history
- add upgrade tests from every currently supported historical schema version
- verify existing repository content, observations, snapshots, datasets, provenance, and validation evidence survive upgrades unchanged
- reject unknown future schema versions clearly

Acceptance: every supported old repository upgrades deterministically to the current schema and retains semantic state; migrations are testable independently of fresh database creation.

## 3. Preserve historical source-definition meaning

Files: repository models/store/schema, executor source registration, repository/query tests; ADR under `docs/adr/` if needed

- decide and document source-definition revision identity and lifecycle before schema implementation
- persist immutable/reconstructable source-definition revisions rather than overwriting the sole definition for a source ID
- associate new observations/source snapshots with the source-definition revision needed to interpret them
- ensure changes to URL, role, tags, include/exclude filters, mirror configuration, or integrity expectations do not rewrite historical meaning
- expose the relevant revision through repository query/dataset-facing APIs without depending on compatibility manifests

Acceptance: after a source configuration change, old and new repository evidence can each be interpreted against the definition active when it was produced.

## 4. Clarify dataset identity before expanding selectors

Files: `src/efloud/datasets.py`, dataset metadata/schema tests; ADR under `docs/adr/` if needed

- define the relationship among dataset specification/resolution identity, exact observation-membership identity, and content-equivalence identity
- decide how two different specifications that resolve to identical members are stored and retrieved
- prevent `Repository.resolve_dataset()` from silently retaining whichever definition happened to be persisted first for an otherwise-colliding identity
- add focused tests for identical membership from distinct specifications and identical content from distinct observations

Acceptance: dataset identity/equivalence behavior is explicit, deterministic, documented, and ready for Phase 14 temporal/snapshot selectors.

## 5. Verify Phase 13 as one migration boundary

- run the non-mutating Python 3.14 quality gate in GitHub Actions
- run the full test suite on every supported Python minor version
- verify migration tests, historical source-definition tests, and dataset-identity tests are green
- verify no compatibility manifest/state file becomes authoritative again

Acceptance: Phase 13 passes CI from a clean checkout and leaves the repository ready for `PLAN.md` Phase 14 without unresolved persistence/identity decisions.
