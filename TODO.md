# TODO.md

Purpose: ephemeral, execution-level tasks for the experimental Git/git-annex redesign. Completed items are removed rather than retained as history.

## 1. Complete Phase A semantic characterization

- [ ] Map existing tests to each characterization item in `docs/git-annex-redesign-gap-audit.md`.
- [ ] Add focused tests for any missing cases: repeated unchanged observation, changed content, complete-coverage absence, partial/failed inventory unknown state, interrupted acquisition, validation history, exact/latest/latest-before resolution, multi-source resolution, deterministic manifest/`DatasetId`, and layout independence.
- [ ] Classify legacy-only tests that assert CAS paths, custom tree hashes, transfer internals, or generic derivation execution for deletion rather than preservation.
- [ ] Classify persisted fields as semantic `keep`, Git/git-annex-derived, or delete.

Acceptance: every retained semantic requirement is asserted without depending on the legacy storage/tree/transfer implementation.

## 2. Introduce minimal infrastructure ports

- [ ] Add an annex-oriented `ContentStore` protocol without exporting it from the package root.
- [ ] Add a Git-oriented `TreeStore` protocol.
- [ ] Define the internal semantic `Catalog` capability needed by orchestration/resolution rather than exposing the writer.
- [ ] Refactor only the first consumers necessary to prove dependency direction; avoid speculative protocol methods.
- [ ] Add pure fakes for fast unit tests.

Acceptance: the first semantic slice no longer imports the filesystem CAS or custom tree implementation directly.

## 3. Prove Git/git-annex command boundary

- [ ] Centralize subprocess execution and stable error mapping.
- [ ] Detect supported Git/git-annex versions and define a minimum only from tested requirements.
- [ ] Initialize temporary Git/git-annex repositories with a cryptographic content-only backend.
- [ ] Implement/test key calculation/ingest, presence, verification, get/drop, URL registration/acquisition, and Git tree/commit operations using machine-readable output where available.
- [ ] Cover duplicate bytes, unusual filenames, interruption/retry, corruption, and drop/reacquire.

Acceptance: real integration tests prove Git/git-annex can satisfy the target content/tree contracts before `ContentRef` or repository persistence is cut over.
