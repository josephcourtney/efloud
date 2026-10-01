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

## 3. Finish and verify the Repository content cutover

- [ ] Run the new Repository/git-annex integration slice on the supported local environment.
- [ ] Add get/drop/reacquire and corruption/interruption coverage to the real git-annex boundary.
- [ ] Rewrite maintenance and repository tests that assert filesystem-CAS paths, orphan blobs, or custom blob corruption mechanics.
- [ ] Remove the remaining production CAS dependency and delete `blob_store.py` once no semantic behavior depends on it.
- [ ] Keep detached manifests portable and independently verifiable; annex custody evidence must not become a requirement for detached byte verification.

Acceptance: Repository content operations are entirely annex-backed, the exact branch head passes the applicable local checks, and the filesystem CAS is no longer a production authority.
