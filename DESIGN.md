# DESIGN

> This document is normative. It defines the intended architecture for `efloud`
> and the invariants new work must preserve while the implementation migrates
> from the current alpha design.

## Intent And Scope

`efloud` is a versioned data-ingestion and artifact-repository library.

It acquires external data through heterogeneous protocols, records what was
observed and how it was obtained, stores immutable content efficiently, tracks
provenance and integrity, and can freeze exact selections of artifact versions
into reproducible immutable datasets.

The repository, not a filesystem mirror or JSON manifest, is the authoritative
model of state.

The design must preserve the useful properties of the current implementation:

- simple programmatic ingestion
- HTTP, REST, collection/fanout, and `rsync` support
- deterministic planning and execution
- inspectable local state
- offline use after acquisition
- derived artifacts and indexes
- query and status helpers

while replacing path-centric storage and merged-manifest state with explicit
artifact identity, version history, provenance, normalized source inventories,
and repository-backed queries.

## High-Level Architecture

The default architecture is:

```text
Sources
   |
   v
Source adapters
   |
   +--> SourceInventory / acquisition results
   |
   v
Planner / Executor / Reconciler
   |
   v
Repository
   |-----------------------------|
   |                             |
MetadataStore                 BlobStore
(SQLite by default)           (content-addressed files by default)
   |                             |
   |-----------------------------|
                 |
                 v
        immutable repository state
                 |
      +----------+-----------+----------------+
      |                      |                |
   Query API          Immutable datasets   optional views
                                           / exports
```

`Engine` is the convenience facade over these pieces. It does not define storage
or provenance semantics itself.

The major responsibility boundaries are:

- **source adapters** understand external protocols and enumerate/fetch source
  items
- **planning/reconciliation** compares requested source state with repository
  state and decides what work is required
- **repository** owns authoritative artifact, observation, provenance, dataset,
  validation, and retention state
- **blob storage** owns immutable bytes identified by content digest
- **metadata storage** owns identities and relationships
- **query and dataset APIs** expose read-only views over repository state
- **filesystem mirrors, manifests, exports, and virtual filesystems** are derived
  representations, not authoritative storage

## Core Invariants

All authoritative mutation occurs through the `efloud` repository API.

Filesystem projections and exported manifests are read-only or disposable
representations of repository state. External code must never be able to mutate
repository content by editing a projected path.

The repository must never commit metadata that references unavailable content.
It is acceptable for an interrupted operation to leave an unreferenced blob;
reachability-based garbage collection can remove such orphans later.

Absence is evidence, not a default assumption. A source item may be recorded as
absent only when a successful source inventory establishes complete coverage of
the relevant scope.

These invariants make complete provenance, transactional updates, historical
reconstruction, and integrity checking possible.

## Goals

- expose a compact API for ordinary acquisition and repository use
- support heterogeneous sources behind protocol adapters
- normalize source enumeration and reconciliation across protocols
- make logical artifact identity independent of filesystem layout
- distinguish retrieval observations from immutable content
- distinguish actual content identity from upstream integrity expectations and
  change tokens
- retain complete acquisition and derivation provenance
- deduplicate identical content without losing repeated observations
- represent source state and file trees historically
- create immutable datasets from exact artifact observations
- support reproducible temporal or "as-of" dataset resolution
- make deterministic derived artifacts reusable without losing run provenance
- use relational integrity for universal structure while allowing flexible JSON
  metadata
- keep bytes directly inspectable in a portable content-addressed blob store
- permit optional native or virtual filesystem views without making them part of
  the storage model
- keep planning deterministic and policy decisions explainable

## Non-Goals

- being a general desktop file synchronization product
- being a workflow scheduler or distributed compute system
- interpreting application-specific scientific or business data
- forcing all artifact metadata into a rigid relational schema
- requiring a server database for ordinary local use
- making a FUSE/WinFsp filesystem a core dependency
- using filesystem paths, mtimes, inodes, hardlinks, or local storage keys as
  artifact/content identity
