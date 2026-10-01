# TODO.md

Purpose: ephemeral, execution-level tasks for the experimental Git/git-annex redesign. Completed items are removed rather than retained as history.

## 1. Cut `Repository` to the narrow infrastructure ports

- [ ] Route semantic source/run/operation/content-description/observation/absence/provenance/validation/snapshot/dataset persistence through `Catalog` rather than the broad legacy metadata protocol.
- [ ] Isolate the remaining materialization-path and custom-tree calls behind an explicitly temporary legacy metadata capability.
- [ ] Prove at least one repository semantic slice against the pure `MemoryCatalog` so storage-independent behavior no longer requires SQLite/custom tree state.
- [ ] Keep `ContentStore`, `TreeStore`, and `Catalog` internal; do not expose writer/storage implementation details from the package root.

Acceptance: ordinary semantic repository behavior depends on `Catalog`; the remaining legacy metadata dependency is limited to functionality already classified for replacement/deletion.

## 2. Complete the Git/git-annex proof

- [ ] Detect the tested Git/git-annex capabilities needed by Efloud; define a minimum version only if concrete incompatibility requires one.
- [ ] Implement/test content get/drop and drop/reacquire without changing Efloud semantic identity.
- [ ] Determine which ordinary URL registration/acquisition operations can be delegated cleanly to git-annex and test only those supported paths.
- [ ] Cover unusual filenames, interruption/retry, corruption, and destructive-operation failure behavior on real filesystem primitives.

Acceptance: real integration tests prove Git/git-annex can satisfy the target content contract before `ContentRef` or repository persistence is cut over.

## 3. Finish the remaining git-annex behavior proof

- [ ] Cover get/reacquire and URL-backed acquisition through the real git-annex boundary.
- [ ] Cover interruption/retry and destructive-operation failure behavior on real filesystem primitives.
- [ ] Remove any remaining tests or documentation that describe the deleted filesystem CAS.

Acceptance: the remaining content-custody behaviors are proven against real git-annex, and no production or test contract refers to the deleted filesystem CAS.
