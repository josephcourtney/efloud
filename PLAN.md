# PLAN.md

Purpose:

- sequence implementation of the repository-centered architecture in `DESIGN.md`
- preserve current acquisition behavior while moving authority from mirrors and
  JSON manifests into the repository
- define phase boundaries that leave the package runnable and testable after
  each migration step
- provide a clear integration path for downstream users such as BVP

Rules:

- `DESIGN.md` is authoritative for architecture and invariants; this file defines
  implementation order
- prefer replacement and deletion of obsolete mechanisms over permanent dual
  abstractions
- keep existing HTTP, REST, collection/fanout, and `rsync` acquisition working
  throughout the migration
- do not make existing mirror or manifest state destructive during migration
- preserve deterministic behavior and test each phase before depending on it
- add compatibility exports where needed, but do not let compatibility formats
  remain authoritative internally
- do not implement deferred replica/ref/Merkle complexity before concrete scale or
  workflow requirements justify it

## Strategy

The migration is organized around one change in authority and one normalization
boundary:

```text
current

transports -> files/mirrors -> manifests/state -> queries

                         becomes

source adapters -> SourceInventory / acquisition evidence
                         |
                         v
                   reconciliation
                         |
                         v
                    Repository
                         |
              metadata + immutable blobs
                         |
          +--------------+---------------+
          |              |               |
       queries        datasets       compatibility
                                    manifests/views
```

The repository must become complete and trustworthy before the old manifest and
mirror-state mechanisms are fully demoted to compatibility views.

The remaining implementation order is deliberately:

1. normalize enumeration, coverage, integrity expectations, and reconciliation
   across source types
2. migrate collection/fanout through that normalized source model
3. make producer identity, operation lifecycle, deterministic derivations, and
   persistent indexes first-class repository concepts
4. remove local-filesystem assumptions from the generic blob-store contract
5. complete the repository-authority cutover for all internal reads and
   compatibility exports
6. formalize planner/executor/adapter/policy interfaces around the proven
   semantics
7. complete validation, temporal dataset policies, retention, and GC
8. add Git and additional source types from concrete use cases
9. remove transitional infrastructure
10. add safe materializations/views and only then optional advanced features

## Cross-Phase Invariants

Every phase must preserve these constraints:

- authoritative new mutation goes through a repository-facing service
- metadata must never commit a reference to blob content that is not durably
  available
- content objects are immutable and identified by digest
- generic content semantics never depend on a local path or storage key
- repeated observation of unchanged bytes must not duplicate content
- an observation must remain distinct from content identity
- absence requires successful complete inventory coverage of the relevant scope
- upstream change tokens and integrity expectations are not content identity
- source-relative paths are retained as provenance/structure, not used as
  content identity
- deterministic derived reuse must still record current-run observations and
  provenance
- no consumer-facing read API may implicitly trigger acquisition
- compatibility manifests, mirrors, and caches may be regenerated from
  authoritative state once cutover occurs
- the default implementation remains local and service-free

## Phase 0: Freeze The Compatibility Perimeter

Status: substantially complete.

Objective:

- establish the exact behavior that must survive the authority migration

Acceptance criteria remain:

- every current authoritative read/write path has a planned repository-backed
  replacement
- representative current outputs can detect migration drift
- no retained source data must be moved or deleted to start the migration

## Phase 1: Introduce The Minimal Runtime Seam

Status: superseded by the transitional `Engine` + repository-recording seam.

The exact `Runtime` extraction originally described here is no longer required.
The architectural requirement is satisfied when acquisition can be recorded
through repository-facing services without transport code depending on SQLite or
manifest authority.

## Phase 2: Define Repository Primitives And Storage Contracts

Status: complete for the initial repository model; blob-store cleanup is deferred
to Phase 9 below.

Established concepts include typed source/artifact/content/observation/run/
operation/snapshot/dataset identities, repository storage protocols, semantic
repository operations, and path-independent artifact/content identity.