- treating cache files or exported manifests as authoritative state
- requiring remote/offloaded blob replicas before a concrete use case exists
- requiring mutable branch/ref semantics before a concrete use case exists
- implementing recursive Merkle trees or chunk-level deduplication before scale
  measurements justify the additional complexity

## Domain Model

### Source

A source is a stable declarative description of an external data origin.

Shared source fields include:

- stable source identifier
- description
- protocol/source type
- upstream locator
- tags and role
- aliases
- source-specific metadata
- policy hints

Protocol-specific source types may include:

- `HttpSource`
- `RestSource`
- `RsyncSource`
- `CollectionSource`
- `GitSource`

Source definitions describe facts and configuration. Execution state belongs in
runs, operations, inventories, observations, and source snapshots.

Protocol-specific fields must remain isolated to the source type or adapter that
understands them.

### Logical Artifact

A logical artifact names a thing whose content may change over time.

Examples:

```text
reference:taxonomy:nodes
weather:noaa:station:KBDR:daily
pdb:8ef4:mmcif
```

The repository treats the identifier as an opaque, stable key. Domain packages
may define conventions for keys, but `efloud` must not interpret their domain
meaning.

Logical artifact identity must not depend on:

- absolute paths
- local cache roots
- inode identity
- retrieval time
- storage backend

### Content Object

A content object is an immutable byte sequence identified by content digest.

The default identity is SHA-256:

```text
sha256:<hex digest>
```

The semantic content record includes at least:

- content identifier
- byte size
- media type when known

Blob-store placement is an implementation detail. Local paths, bucket keys, or
other backend locators do not participate in content identity and should not be
required by repository-facing APIs.

Identical bytes must reuse the same content object even when they are observed
multiple times, by different sources, or under different logical artifact keys.

Content objects are immutable. Replacement means creating or reusing another
content object and recording a new observation.

### Observation

An observation records that a logical artifact was observed with particular
content under particular acquisition circumstances.

An observation includes at least:

- observation identifier
- logical artifact key
- content identifier
- source identifier when applicable
- run and operation identifiers
- observation time
- source-relative path or upstream locator when applicable
- source-provided version or modification metadata when available
- transport/source-specific metadata

Repeated acquisition of unchanged bytes therefore produces:

```text
1 logical artifact
1 content object
N observations
```

This preserves acquisition history without duplicating content.

### Absence

An absence observation records that a logical artifact was established not to be
present within a successfully observed source scope.

Absence must carry the same run/operation/source provenance needed to explain why
it is trusted. Incomplete or failed inventories may never create authoritative
absence outside their proven scope.

### Source Inventory

A `SourceInventory` is the normalized representation of what an adapter
successfully established about source membership before or alongside content
retrieval.

Conceptually:

```python
@dataclass(frozen=True)
class InventoryCoverage:
    scope: tuple[str, ...]
    complete: bool

@dataclass(frozen=True)
class InventoryItem:
    item_id: str
    artifact_key: ArtifactKey
    locator: str | None
    source_path: str | None
    change_token: ChangeToken | None = None
    expected_integrity: tuple[IntegrityExpectation, ...] = ()
    metadata: JsonObject = field(default_factory=dict)

@dataclass(frozen=True)
class SourceInventory:
    source_id: SourceId
    observed_at: float
    coverage: InventoryCoverage
    items: tuple[InventoryItem, ...]
    upstream_identity: str | None = None
    metadata: JsonObject = field(default_factory=dict)
```

The exact concrete API may evolve, but the semantic separation is normative:

- enumeration/membership evidence
- coverage/completeness
- per-item identity and locator
- optional change evidence
- optional integrity expectations

HTTP may produce a one-item complete inventory. `rsync` produces a path-scoped
inventory. Collection/fanout enumeration produces item identities. Git may
produce a commit/tree-backed inventory.

A generic reconciler compares inventories with repository state and classifies
items as new, changed, unchanged, or absent. Protocol adapters must not each
invent incompatible absence/reconciliation semantics.

