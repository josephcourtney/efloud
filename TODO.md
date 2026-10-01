# TODO.md

Purpose: ephemeral, execution-level tasks for the experimental Git/git-annex redesign. Completed items are removed rather than retained as history.

## 1. Finish the Git tree cutover

- [ ] Delete the now-unreachable `SQLiteMetadataStore.record_tree()` / `tree_entries()` implementation and its obsolete tree-model imports.
- [ ] Verify the schema-4 tree cutover with the complete local quality gate.

Acceptance: Git is the only durable tree representation; SQLite stores only the Git tree identity on source snapshots and no custom tree rows remain.

## 2. Complete the remaining Git/git-annex proof

- [ ] Detect the tested Git/git-annex capabilities needed by Efloud; define a minimum version only if concrete incompatibility requires one.
- [ ] Cover interruption/retry on real filesystem primitives.
- [ ] Remove any remaining tests or documentation that describe the deleted filesystem CAS.

Acceptance: the remaining Git/git-annex behaviors required by Efloud are proven against the supported real implementation.

## 3. Delete replaced execution machinery

- [ ] Classify each built-in source acquisition path as native git-annex, special-remote, or adapter-assisted temporary retrieval.
- [ ] Delete generic transfer/cache/retry machinery superseded by git-annex while preserving source-specific discovery/authentication.
- [ ] Remove generic derivation execution from core while retaining the minimal provenance representation required for consumer-supplied transformations.

Acceptance: production has one content backend, one tree identity mechanism, and no general workflow executor owned by Efloud.