## Phase 3: Implement SQLite Metadata And Filesystem Blob Storage

Status: complete for the initial local backend.

The remaining storage refinement is to remove generic `BlobStore` dependence on
local filesystem paths/storage keys in Phase 9.

## Phase 4: Dual-Record Existing HTTP And REST Acquisition

Status: complete.

HTTP/REST acquisition records repository content, observations, provenance, and
source evidence while compatibility outputs remain available.

## Phase 5: Model File Trees And Convert `rsync`

Status: substantially complete.

Authoritative rsync inventory/reconciliation now supports scoped coverage,
unchanged-content reuse, changed/new observations, and absence only when
successful enumeration proves it. A future recursive Merkle representation is a
scale optimization, not a prerequisite for this phase.

## Phase 6: Normalize Source Inventory And Reconciliation

Objective:

- make membership, coverage, change evidence, expected integrity, and absence
  semantics protocol-independent

Work:

- define `InventoryCoverage`, `InventoryItem`, and `SourceInventory`
- define `ChangeToken` separately from content identity
- define `IntegrityExpectation` separately from actual `ContentId`
- extract the successful rsync reconciliation behavior into a generic reconciler
- classify inventory items as new, changed, unchanged, or absent
- permit absence only inside successful complete coverage
- allow unchanged observations to reuse existing content without unnecessary
  retrieval/hashing when trustworthy evidence permits it
- record inventory/reconciliation evidence in source snapshots/operations

Acceptance criteria:

- HTTP, rsync, and synthetic collection fixtures can express their source state
  through one inventory model
- failed/incomplete inventories cannot create authoritative absence
- an upstream checksum is validated against an independently computed
  `ContentId`
- ETag/version/change evidence does not masquerade as content identity
- reconciliation code contains no protocol-specific repository semantics

## Phase 7: Migrate Collections Through `SourceInventory`

Objective:

- replace `REST_BASE`/fanout special result semantics with the normalized source
  model

Work:

- separate collection enumeration from per-item retrieval
- map enumeration results to `SourceInventory`
- define deterministic logical artifact naming for collection items
- apply generic reconciliation/coverage semantics
- record collection items through ordinary content/observation semantics
- record collection enumeration identity and coverage in source snapshots
- preserve compatibility outputs during migration

Acceptance criteria:

- `RestBaseFanoutTask` behavior is expressible without a collection-specific
  provenance/storage model
- a complete collection enumeration can establish absence of removed items
- a partial/failed enumeration cannot establish absence
- collection item history remains reproducible after compatibility outputs are
  deleted

## Phase 8: Formalize Provenance Producers, Lifecycle, And Derived Artifacts

Objective:

- make acquisition and deterministic derivation use one explicit provenance
  model

Work:

- add `ProducerRef` with namespaced stable producer ID and version
- make operation/run lifecycle states explicit and enforce valid transitions
- do not persist dry-run/planned operations merely because plans are inspected
- define `DerivedTaskSpec`
- define canonical `DerivationKey` from:
  - task identity/version
  - normalized parameters
  - declared outputs
  - normalized input identities
- support `dependency_semantics="content"` and `"observation"`
- allow deterministic reuse of prior output content while recording new current
  output observations/provenance
- migrate persistent semantic indexes to specialized derived artifacts
- reserve TTL for source refresh rather than deterministic derivation validity

Acceptance criteria:

- every operation identifies its producer/version
- invalid lifecycle transitions are rejected
- deterministic content-based derivations reuse byte-identical prior results
  without losing current-run provenance
- observation-sensitive derivations distinguish independently observed identical
  bytes
- derived output staleness/reuse can be determined without wall-clock TTL

## Phase 9: Remove Filesystem Assumptions From `BlobStore`

Objective:

- make repository content semantics independent of local filesystem storage

Work:

- redefine generic `BlobStore` around semantic operations such as:
  - `put_bytes`
  - `put_path` or stream-based ingestion convenience
  - `open`
  - `contains`
  - `verify`
  - `delete`
- move local-path access to an optional local-store capability
- remove `storage_key` from semantic content identity/API where possible
- ensure repository/query/dataset code opens content through the blob-store
  abstraction rather than resolving a filesystem path
- document idempotent `put` and orphan-blob failure semantics
- retain `FilesystemBlobStore` as the default small/auditable implementation

Acceptance criteria:

- repository/query/dataset tests pass against a fake non-path-backed blob store
- relocating the filesystem CAS does not change any semantic identity
- no repository-facing model requires a local filesystem path
- interrupted metadata commits may leave orphan blobs but never committed missing
  content

## Phase 10: Complete Repository Authority Cutover

Objective:

- finish moving internal reads and compatibility outputs off legacy manifests,
  mirror-state files, and mirror rescans

Work:

- complete source-result/current-state/freshness/status/integrity queries from
  repository state
- make canonical/timestamped manifests serializers of repository state
- make mirror-state output an explicit compatibility/export view
- make targeted sync planning remember untouched state through repository records,
  not manifest merge
- add conservative adoption/import for existing stores without destructive
  relocation or invented provenance
- remove internal fallbacks that treat generated compatibility files as databases
  once parity tests pass

Cutover rule:

- after this phase, no new internal feature may use a compatibility manifest or
  mirror-state file as authoritative state

Acceptance criteria:

- deleting generated compatibility manifests does not lose semantic state
- current supported query/status/manifest behavior can be generated from
  repository state
- targeted syncs require no manifest merge to remember untouched artifacts
- an existing store can be adopted without reacquisition or destructive moves

## Phase 11: Formalize Planner, Executor, Adapters, And Policies

Objective:

- complete orchestration around the now-proven repository/inventory contracts

Work:

- define `SyncRequest`, `SyncPlan`, `PlanningDecision`, and typed operations
- implement deterministic planning from source definitions plus repository state
- make dry-run use the same plan as execution
- define `SourceAdapter`/`AdapterDescriptor` and adapter registry
- separate declarative `SourceDefinition` from runtime adapter instances
- move HTTP, REST, rsync, and collection work behind adapters
- make inventory/fetch capabilities explicit
- define structured refresh decisions rather than bare booleans
- add explicit bounded concurrency and operation dependencies
- retain the small `Engine` facade
- keep built-in adapter registration direct; add lazy external entry-point discovery
  only if an actual external-plugin requirement appears

Acceptance criteria:

- adding a built-in protocol does not require editing repository semantics
- planner output is deterministic for the same repository state/request
- execution dependencies and concurrency limits are explicit/testable
- source configuration contains no live clients/sessions
- adapter identity/version flows into `ProducerRef`

## Phase 12: Complete Validation As Repository Evidence

Objective:

- unify integrity expectations, storage validation, generic encoding validation,
  and pluggable domain validation

Work:

- retain validation records keyed by content identity plus validator version
- integrate `IntegrityExpectation` evaluation into acquisition
- implement/reuse storage-integrity validation against `ContentId`
- move generic gzip/JSON/container checks into reusable validators where useful
- define a domain-validator extension contract
- reuse validation evidence when content and validator identity/version are
  unchanged
- expose validation through repository/query APIs

Acceptance criteria:

- required failed integrity expectations prevent successful source advancement
- unchanged content is not needlessly revalidated by the same validator version
- validation failures never mutate stored content
- domain libraries can contribute validators without efloud depending on them

## Phase 13: Complete Immutable Datasets And Temporal Policies

Objective:

- finish the generic immutable-data boundary required by downstream consumers

Existing foundation:

- exact/latest/latest-before/latest-all selection
- frozen exact observation membership
- dataset identity and content-equivalence identity
- read-only artifact open/verify

Remaining work:

