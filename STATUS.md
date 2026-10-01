# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Milestone E of the experimental clean-break rewrite: finish deletion of the replaced custom tree persistence, then continue into transfer/derivation removal.

## Baseline

- Branch: `experiment/git-annex-redesign`.
- Starting main commit: `53023cf9482e7a2cfca20a0f71f5cb05483ba1b8`.
- Current main already contains declarative `efloud.toml` and canonical lock/signing work; that boundary is being reused.
- The experiment has internal `ContentStore`, `TreeStore`, and `Catalog` ports; none are package-root API.
- The legacy filesystem CAS is deleted. Generic transfer/runtime code, obsolete SQLite tree methods, and derivation execution remain replacement/deletion targets.

## Verified evidence

- macOS arm64 local environment: Git 2.56.0 and git-annex 10.20260901.
- Real git-annex integration tests pass for content-key calculation/ingest, deduplication, presence, read, verification, URL registration, drop, and key-level reacquisition.
- Real Git integration tests pass for canonical tree identity, nested/unusual portable paths, modes/symlinks, exact blob reads, changed-tree identity, and retained linear commit history.
- Repository-location-independent `DatasetId` behavior is covered and passes.
- Phase A semantic characterization is complete, including explicit multi-source evidence and export-layout-independent dataset identity tests.
- The internal `Catalog` boundary excludes physical tree/materialization state and has a pure `MemoryCatalog` semantic fake.
- Exact clean branch commit `f790499a0f417cf32caec4d6bc060a6dae9d4282` passed `just check` locally: syntax, format, lint, type checking, import contracts, full tests, and coverage.

## Decisions under test

- git-annex owns content custody/integrity/logistics; annex keys and physical locations are infrastructure evidence, not dataset identity.
- Git owns filesystem-tree revision identity; Git tree/commit IDs are not `DatasetId`.
- Efloud owns artifact/source identity, inventories/coverage/absence, observations, semantic/source validation evidence, temporal resolution, semantic dataset identity, locks, and provenance explanation.
- Public `Repository` remains the semantic facade; internal catalog/content/tree ownership is split.
- DataLad is optional; DVC is downstream and never a core dependency.
- No compatibility shims are added on this pre-1.0 branch.

## Current state

- Phase A is complete and locally validated.
- Repository content custody is cut over to git-annex; the filesystem CAS implementation is deleted.
- Maintenance enumerates annex custody through `ContentStore` and performs key-level drops only after semantic reachability checks.
- Key reacquisition and URL registration use git-annex directly; integration coverage proves corruption/drop/reacquisition preserves semantic `ContentId`.
- Semantic Repository persistence is typed against `Catalog`; the pure in-memory catalog supports ordinary semantic behavior.
- Tree snapshot reads/writes are now routed through `GitTreeStore`. A canonical Git blob preserves exact semantic `TreeEntry` data and the Git tree object ID is persisted as `SourceSnapshot.tree_id`.
- Read-only repositories decode the same Git tree projection without mutating repository state.
- Clean schema version 4 removes `tree_snapshots` and `tree_entries`; `source_snapshots.tree_id` records the Git tree identity directly.
- Maintenance validates referenced Git tree projections instead of recomputing the deleted custom Efloud tree hash.
- The old SQLite `record_tree()` / `tree_entries()` methods are now unreachable but still need physical deletion from `sqlite_metadata.py`.

## Immediate gaps

- Delete the unreachable SQLite tree methods/imports and add a direct clean-schema assertion that the old tree tables are absent.
- Locally verify the schema-4 Git tree cutover with `just fix` and then `just check` on a clean exact commit.
- Finish git-annex interruption/retry behavior proof.
- Delete generic transfer/cache/transport machinery superseded by git-annex.
- Remove generic derivation execution from core while preserving the minimal derived-artifact provenance model.

## Resume point

Continue with `TODO.md`: delete the remaining SQLite tree implementation and verify the Git tree cutover before starting the transfer/execution deletion tranche.
