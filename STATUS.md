# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Experimental clean-break rewrite delegating generic storage/tree/workflow infrastructure to Git, git-annex, optional DataLad, and downstream DVC while preserving Efloud's source-observation and semantic-dataset model.

## Baseline

- Branch: `experiment/git-annex-redesign`.
- Starting main commit: `53023cf9482e7a2cfca20a0f71f5cb05483ba1b8`.
- Current main already contains declarative `efloud.toml` and canonical lock/signing work; that boundary should be reused.
- Current code still owns a filesystem CAS, custom content IDs/tree identity, generic transfer/runtime code, and derivation execution targeted for replacement.

## Decisions under test

- git-annex owns content identity/custody/integrity/logistics.
- Git owns filesystem-tree revision identity.
- Efloud owns artifact/source identity, inventories/coverage/absence, observations, validation evidence, temporal resolution, semantic dataset identity, locks, and provenance explanation.
- Public `Repository` remains the semantic facade; internal catalog/content/tree ownership is split.
- DataLad is optional; DVC is downstream and never a core dependency.
- No compatibility shims are added on this pre-1.0 branch.

## Immediate gaps

- Complete Phase A characterization mapping and add any missing storage-independent tests.
- Introduce the first narrow infrastructure ports.
- Prove real Git/git-annex repository operations before changing `ContentRef` or deleting the legacy CAS.
- Local `just check` cannot be run from this chat environment because the repository cannot be cloned through the container network; code commits must not be described as validated until run against a local checkout.

## Resume point

Continue with `TODO.md`: finish semantic characterization first, then implement the minimal Git/git-annex command/content-store slice.