- selection by source/tag/role/namespace where needed
- explicit temporal time basis
- required-complete-snapshot policies
- maximum observation skew/same-run policies where requested
- deterministic dataset export metadata
- BVP catalog/verification parity gate

Acceptance criteria:

- local blob paths/root relocation do not affect dataset identity
- a frozen dataset never changes after newer ingestion
- temporal resolution never infers absence from incomplete coverage
- downstream BVP generic catalog behavior can be reproduced through efloud

## Phase 14: Retention, Reachability, And Garbage Collection

Objective:

- make historical retention safe under immutable datasets and provenance

Work:

- define retention roots over observations/datasets/snapshots/derived provenance
- implement reachability and dry-run GC reports
- add grace periods
- collect orphan blobs from interrupted ingestion
- never collect content required by retained datasets/provenance
- keep the initial model local-first: retained content must remain in the
  canonical/default blob store

Acceptance criteria:

- GC cannot invalidate a retained dataset
- dry-run explains every proposed deletion
- orphan blobs can be collected safely
- shared content referenced by multiple artifacts/datasets is retained correctly

Deferred:

- remote/offloaded replica tracking
- safe local drop based on verified alternate replicas

These are separate future capabilities and should not complicate initial GC.

## Phase 15: Git And Additional Source Types

Objective:

- demonstrate that the normalized inventory/repository model generalizes beyond
  the original protocols

Work:

- implement a first-class Git source/adapter
- map repository URL/ref/commit/tree/path evidence into `SourceInventory`
- map selected files to ordinary artifacts/observations
- use the same source snapshot/reconciliation/dataset mechanisms
- evaluate additional adapters only from concrete use cases

Acceptance criteria:

- Git requires no repository-schema special case beyond source metadata
- Git-derived datasets mix freely with artifacts from other protocols
- Git membership/absence semantics use the same inventory coverage model

## Phase 16: Simplify Public APIs And Remove Transitional Infrastructure

Objective:

- leave one canonical implementation path after repository parity is proven

Work:

- make `Engine`/`Repository` the preferred public surface
- retain/deprecate `sync(cfg)` according to compatibility policy while delegating
  to canonical orchestration
- remove obsolete manifest-merge state machinery from internal control flow
- remove redundant generic mirror-presence rescans
- remove duplicate cache/status/provenance abstractions
- isolate remaining compatibility serializers under explicit compatibility code
- reduce exports to stable semantic interfaces

Acceptance criteria:

- one canonical ingestion path and one authoritative state model remain
- no internal feature depends on legacy JSON state as a database
- compatibility code is isolated/removable
- module boundaries correspond to real responsibilities rather than migration
  history

## Phase 17: Safe Native Materialization And Optional Views

Objective:

- restore filesystem convenience without weakening repository authority

Work:

- add immutable dataset/source-snapshot materialization
- support `auto`, `reflink`, `copy`, and explicit `symlink` strategies
- make `auto` prefer reflink/CoW then fall back to copy
- do not use hardlinks as the default user-visible strategy
- validate all paths/collisions before writing
- materialize through a temporary sibling tree and atomically publish where
  possible
- include small self-describing metadata for detached dataset materializations
- optionally provide read-only virtual filesystem projections later

Acceptance criteria:

- deleting a view does not affect repository correctness
- modifying a copied/reflinked checkout cannot mutate authoritative CAS content
- materialization is deterministic and rejects path traversal/collisions
- views remain optional conveniences rather than storage requirements

## Phase 18: Deferred Advanced Features (Only When Justified)

These are design targets, not current implementation commitments.

### Recursive Merkle Trees

Consider replacing/augmenting flat tree snapshots with recursive versioned
Merkle trees only if measurements show snapshot/storage/diff costs are material.
Historical tree identities must remain readable.

### Mutable References

If human-friendly mutable names are required, add explicit refs from names to
immutable target IDs with compare-and-swap/generation checks. Refs may become GC
roots but never participate in immutable target identity.

### Replica/Availability Tracking

