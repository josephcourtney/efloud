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

## Strategy

The migration is organized around one change in authority:

```text
current

transports -> files/mirrors -> manifests/state -> queries

                         becomes

transports -> Repository -> metadata + immutable blobs
                   |
                   +-> queries
                   +-> source/tree snapshots
                   +-> datasets
                   +-> compatibility manifests/views
```

The repository must become complete and trustworthy before the old manifest and
mirror-state mechanisms are demoted to compatibility views.

The implementation order is therefore:

1. create only the orchestration seam needed to introduce repository recording
   safely
2. implement repository primitives, SQLite metadata, and content-addressed blob
   storage
3. make every existing acquisition path record normalized artifacts,
   observations, provenance, and source state
4. verify repository state against existing manifests and mirrors while both are
   produced
5. switch query/status and synchronization decisions to repository state
6. formalize planning, adapters, and policies around the now-stable repository
   contract
7. add first-class derived artifacts, validation, immutable datasets, retention,
   and historical/tree features
8. remove obsolete BVP-derived and legacy efloud infrastructure after downstream
   parity is demonstrated
9. add optional filesystem projections and other convenience interfaces last

This order deliberately avoids spending early migration effort generalizing
manifest- or path-centric abstractions that the new design makes transitional.

## Cross-Phase Invariants

Every phase must preserve these constraints:

- authoritative new mutation goes through a repository-facing service once that
  service exists
- metadata must never commit a reference to blob content that is not durably
  available
- content objects are immutable and identified by digest
- repeated observation of unchanged bytes must not duplicate content
- an observation must remain distinct from content identity
- source-relative paths are retained as provenance/structure, not used as
  content identity
- no consumer-facing read API may implicitly trigger acquisition
- partial source synchronization must never be interpreted as complete source
  coverage
- compatibility manifests, mirrors, and caches may be regenerated from
  authoritative state once cutover occurs
- the default implementation remains local and service-free
- alternate storage implementations are enabled by semantic interfaces, not by
  weakening repository invariants

## Phase 0: Freeze The Compatibility Perimeter

Objective:

- establish the exact behavior that must survive the authority migration

Work:

- retain regression coverage for current HTTP, REST, collection/fanout, and
  `rsync` acquisition
- inventory the current canonical/timestamped manifest fields, mirror-state
  fields, source-result lookups, query targets, index outputs, and status payloads
- identify every place where current code treats a filesystem path, manifest
  entry, or mirror-state record as authoritative
- identify current user-visible source layouts that must remain available as
  compatibility materializations
- record current behavior for targeted syncs, partial `rsync` path syncs,
  unchanged sources, failures, and derived fanout

Deliverables:

- compatibility inventory in tests or focused documentation
- characterization fixtures for the authority boundaries being replaced

Acceptance criteria:

- every current authoritative read/write path has a planned repository-backed
  replacement
- representative current outputs can detect migration drift
- no retained source data must be moved or deleted to start the migration

## Phase 1: Introduce The Minimal Runtime Seam

Objective:

- make current synchronization injectable enough to add repository recording
  without further enlarging `sync.py`

Work:

- extract manifest payload shaping from `sync.py`
- add a small `Runtime` coordinator responsible for phase sequencing
- make `sync(cfg)` delegate to the runtime while preserving `SyncResult`
- introduce an internal operation-result/ingestion boundary through which
  successful acquisition results can later be committed to a repository
- do not yet build the full planner/executor/adapter architecture

Acceptance criteria:

- caller-visible `sync(cfg)` behavior and current files/manifests are unchanged
- `sync.py` no longer owns manifest-entry shaping
- runtime sequencing can accept a repository recorder without transport-specific
  code knowing about SQLite
- existing sync and transport tests remain unchanged or require only seam-level
  updates

Risks:

- over-extracting abstractions before repository semantics are known
- accidentally making a temporary runtime interface public

## Phase 2: Define Repository Primitives And Storage Contracts

Objective:

- establish the stable semantic boundary that all later work uses

Work:

- define strongly typed identifiers and records for:
  - `SourceId`
  - `ArtifactKey`
  - `ContentId`
  - `ObservationId`
  - `RunId`
  - `OperationId`
  - logical artifacts
  - content objects
  - observations
  - provenance edges/records
  - materializations
- define repository-facing `MetadataStore` and `BlobStore` protocols around
  efloud operations rather than arbitrary CRUD
- define a `Repository` facade that coordinates the stores
- define transaction boundaries and failure semantics before transport code uses
  the repository
- keep protocol-specific metadata in structured JSON mappings

Design constraints:

