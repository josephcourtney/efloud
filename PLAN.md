# PLAN.md

Purpose:

- define the remaining execution strategy for the repository-centered architecture in `DESIGN.md`
- sequence work so each milestone leaves Efloud runnable, testable, and easier for downstream consumers to use
- record ordering constraints and transitional considerations without duplicating architectural rationale or project status

This file intentionally omits the completed migration history. Detailed historical evolution belongs in git history; current completion state belongs in `STATUS.md`.

## Execution Rules

- `DESIGN.md` is authoritative for intended architecture and invariants.
- Significant durable decisions that are costly to reverse should be captured in ADRs before implementation.
- Prefer deleting or isolating obsolete migration mechanisms over extending dual implementations.
- Do not introduce destructive maintenance until repository identity, migration, and coordination semantics are explicit.
- Keep consumer-facing reads acquisition-free.
- Keep the default implementation local and service-free.
- Add protocols, storage backends, plugin discovery, or distributed features only from concrete requirements.
- CI must verify the committed checkout; it must not make a dirty checkout pass by formatting or autofixing it in-place.

## Remaining Strategy

The remaining work is ordered around the consumer boundary first, then cleanup and maintenance:

1. harden persistence, source-definition history, identity semantics, and CI verification
2. complete immutable dataset selection and temporal/coherence policies
3. export and materialize immutable datasets safely for consumers that should not need Efloud internals
4. collapse the public/API compatibility perimeter to one canonical implementation path
5. add repository audit, coordination, recovery, and safe non-historical garbage collection
6. add historical retention/pruning only if a concrete storage requirement justifies it
7. add new source adapters only from concrete source requirements
8. keep advanced storage/distribution features deferred until measurements or workflows justify them

## Cross-Phase Invariants

Every phase must preserve these constraints:

- authoritative mutation goes through repository-facing services
- metadata never commits a reference to blob content that is not durably available
- content objects are immutable and identified by digest
- observation identity remains distinct from content identity
- generic content semantics do not depend on local paths or storage keys
- absence requires successful complete coverage of the relevant scope
- source-relative paths are provenance/structure, not content identity
- source configuration changes must not retroactively change the meaning of historical observations
- validation evidence is immutable content evidence and failed required validation does not advance source state
- deterministic derived reuse still records current-run observations and provenance
- frozen datasets remain immutable after later ingestion
- compatibility manifests, mirrors, caches, and materializations are projections or conveniences, never authoritative databases

## Phase 13: Repository And Persistence Hardening

Objective:

- make persisted semantics durable enough to support richer temporal datasets and later destructive maintenance

Ordering constraint:

- complete this phase before expanding dataset selection semantics or implementing GC

Work:

- make the Python 3.14 CI quality job non-mutating and prove that the committed checkout is already formatted/lint-clean
- introduce explicit ordered SQLite schema migrations with upgrade tests from every supported historical schema version
- preserve source-definition history instead of overwriting the only definition for a source ID
- associate historical repository evidence with the source-definition revision required to interpret it reproducibly
- define the identity relationship among dataset resolution/specification, exact observation membership, and content equivalence
- record ADRs for source-definition revision semantics and dataset identity semantics if those decisions are not already unambiguous in `DESIGN.md`

Acceptance criteria:

- CI fails rather than silently fixing an unformatted or autofixable checkout
- repositories created under supported older schema versions upgrade deterministically without loss of semantic state
- changing a source URL, role, tags, filters, or integrity expectations does not change the interpretation of historical observations/snapshots
- two dataset specifications that resolve to identical membership have explicitly defined identity/equivalence behavior rather than accidentally sharing whichever definition was persisted first

## Phase 14: Complete Immutable Datasets And Temporal Policies

Objective:

- finish the generic immutable-data boundary required by downstream consumers

Existing foundation to preserve:

- exact/latest/latest-before/latest-all selectors
- frozen exact observation membership
- observation-membership and content-equivalence identities
- read-only artifact open/verify

Work:

- add snapshot-backed selection, including exact source snapshots and latest complete source snapshots where appropriate
- add selection by source, role, and tag using authoritative source-definition revisions
- treat namespace initially as an artifact-key prefix/filter convention unless a concrete requirement justifies first-class namespace metadata
- define temporal resolution against an explicit time basis; use repository observation time as the initial universal basis
- enforce complete-snapshot requirements without inferring absence from partial or failed coverage
- add optional same-run and maximum-observation-skew constraints
- permit datasets to require already-recorded validation evidence without triggering validation during resolution
- implement the dataset specification/membership/content identity model established in Phase 13
- define a versioned deterministic detached dataset manifest/lockfile containing exact members, observation/content IDs, roles, relevant source/snapshot revisions, constraint results, content metadata, and safe logical export paths
- keep BVP catalog/verification parity as an external acceptance fixture using generic Efloud dataset APIs and detached manifests; do not add BVP-specific repository semantics

Acceptance criteria:

- a frozen dataset never changes after newer ingestion
- local repository root or blob placement does not affect semantic dataset identity
- temporal resolution never infers absence from incomplete coverage
- snapshot completeness, same-run, skew, and validation requirements are explicit and testable
- detached dataset metadata is deterministic and sufficient for a downstream consumer to understand exact membership without reading Efloud's SQLite schema
- downstream BVP catalog behavior can be represented through generic Efloud dataset semantics

## Phase 15: Safe Dataset Materialization And Export

Objective:

- provide ordinary filesystem handoff without weakening repository authority or requiring consumers to understand Efloud internals

