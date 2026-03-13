# Architecture Decision Records (ADRs)

This directory holds **workspace-level Architecture Decision Records (ADRs)**.

ADRs capture the _durable rationale_ behind significant architectural choices: the “why” that is costly to reconstruct from code diffs alone.

- Design and invariants live in `DESIGN.md`.
- Sequencing/migration lives in `PLAN.md`.
- ADRs explain _why a particular design choice was made_ and what alternatives were rejected.

## Conventions

### Location

- ADRs live under `docs/adr/`.

### Naming

- File naming: `000N-<kebab-slug>.md` (e.g., `0006-renderer-neutral-reportview.md`)
- Inside the ADR, use the canonical label `ADR-000N` in the title.

### Template

Each ADR should include:

- Title, date, and status (`Proposed`, `Accepted`, `Superseded`)
- Context / problem statement
- Decision
- Consequences (positive and negative)
- Alternatives considered

### Lifecycle

- If an ADR is replaced, mark it `Superseded` and link to the newer ADR.

## Index

- `ADR-0001` — Base graph is symbol-level (`0001-symbol-level-graph.md`)
- `ADR-0002` — Canonical NodeId scheme (string IDs) (`0002-canonical-nodeid-scheme.md`)
- `ADR-0003` — Explicit resolution tiers (NONE/SYNTACTIC/SCOPED/DYNAMIC) (`0003-resolution-tiers.md`)
- `ADR-0004` — Compact evidence with deterministic truncation (`0004-evidence-model-and-truncation.md`)
- `ADR-0005` — Projection is the canonical aggregation mechanism (`0005-projection-as-primary-aggregation.md`)
- `ADR-0006` — ReportView as the renderer-neutral presentation model (`0006-renderer-neutral-reportview.md`)
