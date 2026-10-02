# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Milestone E of the experimental clean-break rewrite: delete generic acquisition/runtime and derivation machinery now that content custody, Catalog persistence, and tree identity have been cut over.

## Baseline

- Branch: `experiment/git-annex-redesign`.
- Starting main commit: `53023cf9482e7a2cfca20a0f71f5cb05483ba1b8`.
- Current main already contains declarative `efloud.toml` and canonical lock/signing work; that boundary is being reused.
- The experiment has internal `ContentStore`, `TreeStore`, and `Catalog` ports; none are package-root API.
- The legacy filesystem CAS and custom SQLite tree persistence are deleted. Generic acquisition/runtime code and derivation execution remain replacement/deletion targets.

## Verified evidence

- macOS arm64 local environment: Git 2.56.0 and git-annex 10.20260901.
- Real git-annex integration tests pass for content-key calculation/ingest, deduplication, presence, read, verification, URL registration, drop, key-level reacquisition, direct byte-preserving HTTP custody, and stable local-file custody.
- Real Git integration tests pass for canonical tree identity, nested/unusual portable paths, modes/symlinks, exact blob reads, changed-tree identity, retained linear commit history, and tree survival after explicit Git garbage collection.
- Repository-location-independent `DatasetId` behavior is covered and passes.
- Phase A semantic characterization is complete, including explicit multi-source evidence and export-layout-independent dataset identity tests.
- The internal `Catalog` boundary excludes physical tree/materialization state and has a pure `MemoryCatalog` semantic fake.
- The LocalSource direct-custody tranche passed the full local `just check` gate on 2026-10-02.

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
- Tree snapshot reads/writes are routed through `GitTreeStore`. A canonical Git blob preserves exact semantic `TreeEntry` data and the Git tree object ID is persisted as `SourceSnapshot.tree_id`.
- Git tree snapshots are retained by Git history rather than left as unreachable loose objects.
- Read-only repositories decode the same Git tree projection without mutating repository state.
- Clean schema version 4 removes `tree_snapshots` and `tree_entries`; `source_snapshots.tree_id` records the Git tree identity directly.
- Maintenance validates referenced Git tree projections instead of recomputing the deleted custom Efloud tree hash.
- Byte-preserving built-in `HttpSource` acquisition now delegates URL custody directly to git-annex; no HTTP staging copy is retained.
- Built-in `LocalSource` no longer creates a runtime staging copy. `GitAnnexContentStore.ingest_path()` first snapshots caller-owned bytes into Efloud-controlled temporary storage, derives the key from that exact snapshot, and transfers those bytes into annex custody.
- `RestSource` remains adapter-assisted because canonical JSON normalization is source interpretation rather than byte custody.
- The generic `fetch_to_file` helper is no longer used by production acquisition; only an obsolete combined transport unit-test branch still references it.

## Immediate gaps

- Delete the obsolete `fetch_to_file` helper together with its unit-test branch without disturbing the rsync coverage currently colocated in that test module.
- Finish git-annex interruption/retry behavior proof.
- Reduce REST HTTP runtime support to what canonical JSON acquisition actually requires.
- Reduce rsync/collection acquisition to the smallest adapter-assisted retrieval semantics that git-annex cannot replace.
- Remove generic derivation execution from core while preserving the minimal derived-artifact provenance model.

## Resume point

Delete the obsolete generic HTTP byte-fetch test/helper pair, then audit the remaining HTTP cache/retry/rate-limit machinery against the narrower `RestSource` requirement.
