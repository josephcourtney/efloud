# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Experimental clean-break rewrite delegating generic storage/tree/workflow infrastructure to Git, git-annex, optional DataLad, and downstream DVC while preserving Efloud's source-observation and semantic-dataset model.

## Baseline

- Branch: `experiment/git-annex-redesign`.
- Starting main commit: `53023cf9482e7a2cfca20a0f71f5cb05483ba1b8`.
- Current main already contains declarative `efloud.toml` and canonical lock/signing work; that boundary is being reused.
- The branch has a working annex-oriented internal `ContentStore` and a real `GitAnnexContentStore` integration slice.
- The legacy filesystem CAS, custom tree identity, transfer/runtime code, and derivation execution still exist and are targeted for replacement/deletion after the corresponding replacement boundaries are proven.

## Verified evidence

- macOS arm64 local environment: Git 2.56.0 and git-annex 10.20260901.
- The real `tests/integration/test_git_annex_content_store.py` tests passed locally against git-annex.
- The repository-location-independent dataset identity fix was applied and its focused test passed locally.
- The user reported `just check` passing through branch commit `0231dfb851b1f62f1e8d4f5cc1fb959ec6ec0ec7`.
- New Phase A characterization/audit changes after that commit are not yet locally validated on their exact head.

## Decisions under test

- git-annex owns content identity/custody/integrity/logistics.
- Git owns filesystem-tree revision identity.
- Efloud owns artifact/source identity, inventories/coverage/absence, observations, semantic/source validation evidence, temporal resolution, semantic dataset identity, locks, and provenance explanation.
- Public `Repository` remains the semantic facade; internal catalog/content/tree ownership is split.
- DataLad is optional; DVC is downstream and never a core dependency.
- No compatibility shims are added on this pre-1.0 branch.

## Current state

- Phase A semantic characterization is mapped in `docs/git-annex-redesign-gap-audit.md`.
- Two previously implicit requirements now have focused tests: multi-source source/role evidence and independence of `DatasetId` from detached export layout.
- Legacy-only CAS/tree/transport/derivation test families are classified for deletion or replacement rather than preservation.
- Persisted concepts are classified as semantic keep, Git/git-annex-derived/replaced, or delete.
- Phase A remains pending only the exact-head local validation recorded in `TODO.md`.

## Immediate gaps

- Validate the exact branch head with the focused characterization tests and `just check`.
- Add the minimal Git `TreeStore` and semantic `Catalog` boundaries required by the first replacement slice.
- Finish real git-annex proof for get/drop/reacquire, URL delegation where appropriate, unusual filenames, corruption, and interruption/retry.
- Do not change `ContentRef` or delete the legacy CAS until those boundaries are proven.

## Resume point

Continue with `TODO.md`: validate Phase A on the exact head, then complete the minimal infrastructure ports and remaining Git/git-annex proof before the content-identity cutover.