Work:

- materialize immutable datasets, and exact source snapshots where useful, from repository content
- support `auto`, `reflink`, `copy`, and explicit `symlink` strategies
- make `auto` prefer reflink/CoW and fall back to copy
- do not use hardlinks as the default user-visible strategy
- derive output paths only from explicit safe logical paths in immutable export metadata
- validate path traversal, duplicate paths, and collisions before writing
- build into a temporary sibling tree and atomically publish where the platform permits
- include the versioned detached dataset manifest in every self-contained dataset export

Acceptance criteria:

- deleting or modifying a materialized copy does not affect repository correctness or authoritative CAS content
- materialization rejects path traversal and collisions before publishing partial output
- repeated materialization of the same dataset has deterministic structure and metadata
- a downstream package can consume a detached export without importing Efloud

## Phase 16: Canonical Public API And Migration Cleanup

Objective:

- leave one canonical implementation path and a deliberately small public semantic surface

Work:

- make `Engine` and `Repository` the canonical operational surfaces
- make legacy `sync(cfg)` delegate to canonical orchestration and deprecate or remove it according to compatibility policy
- remove `RepositorySyncRecorder`, transient manifest-import paths, and other migration-only infrastructure when no supported path requires them
- isolate remaining manifest/mirror serializers and inspectors under explicit compatibility code
- replace compatibility-manifest-based materialization helpers with repository/dataset-backed equivalents
- reduce top-level exports to stable semantic APIs plus deliberate adapter/validator extension contracts
- identify and deprecate redundant TTL index, cache/status, mirror-resolution, and provenance compatibility abstractions where repository-native equivalents exist

Acceptance criteria:

- one canonical ingestion path and one authoritative state model remain
- no internal feature depends on compatibility JSON as a database
- compatibility code is isolated and removable
- the documented top-level API contains semantic interfaces rather than migration-history implementation details

## Phase 17: Repository Maintenance, Audit, Recovery, And Safe GC

Objective:

- make repository maintenance safe without yet deleting valid historical state

Work:

- add repository-wide writer/maintenance coordination so destructive maintenance cannot race acquisition, validation staging, or metadata mutation
- define recovery/reporting for abandoned `running` runs and operations after crashes
- implement repository audit/fsck over metadata references, blob availability, digest verification, source snapshots, datasets, and provenance edges
- compute and explain reachability across observations, trees, datasets, provenance, validations, and materializations
- detect CAS blobs left by interrupted metadata commits and content rows with no semantic references
- implement dry-run-first cleanup with explicit grace periods and reason codes for every proposed deletion
- preserve validation-only content evidence and all content required by existing historical metadata

Acceptance criteria:

- maintenance cannot run destructively while a writer holds the repository
- audit reports missing/corrupt blobs and dangling metadata without mutating the repository
- dry-run explains every proposed deletion
- safe GC removes only true orphan/unreferenced storage objects and cannot invalidate any existing dataset, observation, snapshot, provenance edge, or validation record

## Phase 18: Historical Retention And Pruning (Contingent)

Objective:

- reclaim valid historical state only if a concrete storage/retention requirement justifies doing so

This is not an automatic continuation of safe GC.

Work, if activated:

- define explicit retention roots and policies for observations, source snapshots, runs, datasets, derivations, and validation evidence
- define deletion semantics so metadata never remains while required content has been intentionally removed
- preserve retained datasets and required transitive provenance
- provide dry-run impact reports before destructive pruning
- make policy decisions reversible where practical and protect recent state with grace periods

Acceptance criteria:

- pruning cannot invalidate retained datasets or retained provenance
- every removed historical object is attributable to an explicit retention policy
- no surviving metadata claims unavailable intentionally-pruned content

## Phase 19: Additional Source Adapters (Use-Case Driven)

Objective:

- add protocols only when an actual upstream requirement cannot be represented by existing adapters

Work, when required:

- implement the concrete adapter against existing `SourceAdapter`, `SourceInventory`, validation, reconciliation, and repository contracts
- add protocol-specific source evidence without adding protocol-specific repository semantics
- add external entry-point discovery only when a real external-plugin requirement appears
- treat Git as one candidate adapter, not a mandatory architectural milestone

Acceptance criteria for any new adapter:

- no repository-schema special case is required for the protocol
- membership/absence semantics use the normalized coverage model
- artifacts from the new source mix freely with existing dataset semantics

## Phase 20: Deferred Advanced Features

These remain design targets rather than current implementation commitments.

### Recursive Merkle Trees

Consider recursive/versioned Merkle trees only if measurements show flat tree snapshot or diff costs are material. Historical tree identities must remain readable.

### Mutable References

Add human-friendly mutable refs only if required. Refs point to immutable targets, use compare-and-swap/generation semantics, and may become GC roots without participating in immutable identity.

### Replica And Availability Tracking

Add replica records only if content must be offloaded or shared across stores. Mutable upstream locators are not replicas unless exact content identity is established.

### Alternate Blob Backends

Implement alternate stores only from concrete requirements. The semantic `BlobStore` contract must remain sufficient without turning the local core into a general storage framework.

## Verification Strategy

Every active phase should be completed only when:

- the non-mutating Python 3.14 quality gate passes in CI
- the complete test suite passes across every Python minor version declared by `project.requires-python`
- migration tests cover any metadata schema change
- repository invariants receive focused regression tests
- downstream acceptance fixtures exercise generic Efloud APIs rather than importing private repository implementation details