- paths are not artifact identity
- `ContentId` defaults to SHA-256 over exact bytes
- observations reference logical artifact and content identities
- repository methods express semantic operations such as ingest, observe, open,
  and query rather than `write_path()`

Acceptance criteria:

- models can represent repeated unchanged observations, multiple sources sharing
  identical content, and derived output with multiple inputs
- repository contracts do not import HTTP, `rsync`, REST, or BVP-specific types
- identity canonicalization has deterministic unit tests

## Phase 3: Implement SQLite Metadata And Filesystem Blob Storage

Objective:

- create the first authoritative repository backend

Work:

- implement `SQLiteMetadataStore`
- implement `FilesystemBlobStore` with portable content-addressed layout
- introduce an explicit schema version and migration mechanism from the first
  committed schema
- enable foreign-key enforcement and relational uniqueness constraints
- implement atomic blob installation:
  1. write/acquire temporary bytes
  2. calculate digest and byte size
  3. atomically install or reuse the immutable blob
  4. commit metadata referencing the installed blob
- tolerate orphaned unreferenced blobs after interrupted operations; never
  tolerate committed metadata pointing at missing blobs
- implement basic repository open/close, content open, artifact history, and
  observation lookup APIs

Initial metadata entities should cover at least:

```text
sources
runs
operations
logical_artifacts
content_objects
observations
provenance_edges
materializations
```

Acceptance criteria:

- identical bytes are physically stored once
- repeated ingestion creates distinct observations when requested
- interrupted writes cannot create metadata references to absent blobs
- relational constraints reject invalid references and duplicate identities
- repository data survives reopen and is deterministic under fixture inputs

## Phase 4: Dual-Record Existing HTTP And REST Acquisition

Objective:

- prove the repository against simple existing acquisition paths while current
  manifests remain available

Work:

- assign stable logical artifact keys to existing HTTP and REST source outputs
- record runs and operations through the repository
- normalize successful HTTP/REST results into:
  - content objects
  - observations
  - acquisition provenance
  - transport metadata such as URL, ETag, Last-Modified, response status, and
    retrieval timing when available
- continue producing current files and manifests during this phase
- compare repository-derived facts against the legacy manifest after each test
  run
- record unchanged HTTP observations without duplicating content where the
  source was actually checked

Acceptance criteria:

- HTTP and REST syncs populate repository history without changing current user
  behavior
- the repository can answer current-content and observation-history questions
  without reading the JSON manifest
- legacy manifest and repository records agree on source, destination/content,
  success, and relevant freshness facts

## Phase 5: Model File Trees And Convert `rsync`

Objective:

- make large mirrored file trees first-class repository history rather than an
  opaque mirror root plus later filesystem scans

Work:

- define source snapshot coverage explicitly:
  - complete source/tree observation
  - partial path/subtree observation
  - failed/incomplete observation
- implement file-tree entry and tree-snapshot persistence
- assign logical artifact keys independently from source-relative paths while
  retaining every source-relative path needed to reconstruct the source tree
- modify the `rsync` integration so changed/new files produce individual
  observations and removed files are represented explicitly when coverage makes
  absence meaningful
- build immutable tree snapshots or equivalent canonical Merkle-style tree state
  from observed entries
- reuse unchanged content and unchanged tree structure across snapshots
- preserve current native mirror layout as a compatibility materialization
  during migration
- eliminate the need for a later generic mirror rescan merely to discover files
  efloud itself just acquired

Performance requirements:

- do not hash unchanged large trees blindly when trustworthy prior state and
  transport change evidence can avoid it
- support incremental tree-snapshot construction
- retain periodic full integrity verification as a separate operation

Acceptance criteria:

- a full tree sync can reconstruct the source-relative tree from repository state
- a partial path sync records scope and cannot imply absence outside that scope
- one changed file does not duplicate all unchanged file contents
- repeated unchanged syncs produce history without duplicating blobs
- repository state can reproduce the information currently needed from
  mirror-state and mirror-presence scans

## Phase 6: Migrate Collections And Derived Outputs To The Artifact Model

Objective:

- eliminate special result families that bypass ordinary artifact/provenance
  semantics

Work:

- generalize `REST_BASE` into a collection model with explicit:
  - enumeration
  - item identity
  - per-item retrieval
  - reconciliation/coverage
  - logical artifact naming
- make collection enumeration itself record sufficient source-snapshot evidence
- record every collection item through ordinary observation/content semantics
- convert derived-task outputs to ordinary artifacts with:
  - stable task identity and version
  - exact input observations
  - normalized parameters
  - output observations
  - provenance edges
