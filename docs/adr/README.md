# Architecture Decision Records (ADRs)

This directory holds project-level Architecture Decision Records for Efloud.

ADRs capture durable rationale behind significant architectural choices whose reasoning would be costly to reconstruct from code diffs alone.

- Design and invariants live in `DESIGN.md`.
- Execution sequencing lives in `PLAN.md`.
- Current state lives in `STATUS.md`.
- ADRs explain why a durable design choice was made and what alternatives were rejected.

## Conventions

### Location

- ADRs live under `docs/adr/`.

### Naming

- File naming: `000N-<kebab-slug>.md`.
- Inside the ADR, use the canonical label `ADR-000N` in the title.

### Template

Each ADR should include:

- title, date, and status (`Proposed`, `Accepted`, or `Superseded`)
- context / problem statement
- decision
- consequences, positive and negative
- alternatives considered

### Lifecycle

- Accepted ADRs remain as historical rationale even after implementation.
- If an ADR is replaced, mark it `Superseded` and link to the newer ADR.
- The index lists only ADR files that actually exist in this repository.

## Index

- `ADR-0007` — Source definitions are immutable content-addressed revisions (`0007-source-definition-revisions.md`)
- `ADR-0008` — Dataset specification identity is distinct from frozen membership identity (`0008-dataset-specification-and-membership-identity.md`)
- `ADR-0009` — Frozen snapshot membership, detached exports, and local maintenance (`0009-dataset-export-and-repository-maintenance.md`)
- `ADR-0010` — Adopt a clean-break public API and remove alpha compatibility (`0010-clean-break-public-api.md`)
