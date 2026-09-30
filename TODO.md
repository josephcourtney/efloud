# TODO.md

Purpose: ephemeral, execution-level tasks for the experimental Git/git-annex redesign. Completed items are removed rather than retained as history.

## 1. Complete the Git/git-annex proof

- [ ] Detect the tested Git/git-annex capabilities needed by Efloud; define a minimum version only if concrete incompatibility requires one.
- [ ] Implement/test content get/drop and drop/reacquire without changing Efloud semantic identity.
- [ ] Determine which ordinary URL registration/acquisition operations can be delegated cleanly to git-annex and test only those supported paths.
- [ ] Cover unusual filenames, interruption/retry, corruption, and destructive-operation failure behavior on real filesystem primitives.

Acceptance: real integration tests prove Git/git-annex can satisfy the target content contract before `ContentRef` or repository persistence is cut over.

## 2. Prepare the first persistence cutover

- [ ] Define the exact mapping between portable semantic content identity and opaque git-annex keys without making annex layout/location part of semantic identity.
- [ ] Replace the first filesystem-CAS consumer only after the corresponding annex behavior is covered by real integration tests.
- [ ] Keep detached manifests portable and independently verifiable; do not require Git, git-annex, SQLite, or repository layout knowledge to validate exported bytes.

Acceptance: the first cutover removes one legacy storage dependency without introducing a second content authority or changing dataset identity semantics.