- convert persistent semantic indexes into specialized derived artifacts
- reserve the term cache for disposable acceleration state

Acceptance criteria:

- fanout/collection behavior no longer requires a separate provenance or storage
  model
- derived output staleness can be determined from recorded input identities
- current `RestBaseFanoutTask` behavior remains expressible through the new model

## Phase 7: Make Repository State Authoritative

Objective:

- cut internal reads over from merged manifests, mirror-state files, and mirror
  rescans to repository queries

Work:

- move source-result resolution onto repository queries
- move current-state/freshness lookup onto observations and source snapshots
- move status and integrity summaries onto repository state
- make canonical and timestamped JSON manifests serializers/exports of repository
  state rather than independent databases
- make mirror-state output a compatibility/exported view where it remains useful
- generate compatibility materialized mirror layouts from repository state when
  practical
- add an import/adoption path for existing repositories:
  - read current manifest/mirror state
  - hash/import existing files without modifying the source tree
  - create observations and source snapshots conservatively
  - never invent provenance that legacy state cannot support

Cutover rule:

- after this phase, new code must not use the compatibility manifest as its
  source of truth

Acceptance criteria:

- deleting only generated compatibility manifests does not lose authoritative
  repository state
- targeted syncs require no manifest-merge algorithm to remember untouched
  artifacts
- current query/status behavior can be generated from repository state
- an existing efloud store can be adopted without destructive relocation

## Phase 8: Formalize Planner, Executor, Adapters, And Policies

Objective:

- complete the orchestration architecture around the now-stable repository
  contract

Work:

- define `SyncRequest`, `SyncPlan`, `PlanningDecision`, and typed operations
- implement deterministic planning from source definitions plus repository state
- make dry-run use the same plan as execution
- define `ProtocolAdapter` and `ProtocolAdapterRegistry`
- move protocol-specific work behind adapters for:
  - HTTP
  - REST
  - `rsync`
  - collections
- define structured refresh decisions rather than bare booleans
- separate source-refresh policy from deterministic derived invalidation
- add explicit bounded concurrency and operation dependencies
- retain the small `Engine` facade over the composed runtime

Acceptance criteria:

- adding a new source protocol does not require editing repository semantics or
  engine orchestration branching
- planner output is deterministic for the same repository state and request
- execution dependencies and concurrency limits are explicit and testable
- current refresh behavior remains representable without transport-specific
  policy leaking into the engine core

## Phase 9: Add Validation As Repository Evidence

Objective:

- unify integrity, encoding validation, and pluggable domain validation without
  coupling efloud to domain semantics

Work:

- add validation records keyed by content identity plus validator
  identity/version
- implement storage-integrity validation against content digest
- move generic gzip/JSON/container checks into reusable validators where useful
- define a domain-validator extension contract
- cache validation evidence when both content and validator identities are
  unchanged
- expose validation through repository and query APIs

Acceptance criteria:

- unchanged content is not needlessly revalidated by the same validator version
- validation failures never mutate stored content
- domain libraries can contribute validators without efloud depending on them

## Phase 10: Implement Immutable Datasets And Temporal Resolution

Objective:

- provide the generic immutable-data boundary required by downstream consumers
  such as BVP

Work:

- implement `DatasetDefinition`, resolved dataset manifests, and
  `ImmutableDataset`
- start with a deliberately small selection language:
  - exact observation
  - latest observation
  - latest observation before a timestamp
  - selection by source/tag/role/namespace where repository metadata supports it
- freeze selectors to exact observation and content identities
- define deterministic canonical dataset identity
- also expose content-equivalence identity when useful
- implement temporal consistency policies including:
  - explicit time basis
  - required complete snapshots
  - maximum observation skew where requested
- provide read-only artifact lookup/open/verify APIs
- implement deterministic dataset export metadata

Acceptance criteria:

- resolving the same exact membership yields the same dataset identity
- local blob paths or repository root relocation do not affect dataset identity
- a frozen dataset never changes when newer observations are ingested
- temporal resolution never infers absence from incomplete source coverage
- a consumer can operate offline using only an immutable dataset and repository
  bytes

Downstream integration gate:

- reproduce the behavior of BVP's current `bvp-catalog` manifest/verification
  interface using efloud datasets before BVP removes its transitional catalog

## Phase 11: Retention, Reachability, And Garbage Collection

Objective:

- make historical retention safe under immutable datasets and provenance
  dependencies

Work:

- define retention policy over observations/references rather than filesystem
  paths
- implement reachability from:
  - immutable datasets
  - retained observations
  - retained source snapshots
  - derived artifacts and provenance ancestors