### Change Tokens

A change token is source evidence that may allow retrieval to be skipped or
revalidated efficiently. Examples include HTTP ETags, upstream version IDs, or
source-specific revision tokens.

Change tokens are not content identity. They may be classified by strength or
reliability when useful to policy.

### Integrity Expectations

An integrity expectation is an upstream assertion that eFLOUD can test, for
example an expected SHA-256 digest supplied by a registry or source manifest.

Integrity expectations are distinct from `ContentId`:

```text
upstream assertion -> IntegrityExpectation
actual downloaded bytes -> ContentId
comparison -> ValidationResult
```

An upstream checksum must never become the authoritative content identity until
eFLOUD has independently computed and verified the bytes.

HTTP ETags and Last-Modified values are change/version evidence, not integrity
expectations unless the source explicitly defines cryptographic semantics.

### Materialization

A materialization describes a physical representation of repository content,
such as a native checkout, compatibility mirror, or exported dataset tree.

Materialization is not identity.

The repository must remain correct if a disposable materialized view is removed
and reconstructed from authoritative blobs and metadata.

Ordinary user-visible immutable materialization should prefer:

```text
reflink / copy-on-write clone
        ↓ fallback
copy
```

Hardlinks should not be the default because modifying a hardlinked checkout can
corrupt an authoritative filesystem CAS blob. Symlinks are appropriate only for
explicit disposable view modes.

Materialization should validate path layout/collisions before writing and should
publish a complete tree atomically where the platform permits it.

### Producer And Operation Lifecycle

Every acquisition or derivation operation has an explicit producer identity and
version:

```python
ProducerRef(producer_id="efloud:rsync", version="...")
```

Producer IDs are namespaced and stable. Protocol adapters and derived tasks use
the same producer concept.

Runs and operations use explicit lifecycle states rather than inferring state
solely from nullable timestamps. At minimum:

```text
operation: running -> succeeded | failed | cancelled
run:       running -> succeeded | partial | failed | cancelled
```

Plans and dry-runs describe potential work but do not create persisted
`planned` operations merely by being inspected.

Invalid lifecycle transitions must be rejected by repository/metadata-store
logic.

### Provenance

Provenance records describe how observations and derived artifacts came to
exist.

A provenance record should include:

- run identifier
- operation identifier
- producer identity/version
- source identifier when applicable
- upstream locator when applicable
- input observation identifiers
- normalized parameters
- start and completion times
- transport or transformation metadata

Fetched and derived artifacts use the same provenance model.

Provenance therefore forms a directed graph from source observations through
transformations, indexes, and other derived artifacts.

### Validation

Validation results are immutable records associated with content identity and a
validator identity/version.

Validation is layered:

1. **storage integrity** - content still hashes to its content identifier
2. **source expectation validation** - expected checksum/version assertions
3. **generic encoding/container validation** - for example gzip or JSON validity
4. **domain validation** - supplied by consuming packages

A validation result should be reusable when both content identity and validator
identity/version are unchanged.

Validation must never silently mutate artifact content.

### Source Snapshot

A source snapshot records what state of a source was actually observed.

Snapshots are derived from successful inventory/reconciliation evidence plus
content observations. Snapshot evidence is source-specific. Examples include:

- HTTP ETag, Last-Modified value, or response digest
- REST/collection enumeration identity
- `rsync` tree identity and requested path scope
- Git commit or tree identity

Snapshots must explicitly represent coverage or completeness. "Not observed"
must not be conflated with "observed absent".

For partial synchronization, the snapshot records the selectors or subtrees that
were actually examined.

### Tree Snapshot

File-tree sources are represented by immutable canonical tree snapshots.

The initial implementation may use a flat canonical tree representation, but the
semantic target permits recursive Merkle trees whose entries reference:

- content objects for files
- child tree identities for directories
- symlink targets when preserved

Tree identity is derived from canonical ordered semantic entries. Local
filesystem details such as inode, ctime, uid/gid, or absolute paths must not
participate in tree identity by default.

