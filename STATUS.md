# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Phase C of the experimental clean-break rewrite: complete the real Git/git-annex behavior proof before changing semantic content references or repository persistence.

## Baseline

- Main is now the redesign baseline at `fe21a6f5b98fecf474c6021fe20200d256e9f013`.
- Active focused branch: `refactor/legacy-metadata-boundary`.
- Declarative `efloud.toml` and canonical lock/signing work are retained as the project/lock boundary.
- Internal `ContentStore`, `TreeStore`, and `Catalog` ports exist; none are package-root API.
- The legacy filesystem CAS, custom tree persistence, transfer/runtime code, and derivation execution still exist and remain replacement/deletion targets.

## Verified evidence

- macOS arm64 local environment: Git 2.56.0 and git-annex 10.20260901.
- Real git-annex integration tests pass for content-key calculation/ingest, deduplication, presence, read, and verification.
- Real Git integration tests pass for canonical tree identity, nested/unusual portable paths, modes/symlinks, changed-tree identity, and retained linear commit history.
- Repository-location-independent `DatasetId` behavior is covered and passes.
- Phase A semantic characterization is complete, including explicit multi-source evidence and export-layout-independent dataset identity tests.
- The internal `Catalog` boundary excludes physical tree/materialization state and has a pure `MemoryCatalog` semantic fake.
- `Repository` routes semantic source/run/operation/content-description/observation/absence/provenance/validation/snapshot/dataset state through `Catalog`.
- The remaining legacy metadata capability is explicitly limited to materialization-path bookkeeping and custom tree record/read operations.
- A real `Repository` semantic lifecycle is characterized against `MemoryCatalog` without creating SQLite or legacy CAS state.
- Exact branch commit `ff68bf15132d21bc72df23d330c103a0be301d28` passed the focused catalog/repository tests and full `just check`: syntax, format, lint, type checking, import contracts, full tests, and coverage.

## Decisions under test

- git-annex owns content custody/integrity/logistics; annex keys and physical locations are infrastructure evidence, not dataset identity.
- Git owns filesystem-tree revision identity; Git tree/commit IDs are not `DatasetId`.
- Efloud owns artifact/source identity, inventories/coverage/absence, observations, semantic/source validation evidence, temporal resolution, semantic dataset identity, locks, and provenance explanation.
- Public `Repository` remains the semantic facade; internal catalog/content/tree ownership is split.
- DataLad is optional; DVC is downstream and never a core dependency.
- No compatibility shims are added in the pre-1.0 redesign.

## Current state

- Phase A semantic characterization is complete and locally validated.
- Phase B infrastructure boundaries and the first `Repository` dependency cut are complete and locally validated.
- The initial real Git/git-annex proof is complete for ingest/verify and tree/commit operations.
- No production content persistence has been cut over to git-annex yet.

## Immediate gaps

- Finish git-annex get/drop/reacquire behavior without changing Efloud semantic identity.
- Determine which URL registration/acquisition behavior can be delegated cleanly to git-annex.
- Cover corruption, interruption/retry, unusual filename, and destructive-operation failure cases on real filesystem primitives.
- Define the portable semantic-content ↔ annex-key mapping before changing `ContentRef` or deleting the filesystem CAS.

## Resume point

Continue with `TODO.md`: finish the remaining real git-annex proof, then define the semantic-content/annex-key mapping before the first persistence cutover.
