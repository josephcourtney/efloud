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
artifact identity, version history, provenance, and repository-backed queries.

## High-Level Architecture

The default architecture is:

```text
Sources
   |
   v
Engine / Planner / Executor
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

The major responsibility boundaries are:

- **ingestion** decides what external work to perform and records its results
- **repository** owns authoritative artifact, observation, provenance, dataset,
  validation, and retention state
- **blob storage** owns immutable bytes identified by content digest
- **metadata storage** owns identities and relationships
- **query and dataset APIs** expose read-only views over repository state
- **filesystem mirrors, manifests, exports, and virtual filesystems** are derived
  representations, not authoritative storage

## Core Invariant

All authoritative mutation occurs through the `efloud` repository API.

Filesystem projections and exported manifests are read-only or disposable
representations of repository state. External code must never be able to mutate
repository content by editing a projected path.

This invariant makes complete provenance, transactional updates, historical
reconstruction, and integrity checking possible.

## Goals

- expose a compact API for ordinary acquisition and repository use
- support heterogeneous sources behind protocol adapters
- make logical artifact identity independent of filesystem layout
- distinguish retrieval observations from immutable content
- retain complete acquisition and derivation provenance
- deduplicate identical content without losing repeated observations
- represent source state and file trees historically
- create immutable datasets from exact artifact observations
- support reproducible temporal or "as-of" dataset resolution
- make derived artifacts first-class repository objects
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
- using filesystem paths, mtimes, inodes, or hardlinks as artifact identity
- treating cache files or exported manifests as authoritative state

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
runs, operations, observations, and source snapshots.

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

A content record includes at least:

- content identifier
- byte size
- media type when known
- blob-store key

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

### Materialization

A materialization describes a physical representation of content, such as a blob
path, native checkout, or mirror path.

Materialization is not identity.

The repository must remain correct if a disposable materialized view is removed
and reconstructed from authoritative blobs and metadata.

### Provenance

Provenance records describe how observations and derived artifacts came to
exist.

A provenance record should include:

- run identifier
- operation identifier
- producer/task identity
- producer/task version when applicable
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
2. **generic encoding/container validation** - for example gzip or JSON validity
3. **domain validation** - supplied by consuming packages

A validation result should be reusable when both content identity and validator
identity/version are unchanged.

Validation must never silently mutate artifact content.

### Source Snapshot

A source snapshot records what state of a source was actually observed.

Snapshot evidence is source-specific. Examples include:

- HTTP ETag, Last-Modified value, or response digest
- REST collection enumeration identity
- `rsync` tree identity and requested path scope
- Git commit or tree identity

Snapshots must explicitly represent coverage or completeness. "Not observed"
must not be conflated with "observed absent".

For partial synchronization, the snapshot records the selectors or subtrees that
were actually examined.

### Tree Snapshot

File-tree sources may be represented by immutable Merkle-style tree snapshots.

A tree consists of entries that reference:

- content objects for files
- child tree identities for directories
- symlink targets when preserved

Tree identity is derived from canonical ordered entries and semantic tree
metadata. Local filesystem details such as inode, ctime, or local ownership must
not participate in tree identity by default.

Unchanged files and subtrees are shared between snapshots.

The original source-relative path remains recorded and can be reconstructed even
though the authoritative bytes live in the blob store.

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
- record derived output
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
provenance_edges
validations
source_snapshots
tree_snapshots
datasets
dataset_members
materializations
```

Foreign keys, unique constraints, and transactions should enforce repository
invariants where possible.

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

Blob storage rules:

- content is immutable after installation
- blob identity is derived from bytes
- writes occur through temporary files followed by atomic installation where the
  backend permits it
- identical content is stored once
- storage paths are implementation details
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
compute content identity and basic integrity
        |
        v
atomically install or reuse immutable blob
        |
        v
metadata transaction
  - content record
  - observation
  - provenance
  - source/run/operation updates
        |
        v