A future recursive representation should structurally share unchanged subtrees
between snapshots. It should be introduced only when measurements show that the
flat representation is a material scaling cost, and historical tree identities
must remain readable through explicit representation versioning.

## Repository

`Repository` is the authoritative service boundary over metadata and blobs.

Conceptually:

```python
Repository(
    metadata_store=SQLiteMetadataStore(...),
    blob_store=FilesystemBlobStore(...),
)
```

The repository coordinates transactions across these stores and exposes
semantic operations rather than arbitrary CRUD.

Typical mutation operations include:

- ingest or record an observation
- observe existing content without re-storing bytes
- record absence supported by complete inventory evidence
- record derived output and provenance
- record validation
- create or update source snapshots
- resolve and publish datasets
- apply retention decisions
- remove unreferenced content after policy permits it

Typical read operations include:

- resolve a logical artifact
- enumerate observation history
- open content
- inspect provenance
- query source snapshots
- open immutable datasets

The public API should avoid exposing "write this repository path" as a primitive.
Callers declare artifact semantics and input relationships; the repository owns
physical placement and provenance recording.

## Storage Architecture

### Metadata Store

The default metadata store is SQLite.

The relational model should encode universal structure and integrity constraints,
including entities such as:

```text
sources
runs
operations
logical_artifacts
content_objects
observations
artifact_absences
provenance_edges
validations
source_snapshots
tree_snapshots
datasets
dataset_members
materializations
```

Foreign keys, unique constraints, lifecycle transition checks, and transactions
should enforce repository invariants where possible.

Protocol- and domain-specific details belong in JSON columns rather than causing
transport-specific relational columns to proliferate.

SQLite is the local default because the normal repository is single-machine and
should not require a service. The repository API should permit a future
PostgreSQL metadata implementation if shared multi-machine repositories become a
requirement.

### Blob Store

The default blob store is a portable content-addressed filesystem layout, for
example:

```text
objects/
  sha256/
    ab/
      abcdef...
```

The generic blob-store contract is semantic and storage-location independent:

```python
class BlobStore(Protocol):
    def put_bytes(...) -> ContentRef: ...
    def put_path(...) -> ContentRef: ...
    def open(content_id) -> BinaryIO: ...
    def contains(content_id) -> bool: ...
    def verify(content_id) -> bool: ...
    def delete(content_id) -> None: ...
```

A local filesystem path is an optional capability of a local blob store, not a
requirement of every blob store. Repository/query/dataset code should use
`open()` rather than reaching through to a filesystem path.

Blob storage rules:

- content is immutable after installation
- blob identity is derived from bytes
- `put` is idempotent by content identity
- a successful `put` guarantees immediately readable content
- writes occur through temporary files followed by atomic installation where the
  backend permits it
- identical content is stored once
- storage paths/keys are implementation details
- whole-file content addressing is the default

Chunk-level deduplication is not part of the initial design. It may be added for
large-file workloads only if measurements justify the complexity.

Potential future blob backends include object storage, but the repository model
must not depend on filesystem-specific features.

### Transactional Ingestion

The repository must not expose metadata referencing unavailable content.

The default ingestion sequence is:

```text
acquire bytes into temporary storage
        |
        v
compute actual ContentId
        |
        v
validate required IntegrityExpectation(s)
        |
        v
atomically install or reuse immutable blob
        |
        v
metadata transaction
  - content record
  - observation
  - provenance
  - validation evidence
  - source/run/operation updates
        |
        v
commit
```

If a required integrity expectation fails, the operation fails and source state
must not advance as if acquisition succeeded. Actual digest/size evidence should
remain available in operation diagnostics. Failed bytes need not enter the
ordinary CAS unless a future quarantine/forensic policy explicitly requests it.

Equivalent guarantees must be preserved by alternate storage backends.

## Ingestion And Synchronization

### Engine

`Engine` is the high-level convenience facade for acquisition.

