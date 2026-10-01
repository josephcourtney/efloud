# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Milestone D of the experimental clean-break rewrite: complete git-annex-aware maintenance after the Repository content-custody cutover.

## Baseline

- Branch: `experiment/git-annex-redesign`.
- Starting main commit: `53023cf9482e7a2cfca20a0f71f5cb05483ba1b8`.
- Current main already contains declarative `efloud.toml` and canonical lock/signing work; that boundary is being reused.
- The experiment has internal `ContentStore`, `TreeStore`, and `Catalog` ports; none are package-root API.
- The legacy filesystem CAS, custom tree persistence, transfer/runtime code, and derivation execution still exist and remain replacement/deletion targets.

## Verified evidence

- macOS arm64 local environment: Git 2.56.0 and git-annex 10.20260901.
- Real git-annex integration tests pass for content-key calculation/ingest, deduplication, presence, read, and verification.
- Real Git integration tests pass for canonical tree identity, nested/unusual portable paths, modes/symlinks, changed-tree identity, and retained linear commit history.
- Repository-location-independent `DatasetId` behavior is covered and passes.
- Phase A semantic characterization is complete, including explicit multi-source evidence and export-layout-independent dataset identity tests.
- The internal `Catalog` boundary excludes physical tree/materialization state and has a pure `MemoryCatalog` semantic fake.
- Exact branch commit `5db183180de957d01bf472eb1eefdab213d358b8` passed `just check` locally: syntax, format, lint, type checking, import contracts, full tests, and coverage.

## Decisions under test

- git-annex owns content custody/integrity/logistics; annex keys and physical locations are infrastructure evidence, not dataset identity.
- Git owns filesystem-tree revision identity; Git tree/commit IDs are not `DatasetId`.
- Efloud owns artifact/source identity, inventories/coverage/absence, observations, semantic/source validation evidence, temporal resolution, semantic dataset identity, locks, and provenance explanation.
- Public `Repository` remains the semantic facade; internal catalog/content/tree ownership is split.
- DataLad is optional; DVC is downstream and never a core dependency.
- No compatibility shims are added on this pre-1.0 branch.

## Current state

- Phase A is complete and locally validated.
- The initial real Git/git-annex infrastructure proof is complete for ingest/verify and tree/commit operations.
- Repository content custody has now been cut over in production code to the internal git-annex ContentStore; real repository reopen/persistence coverage is present.
- The exact clean branch head passed `just check` after the cutover and read-only custody fixes.
- The first CAS-specific test migration is complete: obsolete blob-store contract tests and filesystem-layout assertions were removed or converted to semantic content assertions; reflink export permissions were corrected so cloned handoff files are independently writable.
- The filesystem CAS implementation has now been deleted. Maintenance enumerates annex custody through the ContentStore and performs key-level drops only after semantic reachability checks.
- The narrow semantic `Catalog` and pure in-memory fake are implemented and locally validated.
- `Repository` still directly owns the broad legacy metadata/blob abstractions; this is now the immediate dependency-cut target.

## Immediate gaps

- Route the remaining semantic repository persistence through `Catalog` and isolate legacy materialization/custom-tree calls.
- Finish git-annex get/reacquire, appropriate URL delegation, corruption, interruption/retry, and destructive-operation failure behavior.
- Locally run the current branch after this maintenance cutover; the GitHub edits in this tranche have not yet been locally verified here.

## Resume point

Continue with `TODO.md`: perform the first `Repository` dependency cut, then finish the remaining real git-annex proof before any content-persistence cutover.
