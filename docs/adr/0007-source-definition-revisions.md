# ADR-0007: Source definitions are immutable content-addressed revisions

Date: 2026-09-08

Status: Accepted

## Context

A source ID is intentionally stable, while configuration that gives that source meaning can change: URL, role, tags, include/exclude filters, mirror settings, integrity expectations, and similar fields. The pre-Phase-13 metadata model stored only one mutable JSON definition per source ID. Re-registering a source therefore replaced the definition used to interpret all historical observations and snapshots.

Temporal datasets and later maintenance require historical evidence to remain interpretable without consulting the current configuration or compatibility manifests. At the same time, repositories created before revision tracking cannot truthfully reconstruct which earlier configuration produced each historical observation.

## Decision

Each semantic source definition has an immutable `SourceDefinitionRevisionId` derived from canonical JSON over the stable source ID and complete definition.

The current source record stores a versioned history envelope containing all known immutable revisions and an explicit current revision ID. Re-registering an unchanged definition reuses its revision; changing any semantic definition field creates or reactivates the corresponding revision without deleting earlier revisions.

New source-scoped operations, content observations, absences, and source snapshots record the active revision ID in their ordinary repository evidence/metadata.

The v3 metadata migration wraps the definition currently known for each legacy source as one revision, but it does **not** attach that revision to pre-v3 observations or snapshots. Their historical source-definition revision remains unknown rather than being invented during migration.

## Consequences

Positive:

- source configuration changes cannot retroactively rewrite the meaning of new historical evidence;
- identical definitions have deterministic revision identity;
- revision history remains local, inspectable, and independent of compatibility manifests;
- old repositories upgrade conservatively without fabricated provenance.

Negative:

- pre-v3 evidence may lack an explicit source-definition revision forever;
- the source metadata JSON representation now has an internal versioned envelope rather than containing only the current definition;
- APIs that expose source state must distinguish the current definition from the complete revision history.

## Alternatives considered

- **Overwrite the current definition only:** rejected because historical interpretation becomes configuration-dependent.
- **Copy the complete definition into every observation and snapshot:** rejected because it duplicates large mutable configuration payloads and obscures revision equivalence.
- **Assign the migrated current definition to every old observation:** rejected because that would invent historical provenance.
- **Create a separate relational revision table immediately:** not required for current scale; the versioned envelope preserves the same semantic revision model and can be normalized later through an explicit schema migration if query scale justifies it.