It assembles the default repository, planner, executor, adapters, policies, and
query services while keeping advanced composition optional.

A simple usage model should remain possible:

```python
engine = Engine(root="repo", sources=[...])
result = await engine.sync()
```

### Planning

Planning converts caller intent and repository state into deterministic typed
operations.

Planning may consider:

- requested targets
- source definitions
- current source snapshots/inventories
- current artifact observations
- adapter capabilities
- refresh policies
- derived dependencies
- validation state

Planning performs no authoritative mutation or network retrieval.

Dry-run uses the same planning path as real execution.

Planning decisions must be explainable and serializable.

### Reconciliation

Reconciliation is protocol-independent wherever possible.

A generic reconciler compares a successful `SourceInventory` against relevant
repository state and classifies source items as:

- new
- changed
- unchanged
- absent within proven complete scope

The reconciler must preserve repeated observations of unchanged content when the
source was actually observed, while reusing the existing `ContentId` and avoiding
unnecessary byte hashing/retrieval when trustworthy source evidence permits it.

Incomplete inventories may record positive observations inside their scope but
may not infer absence from missing members.

### Execution

Execution performs approved operations, controls concurrency, dispatches to
protocol adapters, and commits resulting repository records.

Execution must not invent unrelated work outside the approved plan except local
bookkeeping necessary to safely complete an operation.

### Protocol Adapters

Protocol-specific acquisition behavior belongs behind adapters.

Adapters separate declarative source configuration from runtime implementation.
Conceptually:

```python
class SourceAdapter(Protocol):
    descriptor: AdapterDescriptor

    async def inventory(...) -> SourceInventory: ...
    async def fetch(...) -> AcquisitionResult: ...
```

An adapter descriptor contains a stable namespaced adapter/producer ID, version,
and capabilities.

Each adapter must:

- declare the source/operation types it supports
- contribute protocol-specific planning evidence where needed
- enumerate source membership/coverage when the protocol permits it
- retrieve content for requested items
- emit normalized inventory/acquisition evidence rather than writing repository
  internals directly

Initial adapters include:

- HTTP file acquisition
- REST acquisition
- `rsync` tree synchronization
- collection/fanout acquisition

Git should become a first-class adapter for versioned upstream repositories.

Built-in adapters may be registered directly. External plugin discovery should
be added only if a real external-adapter use case appears; if added, use lazy
loading and fully qualified/namespaced identities.

Adding a protocol must not require modifying repository semantics.

### Collection Sources

Collection/fanout acquisition is a first-class source pattern rather than a
special REST_BASE concept.

A collection source separates:

- enumeration of item identities into `SourceInventory`
- per-item retrieval
- naming/logical artifact mapping
- reconciliation/completeness policy

REST pagination and REST fanout are implementations of this more general model.
Collection enumeration is source evidence and should be sufficient to establish
complete/partial membership semantics independently of individual item fetches.

### File-Tree Sources

For file-tree sources such as `rsync`, inventory establishes the covered path
scope and item set before or alongside transfer reconciliation.

The repository must not need to rescan its own mirror later merely to rediscover
which files it previously ingested.

Source-relative paths are retained as metadata. A current source-like tree may be
materialized for convenience, but it is a derived view over repository state.

### Derived Artifacts

Derived outputs are ordinary artifacts with provenance, not a separate cache
object family.

A deterministic derived task declares at least:

```python
@dataclass(frozen=True)
class DerivedTaskSpec:
    task_id: str
    task_version: str
    deterministic: bool
    dependency_semantics: Literal["content", "observation"]
    parameters: JsonObject
```

The repository/executor computes a canonical `DerivationKey` from:

- task identity/version
- normalized parameters
- declared output identities
- normalized input identities according to dependency semantics

For `dependency_semantics="content"`, independently observed but byte-identical
inputs may reuse a prior deterministic result. For
`dependency_semantics="observation"`, provenance-distinct inputs remain distinct.

Reuse of an existing output `ContentId` must still create a new output observation
for the current run/operation so current provenance remains complete.

