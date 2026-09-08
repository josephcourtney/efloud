# ADR-0008: Dataset specification identity is distinct from frozen membership identity

Date: 2026-09-08

Status: Accepted

## Context

The existing immutable dataset model intentionally identifies a dataset by its exact resolved observation membership, with a second content identity for byte-equivalent membership. Before Phase 13, the persisted dataset row also stored one unresolved/intensional `DatasetDefinition` under that membership ID.

Two different definitions can legitimately resolve to the same exact observations. Because the metadata table was keyed only by membership identity, whichever definition was persisted first silently became the definition returned later. That made specification provenance insertion-order dependent even though dataset membership itself was deterministic.

## Decision

The existing `DatasetId` remains the identity of exact frozen observation membership, including member roles. This preserves the established semantic meaning and avoids changing durable dataset IDs merely because selector syntax differs.

`content_identity` remains the equivalence identity based on logical membership plus immutable content IDs, allowing independently observed but byte-identical datasets to compare equal by content.

Phase 13 adds `DatasetSpecificationId`, derived from canonical JSON of the complete intensional `DatasetDefinition`. Every persisted membership retains all known specifications that resolved to it.

When a membership has multiple specifications:

- `Repository.resolve_dataset(definition)` returns the requested definition and its specification ID;
- persisted membership records retain the union of known specifications;
- generic lookup by `DatasetId` selects a canonical specification deterministically by specification ID, never by insertion order;
- query APIs expose the complete specification set so no definition is silently lost.

## Consequences

Positive:

- durable `DatasetId` semantics remain backward compatible;
- different selection recipes that produce identical frozen membership are distinguishable and retained;
- membership equivalence, specification equivalence, and content equivalence answer three different questions explicitly;
- canonical dataset lookup is deterministic across insertion order and repository reopen.

Negative:

- one dataset membership can now have multiple valid intensional definitions;
- callers that care about how a membership was selected must use `DatasetSpecificationId`, not `DatasetId` alone;
- legacy v2 dataset rows are migrated as memberships with one known specification.

## Alternatives considered

- **Include the definition in `DatasetId`:** rejected because it would change the established meaning of dataset identity and make equivalent frozen memberships different datasets solely because of selector syntax.
- **Keep one definition per membership:** rejected because it loses valid provenance and makes retrieval insertion-order dependent.
- **Use content identity as the dataset ID:** rejected because independently observed identical bytes may carry materially different observation/provenance identity.
- **Introduce a separate relational resolution table immediately:** deferred; the versioned specification envelope is sufficient for present scale and preserves a clean migration path if query requirements later justify normalization.
