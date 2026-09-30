# TODO.md

Purpose: ephemeral, execution-level tasks for the experimental Git/git-annex redesign. Completed items are removed rather than retained as history.

## 1. Validate the completed Phase A characterization slice

- [ ] Run the new focused semantic characterization tests on the exact branch head.
- [ ] Run `just check` on the exact branch head.

Acceptance: the characterization map in `docs/git-annex-redesign-gap-audit.md` is backed by a locally passing exact commit.

## 2. Complete the minimal infrastructure ports

- [ ] Add a Git-oriented `TreeStore` protocol only for tree/commit operations actually required by the first replacement slice.
- [ ] Define the internal semantic `Catalog` capability needed by orchestration/resolution rather than exposing the writer.
- [ ] Refactor only the first consumers necessary to prove dependency direction; avoid speculative protocol methods.
- [ ] Add pure fakes for semantic unit tests where they remove dependency on filesystem CAS/tree implementations.

Acceptance: the first semantic slice no longer imports the filesystem CAS or custom tree implementation directly.

## 3. Complete the Git/git-annex proof

- [ ] Detect the tested Git/git-annex capabilities needed by Efloud; define a minimum version only if concrete incompatibility requires one.
- [ ] Implement/test content get/drop and drop/reacquire without changing Efloud semantic identity.
- [ ] Determine which ordinary URL registration/acquisition operations can be delegated cleanly to git-annex and test only those supported paths.
- [ ] Add Git tree/commit operations required to replace custom tree identity without using Git identity as `DatasetId`.
- [ ] Cover unusual filenames, interruption/retry, corruption, and destructive-operation failure behavior on real filesystem primitives.

Acceptance: real integration tests prove Git/git-annex can satisfy the target content/tree contracts before `ContentRef` or repository persistence is cut over.