`task_version` is an explicit reproducibility contract. eFLOUD should not attempt
to infer reproducibility by hashing arbitrary Python source or the entire runtime
environment, though callers may record an optional environment fingerprint.

TTL remains appropriate for deciding when an external source should be
re-observed, not for deterministic derived invalidation.

### Indexes

Indexes are specialized derived artifacts.

Index definitions may add query-oriented metadata and convenience APIs, but
index outputs and their provenance are stored using the ordinary artifact model
and deterministic derivation semantics where appropriate.

Disposable database indexes used solely to accelerate repository queries remain
implementation caches and are not repository artifacts.

## Time Model

The repository must distinguish temporal concepts rather than using one generic
timestamp.

Relevant times may include:

- request/start time
- inventory/observation time
- storage/commit time
- upstream modification time
- upstream validity interval when explicitly provided

Temporal dataset or artifact resolution must explicitly state which temporal
semantics it uses.

Observation time is always repository provenance; upstream time is source data
and may be absent or unreliable.

## Immutable Datasets

A dataset is a reproducible immutable selection of exact artifact observations.

The model separates definition from resolved state:

```text
DatasetDefinition
      |
      | resolve against repository state
      v
DatasetManifest
      |
      | canonical identity
      v
ImmutableDataset
```

### Dataset Definition

A definition is an intensional selection rule. It may express operations such as:

- exact observation selection
- latest observation for an artifact
- latest observation before a timestamp
- selection by namespace, source, role, or tag

A definition is not itself sufficient for reproducibility because future
resolution may produce a different result.

### Dataset Manifest

Resolution freezes every selector to exact observation and content identities.
The resulting manifest contains no unresolved temporal queries.

Dataset identity must not depend on local storage paths or cache locations.

The repository may expose two useful identities:

- **dataset identity** - exact membership including observation/provenance identity
- **dataset content identity** - semantic membership plus content identities,
  allowing two independently observed but byte-identical datasets to be
  recognized as content-equivalent

### Dataset Resolution Policy

Temporal multi-source resolution may require consistency policies such as:

- latest-before a timestamp
- same-run observations
- maximum observation-time skew
- required complete source snapshots

The resolver must not infer absence from incomplete source coverage.

### Immutable Dataset API

Consumers should have a small read-only interface, for example:

```python
dataset = repository.dataset(dataset_id)
dataset.artifacts()
dataset.artifact("logical:key")
dataset.open("logical:key")
dataset.verify()
```

A consumer can therefore operate entirely on frozen artifact versions without
knowing whether data originally came from HTTP, REST, `rsync`, Git, or a derived
operation.

Dataset metadata/member enumeration must work without materializing files.

## Retention And Garbage Collection

Retention operates on repository references, not on arbitrary filesystem paths.

The initial retention model assumes every retained `ContentId` is available in
the repository's canonical local/default `BlobStore`.

Content referenced by immutable datasets must not be collected.

Policies may retain, for example:

- all observations referenced by datasets
- the latest N observations for each logical artifact
- observations newer than an age threshold
- provenance ancestors required by retained derived artifacts

Content is collectible only when no retained observation, dataset, or other
protected repository object requires it.

Garbage collection should be reachability-based and should support a grace period
before physical blob deletion.

Remote/offloaded replica tracking is deliberately deferred until a concrete use
case requires content identity to be separated from local availability. If later
introduced, an upstream mutable URL must not automatically count as a verified
replica of exact content.

## Query Architecture

The query layer operates against repository state, not raw mirror directories or
merged JSON manifests.

Useful target classes include:

- source
- logical artifact
- observation
- content
- source snapshot
- run
- operation
- dataset
- derived artifact/index

Queries should expose physical storage locations only as optional implementation
information. Logical identity, provenance, and content identity are primary.

Existing alpha query forms may remain available through compatibility parsers
while the repository-backed query API becomes authoritative.

## Manifests And Exports