- implement dry-run GC reports
- add configurable grace periods
- delete metadata references transactionally before/with safe blob collection as
  appropriate
- never collect content referenced by an immutable dataset

Acceptance criteria:

- GC cannot invalidate a retained dataset
- dry-run explains every proposed deletion
- orphan blobs from interrupted ingestion can eventually be collected safely
- retention tests cover shared content referenced by multiple artifacts/datasets

## Phase 12: Git And Additional Source Types

Objective:

- demonstrate that the repository model generalizes beyond the original
  HTTP/REST/`rsync` cases

Work:

- implement a first-class `GitSource`/adapter
- record repository URL, ref/commit, tree/blob identity, and path provenance
- map selected Git files into ordinary logical artifacts and observations
- use the same source-snapshot and dataset mechanisms as other protocols
- evaluate additional collection/listing adapters only from concrete use cases

Acceptance criteria:

- Git acquisition requires no repository-schema special case beyond
  source-specific metadata
- Git-derived datasets can mix freely with artifacts acquired through other
  protocols

## Phase 13: Simplify Public APIs And Remove Transitional Infrastructure

Objective:

- leave one canonical implementation path after repository parity is proven

Work:

- make the new `Engine`/`Repository` APIs the preferred public surface
- retain or deprecate `sync(cfg)` according to compatibility policy, but ensure it
  delegates to the canonical runtime
- remove obsolete manifest-merge state machinery from internal control flow
- remove generic mirror-presence rescans made redundant by repository records
- remove duplicate cache/status/provenance abstractions superseded by repository
  concepts
- move remaining compatibility serializers into an explicit compatibility area
- update source models so protocol-specific fields live with their source types
- reduce exports to stable semantic interfaces rather than implementation stores

Acceptance criteria:

- there is one canonical ingestion path and one authoritative state model
- no current internal feature depends on a legacy JSON manifest as a database
- compatibility code is isolated and removable
- package/module boundaries correspond to real responsibilities rather than
  migration history

## Phase 14: Optional Views And Portability Utilities

Objective:

- restore filesystem convenience without weakening repository authority

Work:

- provide native read-only materialization/checkouts for source snapshots or
  datasets
- use hardlinks/reflinks only as optional optimizations; fall back to copies
- optionally provide a read-only virtual filesystem projection where supported
- allow useful projections such as:
  - current source tree
  - a source tree as of a timestamp
  - an immutable dataset
  - all observations/versions of one artifact
- ensure all projections resolve immutable repository content and cannot mutate
  authoritative state
- add portable dataset export/import if demanded by downstream workflows

Acceptance criteria:

- deleting a disposable view does not affect repository correctness
- modifying a copied checkout cannot mutate repository content
- virtual/native views are optional dependencies/utilities, not required for
  repository or dataset use

## Testing Strategy

The migration requires several complementary test layers.

### Repository Model Tests

Cover:

- identity canonicalization
- content deduplication
- repeated unchanged observations
- transaction failure/recovery
- provenance edges
- relational constraints
- source-snapshot coverage
- tree snapshot identity
- dataset identity and immutability
- reachability/GC

### Transport Integration Tests

For each adapter, verify:

```text
upstream fixture
    -> operation
    -> repository records
    -> expected content/provenance/snapshot
```

Transport tests should not assert repository internals that are not part of the
semantic contract.

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
- dataset identity is independent of local repository path
- a failed metadata transaction cannot expose unavailable content
- partial source coverage cannot prove absence outside its scope
- retained datasets protect all required content from GC

### Scale Tests

Use synthetic large-tree fixtures to characterize:

- `rsync` ingestion overhead
- incremental snapshot construction
- SQLite query/index behavior
- directory/file cardinality scaling
- repeated observation storage growth

Do not optimize tree/chunk representation beyond whole-file content addressing
until measurements demonstrate a need.

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
- every acquisition protocol emits normalized observations and provenance
- file-tree sources preserve reconstructable historical source structure and
  explicit coverage
- query/status/sync decisions use repository state rather than merged manifests
- derived artifacts and persistent semantic indexes use ordinary artifact
  provenance
- immutable datasets provide the read-only reproducibility boundary
- retention and GC respect dataset/provenance reachability
- planning and protocol behavior are adapter-driven and deterministic
- legacy manifests/mirrors are compatibility views rather than databases
- existing repositories can be adopted without destructive reacquisition
- downstream consumers such as BVP no longer need their own generic catalog,
  provenance, integrity, or source-store infrastructure
- optional filesystem projections remain convenience utilities over immutable
  repository state
