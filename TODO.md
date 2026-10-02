# TODO.md

Purpose: ephemeral, execution-level tasks for the experimental Git/git-annex redesign. Completed items are removed rather than retained as history.

## 1. Complete the remaining Git/git-annex proof

- [ ] Detect the tested Git/git-annex capabilities needed by Efloud; define a minimum version only if concrete incompatibility requires one.
- [ ] Cover interruption/retry on real filesystem primitives.
- [ ] Remove any remaining tests or documentation that describe the deleted filesystem CAS.

Acceptance: the remaining Git/git-annex behaviors required by Efloud are proven against the supported real implementation.

## 2. Delete replaced acquisition/runtime machinery

- [ ] Remove the obsolete `fetch_to_file` helper and its unit-test branch now that built-in `HttpSource` no longer uses generic HTTP file transport.
- [ ] Keep `RestSource` adapter-assisted where canonical JSON normalization is part of the declared source semantics; remove generic HTTP cache/retry/rate-limit machinery that is no longer needed for custody.
- [ ] Keep `RsyncSource` adapter-assisted for enumeration, scoped coverage, and absence evidence; reduce its transport layer to the smallest temporary-retrieval mechanism required by those semantics.
- [ ] Keep collection enumeration/provider semantics separate from byte custody; item retrieval should delegate to an appropriate source/provider acquisition boundary rather than recreate generic transport logic.

Acceptance: source-specific discovery and evidence remain in adapters, but generic content custody/retry/cache logistics are not reimplemented alongside git-annex.

## 3. Delete generic derivation execution

- [ ] Remove generic derived-task scheduling/execution from core planning and executor paths.
- [ ] Retain only the semantic provenance representation needed to record consumer-supplied transformations and promoted outputs.
- [ ] Delete derivation-only indexes/tests/contracts that no longer describe Efloud's repository role.

Acceptance: Efloud records provenance for transformed data but no longer owns a general workflow executor.