Human-readable manifests remain important for transparency and interoperability,
but they are exports of authoritative repository state.

The repository may export:

- sync/run summaries
- source snapshots
- artifact manifests
- immutable dataset manifests
- provenance subsets

The current merged sync manifest may be supported as a compatibility view, but it
must not remain a second state database.

A targeted sync therefore does not require manifest merging to preserve untouched
source state; historical state already exists as repository records.

## Native Filesystem Views

Source-like trees and dataset trees may be materialized as ordinary native
filesystem views.

Default immutable materialization strategies are:

- reflinks/clones when supported
- copies as the universal fallback

Hardlinks are not a normal user-visible materialization strategy because a
writable hardlink can mutate an authoritative filesystem CAS blob. Symlinks may
be offered only as explicit disposable views whose dependence on the repository
is clear.

Materialization should:

1. resolve and validate the complete path layout before writing
2. reject traversal and collisions deterministically
3. build into a sibling temporary location
4. write self-describing dataset/snapshot metadata where appropriate
5. atomically publish the completed tree where the platform permits it

Deleting a materialized view must not affect repository correctness.

## Optional Virtual Filesystem

A read-only virtual filesystem may provide convenient file-oriented projections
of repository state. It is an optional utility, not a core storage component.

Possible views include:

- current source state
- a source snapshot
- repository state as of a specified time
- an immutable dataset
- all observations or distinct content versions of one logical artifact

Filesystem lookup conceptually resolves:

```text
view + path
   -> logical artifact/member
   -> selected observation
   -> content identity
   -> blob
```

The VFS must never become an authoritative mutation path.

## Mutable References (Deferred)

Immutable dataset/source-snapshot identity must remain separate from any future
human-friendly mutable names.

If mutable refs become necessary, introduce explicit reference records and
compare-and-swap updates rather than embedding mutable names into immutable
identity:

```text
name -> immutable target ID
```

Ref updates should require an expected previous target/generation to avoid lost
updates. Refs may act as retention/GC roots. This feature is deferred until a
concrete mutable-name use case exists.

## Replica And Availability Tracking (Deferred)

If future repositories need remote/offloaded content, model availability
separately from content identity, for example with replica records containing:

- content identity
- store/replica identity
- locator
- availability state
- last verification time
- whether eFLOUD manages the replica

The local-first implementation does not require this model. Exact content should
not be dropped from the canonical store based solely on an unverified upstream
locator.

## Policy Architecture

Policies make structured decisions and do not directly perform transport or
storage work.

Important policy areas include:

- source refresh
- inventory/reconciliation completeness
- retention and garbage collection
- naming/logical artifact mapping
- validation/integrity expectations
- dataset resolution

Policy outputs should include actions, reasons, and structured details suitable
for diagnostics and dry-run output.

## Concurrency And Locking

Repository mutation must be transactionally safe.

The default SQLite repository may use process/root locking in addition to SQLite
transactions where needed to coordinate blob installation and metadata commits.

Execution supports:

- serial execution
- bounded parallel execution for independent operations
- per-source or per-adapter concurrency limits

Concurrency must respect operation dependencies and repository transaction
boundaries.

Defaults favor correctness over maximum throughput.

## Public API Shape

The public API should distinguish mutable repository capabilities from read-only
views.

Conceptual interfaces include:

```text
Engine                 acquisition convenience facade
Repository             authoritative mutable repository service
RepositoryView         general read/query capability
ImmutableDataset       frozen read-only capability
```

Consumers that only analyze data should be able to depend on read-only
interfaces without acquiring transport or mutation capabilities.

Advanced users may compose alternate adapters, policies, metadata stores, or blob
stores without patching core repository logic.

## Default Repository Layout

The default local implementation may use a layout such as:

```text
repo/
  metadata.sqlite
  objects/
    sha256/
      ...
  views/
    ...                 # optional/disposable materializations
  exports/
    ...                 # optional manifests and portable exports
  operational/
    ...                 # HTTP cache, rate-limit state, locks, temporary state
```