If content must be offloaded or shared across stores, add replica records
separating `ContentId` from physical availability. Mutable upstream locators do
not count as verified replicas unless exact content identity is established.

### Alternate Blob Backends

Implement alternate blob stores only from concrete requirements. The semantic
`BlobStore` contract must make this possible without adding a general storage
framework dependency to the local core.

## Testing Strategy

### Repository Model Tests

Cover:

- identity canonicalization
- content deduplication
- repeated unchanged observations
- absence/coverage semantics
- transaction failure/recovery
- provenance edges and producer identity
- operation lifecycle transitions
- relational constraints
- source inventory/reconciliation
- source/tree snapshot identity
- derivation-key reuse semantics
- dataset identity and immutability
- reachability/GC

### Source/Reconciliation Integration Tests

For each adapter/source pattern, verify:

```text
upstream fixture
    -> SourceInventory
    -> reconciliation decisions
    -> acquisition where needed
    -> repository records
    -> expected content/provenance/snapshot
```

Include explicit tests for complete, partial, and failed inventories.

### Compatibility Tests

Until cleanup is complete, verify that repository state can reproduce supported:

- canonical/timestamped manifests
- source query results
- status summaries
- mirror-state information that remains public
- derived fanout behavior

Compatibility tests should become deletion targets rather than permanent reasons
to preserve obsolete internals.

### Property And Failure Tests

Add focused property/fault tests for high-value invariants:

- content identity depends only on bytes
- integrity expectations cannot substitute for actual content hashing
- dataset identity is independent of local repository path
- a failed metadata transaction cannot expose unavailable content
- partial source coverage cannot prove absence outside its scope
- deterministic derivation reuse preserves current provenance
- retained datasets protect all required content from GC

### Scale Tests

Use synthetic large-tree fixtures to characterize:

- rsync/inventory reconciliation overhead
- incremental snapshot construction
- SQLite query/index behavior
- directory/file cardinality scaling
- repeated observation storage growth

Only if these measurements show a real bottleneck should recursive Merkle trees,
chunk-level deduplication, or more complex storage representations move out of
Phase 18.

## Migration Of Existing Data

Existing efloud/BVP mirrors may be large and expensive to reacquire. The
migration must therefore support conservative adoption.

The adoption workflow should:

1. inspect legacy manifests/state when available
2. enumerate known materialized files
3. hash/import or safely reuse their bytes in the blob store
4. record only provenance that can actually be established
5. mark source-snapshot completeness conservatively
6. verify repository records against existing files
7. leave legacy data untouched until the user explicitly chooses cleanup

No migration step should require redownloading an unchanged corpus merely to
enter the new repository model.

## Documentation During Migration

- update `STATUS.md` as the active phase changes
- keep `TODO.md` limited to the immediate tranche within the current phase
- update `README.md` when public setup or usage changes
- update `DESIGN.md` only when intended architecture changes
- keep compatibility/deprecation guidance explicit when old and new surfaces
  temporarily coexist

## Completion Criteria

The repository-centered migration is complete when:

- SQLite metadata plus immutable content-addressed blobs are authoritative
- every acquisition protocol emits normalized inventory/acquisition evidence and
  repository observations/provenance
- absence is established only from explicit successful coverage
- file-tree sources preserve reconstructable historical structure
- query/status/sync decisions use repository state rather than merged manifests
- derived artifacts and persistent semantic indexes use ordinary artifact
  provenance and deterministic derivation semantics where applicable
- immutable datasets provide the read-only reproducibility boundary
- retention/GC respect dataset/provenance reachability
- planning and protocol behavior are adapter-driven and deterministic
- legacy manifests/mirrors are compatibility views rather than databases
- existing repositories can be adopted without destructive reacquisition
- downstream consumers such as BVP no longer need their own generic catalog,
  provenance, integrity, or source-store infrastructure
- optional filesystem projections remain convenience utilities over immutable
  repository state