commit
```

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
- source snapshot state
- current artifact observations
- adapter capabilities
- refresh policies
- derived dependencies
- validation state

Planning performs no authoritative mutation or network retrieval.

Dry-run uses the same planning path as real execution.

Planning decisions must be explainable and serializable.

### Execution

Execution performs approved operations, controls concurrency, dispatches to
protocol adapters, and commits resulting repository records.

Execution must not invent unrelated work outside the approved plan except local
bookkeeping necessary to safely complete an operation.

### Protocol Adapters

Protocol-specific acquisition behavior belongs behind adapters.

Each adapter must:

- declare the source/operation types it supports
- plan or contribute protocol-specific operations
- execute the operations it owns
- emit normalized observations, source snapshots, and operation results

Initial adapters include:

- HTTP file acquisition
- REST acquisition
- `rsync` tree synchronization
- collection/fanout acquisition

Git should become a first-class adapter for versioned upstream repositories.

Adding a protocol must not require modifying repository semantics.

### Collection Sources

Collection/fanout acquisition is a first-class source pattern rather than a
special REST_BASE concept.

A collection source separates:

- enumeration of item identities
- per-item retrieval
- naming/logical artifact mapping
- reconciliation/completeness policy

REST pagination and REST fanout are implementations of this more general model.

### File-Tree Sources

For file-tree sources such as `rsync`, the adapter must report individual
artifact observations and enough tree state to construct source snapshots.

The repository must not need to rescan its own mirror later merely to rediscover
which files it previously ingested.

Source-relative paths are retained as metadata. A current source-like tree may be
materialized for convenience, but it is a derived view over repository state.

### Derived Artifacts

Derived outputs are ordinary artifacts with provenance, not a separate cache
object family.

A derived task declares:

- stable task identity
- task version
- input observations or selectors
- normalized parameters
- output artifact identities

The repository records the resulting observations and provenance edges.

Derived invalidation should prefer exact dependency identities over time-based
TTL expiration:

```text
recorded input content/observation identities
        !=
current selected input identities
```

TTL remains appropriate for deciding when an external source should be
re-observed, not for deterministic dependency invalidation.

### Indexes

Indexes are specialized derived artifacts.

Index definitions may add query-oriented metadata and convenience APIs, but
index outputs and their provenance are stored using the ordinary artifact model.

Disposable database indexes used solely to accelerate repository queries remain
implementation caches and are not repository artifacts.

## Time Model

The repository must distinguish temporal concepts rather than using one generic
timestamp.

Relevant times may include:

- request/start time
- observation time
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

## Retention And Garbage Collection

Retention operates on repository references, not on arbitrary filesystem paths.

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

Possible strategies include:

- copies, always available
- hardlinks when safe and supported
- reflinks/clones when supported
- symlinks where their semantics are acceptable

These mechanisms are optimizations only. Repository correctness must never
depend on link semantics or filesystem snapshot support.

Materialized views should be read-only to ordinary consumers where practical.
Mutation of repository state must still occur through the repository API.

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

## Policy Architecture

Policies make structured decisions and do not directly perform transport or
storage work.

Important policy areas include:

- source refresh
- retention and garbage collection
- collection reconciliation/completeness
- naming/logical artifact mapping
- validation
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
- observations
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

1. introduce repository artifact, content, observation, and provenance records
2. make existing protocol adapters populate repository state alongside current
   manifests
3. make the blob store content-addressed and authoritative
4. make source/file-tree synchronization produce artifact observations directly
5. represent derived outputs and indexes as ordinary artifacts
6. implement source and tree snapshots
7. implement immutable datasets and migrate generic catalog functionality into
   `efloud`
8. make repository queries authoritative and reduce manifests/mirror scans to
   compatibility views
9. add Git and broader collection-source support
10. remove obsolete path-centric and duplicated state mechanisms

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
  artifacts.py
  provenance.py
  datasets.py
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
- logical artifact identity is independent of storage paths
- repeated observations do not require duplicate content
- observations retain acquisition provenance even when content is unchanged
- fetched and derived artifacts use the same provenance model
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