Only `metadata.sqlite` and retained blob objects are authoritative repository
state. Disposable query indexes, caches, views, and exports must be reconstructable
or explicitly classified as operational state.

## Caches Versus Repository Data

The term "cache" must be reserved for state whose deletion does not destroy
semantic history or reproducibility.

Repository data includes:

- retained content objects
- observations/absences
- provenance
- source snapshots
- derived artifact records
- dataset manifests and membership

Implementation caches include:

- HTTP response cache
- rate-limit/backoff state
- disposable query indexes
- temporary materializations

If deleting an object loses provenance or prevents reconstruction of a retained
dataset, it is not a cache.

## Compatibility And Migration

The repository architecture is a migration target. Existing alpha APIs may be
adapted incrementally.

A preferred migration sequence is:

1. establish repository artifact/content/observation/provenance storage
2. normalize source membership through `SourceInventory` and generic
   reconciliation
3. make collection/fanout use the same inventory/reconciliation model
4. make derived outputs ordinary artifacts with producer identity and
   deterministic `DerivationKey` semantics
5. separate integrity expectations from actual content identity
6. remove filesystem-path assumptions from the generic blob-store contract
7. make repository queries/status/synchronization decisions authoritative and
   reduce manifests/mirror scans to compatibility views
8. formalize planner/executor/adapter interfaces around the proven semantics
9. complete validation, dataset temporal policies, retention, and GC
10. add Git and other source types only from concrete use cases
11. remove obsolete path-centric and duplicated state mechanisms
12. add safe native/virtual materializations and advanced/deferred features last

During migration:

- existing `sync(cfg)` behavior may remain through a compatibility layer
- current `EngineConfig` and `SourceDefinition` may be adapted to new source
  specifications
- current manifest consumers may use explicit compatibility serializers
- current query targets may map onto repository queries
- compatibility code must be isolated, testable, and removable

## Suggested Package Structure

Avoid excessive fragmentation. A target structure is approximately:

```text
efloud/
  engine.py
  repository.py
  sources.py
  inventory.py
  reconciliation.py
  artifacts.py
  provenance.py
  datasets.py
  derivation.py
  operations.py
  policy.py
  validation.py
  query.py
  indexing.py

  storage/
    metadata.py
    sqlite.py
    blobs.py
    filesystem.py

  transport/
    http.py
    rest.py
    rsync.py
    collection.py
    git.py

  compat/
    manifest_v1.py
```

Internal dependency direction should remain simple:

```text
primitive domain models
        |
        v
repository / storage
        |
        +----> datasets
        +----> query
        |
        v
inventory / reconciliation / derivation
        |
        v
planning / execution / adapters
        |
        v
Engine
```

Read-only dataset and query code must not depend on transport implementations.

## Design Invariants

All implementations must preserve these invariants:

- the repository is the authoritative source of semantic state
- all authoritative mutation goes through repository operations
- content objects are immutable and content-addressed
- generic blob-store semantics do not require a local filesystem path
- logical artifact identity is independent of storage paths
- repeated observations do not require duplicate content
- observations retain acquisition provenance even when content is unchanged
- absence requires successful complete coverage of the relevant source scope
- source inventory/change evidence is distinct from content identity
- expected integrity is validated against independently computed content identity
- fetched and derived artifacts use the same provenance model
- deterministic derived reuse never erases current-run provenance
- source snapshot completeness is explicit
- filesystem paths and mirrors are representations, not identity
- immutable datasets resolve to exact observations
- retained datasets protect all content required to read them
- manifests and filesystem views are derived/exported state
- deterministic inputs and repository state produce deterministic plans
- policies remain explainable
- protocol-specific details do not leak into repository semantics
- domain-specific interpretation remains outside `efloud`
- the default local implementation requires no database server
- optional filesystem projections are read-only mutation boundaries
- compatibility shims are explicit and testable
- deferred replicas, mutable refs, and recursive Merkle trees must not complicate
  the local core until concrete requirements justify them
