# ADR-0011: Delegate generic storage and workflow infrastructure

- Date: 2026-09-30
- Status: Proposed — experimental branch

## Context

Efloud currently implements several infrastructure concerns in addition to its source-observation and dataset semantics: a filesystem content-addressed store, content hashing and integrity checks, custom tree identity, transfer/runtime machinery, and generic derivation execution.

Those mechanisms are substantial but are not the distinctive part of Efloud. The distinctive model is the separation of logical artifact identity, immutable content identity, observations through time, explicit absence backed by coverage evidence, semantic validation, temporal resolution, and immutable path-independent datasets.

The experiment on `experiment/git-annex-redesign` tests whether mature external tools can own the generic infrastructure without weakening those semantics.

## Decision

For this experiment:

1. Git and git-annex are foundational infrastructure.
   - git-annex owns immutable content keys, byte custody, byte-integrity verification, content presence/location, retrieval, dropping, replication, and special-remotes.
   - Git owns filesystem-tree revision identity and human-reviewable small metadata.
2. DataLad is optional. It may distribute or compose Git/git-annex dataset trees but must not define Efloud artifact, observation, snapshot, or dataset identity.
3. DVC is downstream. It may consume Efloud locks/materialized datasets and own computational DAGs, generated outputs, metrics, plots, and experiments. Core Efloud must not import or require DVC.
4. Efloud continues to own:
   - stable logical artifact identity;
   - source-definition identity;
   - inventories, scope, coverage, and explicit absence;
   - observations and acquisition evidence;
   - semantic/source validation evidence;
   - temporal resolution;
   - cross-source dataset composition;
   - deterministic path-independent dataset identity;
   - provenance/explanation of dataset membership.
5. The public `Repository` remains the durable semantic facade required by the package API. Internally it is split so semantic catalog state, content logistics, and filesystem-tree history have distinct owners. A catalog implementation must never become a second byte store.
6. The existing declarative `efloud.toml` and canonical lock machinery are retained and adapted rather than replaced by a parallel configuration system.
7. This is a pre-1.0 clean break. Once a replacement is proven, obsolete production infrastructure is deleted rather than hidden behind compatibility aliases or shims. A one-shot repository migration may read old state, but normal runtime code does not preserve old repository schemas or APIs.

## Required invariants

- Logical artifact identity is independent of paths, content, and storage location.
- One content reference denotes immutable exact bytes and is backed by a git-annex key.
- Physical absence of bytes does not invalidate historical semantic evidence.
- Observations are append-only historical evidence.
- Absence is authoritative only when successful enumeration establishes sufficient coverage.
- Dataset membership and `DatasetId` are independent of filesystem layout, Git commit, annex UUID, and current storage location.
- Git commits may represent source or materialized trees but are not semantic dataset IDs.
- DataLad must remain optional and DVC must remain downstream.
- Metadata must never commit a reference to content whose annex identity was not successfully established.

## Consequences

### Positive

- Removes a large custom storage, transfer, tree-versioning, and workflow surface.
- Concentrates Efloud on source observation, evidence, temporal semantics, and dataset resolution.
- Reuses git-annex's mature content logistics and Git's tree/history model.
- Gives downstream computation a narrow deterministic handoff rather than expanding Efloud into a workflow system.

### Negative

- Git and git-annex command behavior becomes part of Efloud's operational correctness.
- Transaction boundaries now span SQLite/catalog state and external Git/git-annex operations.
- Integration tests must exercise real Git/git-annex repositories and failure recovery.
- Some current APIs and persistent fields become invalid and will be removed.

## Alternatives considered

### Keep the custom CAS and add git-annex only as a remote

Rejected for the experiment because it preserves two authoritative content-identity/logistics systems and therefore does not test the main simplification hypothesis.

### Make DataLad the core repository abstraction

Rejected because DataLad's dataset/tree identity does not replace Efloud's logical artifact, temporal observation, coverage, or semantic dataset identities.

### Move computation into Efloud

Rejected because generic computational DAGs, experiments, metrics, and generated outputs are better handled downstream by tools such as DVC.

## Validation

This ADR is accepted for the main line only if the experimental branch demonstrates the acceptance criteria in `docs/git-annex-redesign-gap-audit.md` and preserves Efloud's semantic characterization tests while deleting the replaced production subsystems.
