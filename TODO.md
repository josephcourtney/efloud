# TODO.md

Purpose: ephemeral, execution-level tasks for the next development work. Completed items are removed rather than retained as history.

## 1. Run final repository gates

- [ ] Run the non-mutating Python 3.14 `just check` gate.
- [ ] Run the complete suite on every Python minor version declared by `project.requires-python`.
- [ ] Run packaging checks and all architecture/import contracts.
- [ ] Compare coverage with the pre-cutover baseline and explain the expected reduction from deleted compatibility tests/code separately from genuine coverage regressions.
- [ ] Verify installed-package root exports and failures for removed compatibility imports.
- [ ] Run remote CI against the committed checkout.
- [ ] Record acceptance evidence for the clean API, compatibility deletion, durability, and detached consumer boundary.

Acceptance: all required checks pass against the committed clean-break implementation.

## 2. Migrate and run external BVP acceptance

Depends on the finalized clean API and generic acceptance above.

- [ ] Replace BVP legacy manifest/tree/fanout imports with Efloud public source/repository/dataset APIs and detached manifests.
- [ ] Verify BVP does not require private SQLite details, compatibility mirrors, old query/status helpers, or legacy extension interfaces.
- [ ] Classify any failure as a generic Efloud capability gap or BVP-specific interpretation before assigning a fix.
- [ ] Keep BVP catalog rules, artifact requirements, domain validation, and naming conventions in BVP.
- [ ] Record the external result separately from Efloud's core release-gate evidence.

Acceptance: BVP implements its workflow through the clean public boundary without reintroducing backwards compatibility into Efloud.
