# DESIGN

> This document is normative. It defines the intended architecture, public
> semantic boundary, and invariants for `efloud`. `PLAN.md` defines sequencing;
> `TODO.md` defines immediate work; ADR-0010 records the decision to make a clean
> pre-1.0 API break and remove alpha compatibility completely.

## Intent And Scope

`efloud` is a versioned data-ingestion and artifact-repository library.

It acquires external data through heterogeneous protocols, records what was
observed and how it was obtained, stores immutable content efficiently, tracks
provenance and integrity, and freezes exact selections of artifact observations
into reproducible datasets.

The repository, not a filesystem mirror, cache, merged sync manifest, or exported
view, is the authoritative model of state.

The design preserves these capabilities:

- simple programmatic acquisition
- HTTP, REST, collection/fanout, and `rsync` sources
- deterministic planning and explainable execution
- inspectable and read-only repository access
- offline use after acquisition
- provenance-aware derived artifacts and indexes
- validation and integrity evidence
- immutable datasets and detached exports
- safe maintenance and crash recovery

while keeping path layout, storage implementation, protocol mechanics, and
coordination mechanisms behind semantic interfaces.

## High-Level Architecture

```text
Declarative Sources
        |
        v
Source adapters  ----> normalized inventory/acquisition evidence
        |
        v
Planner / Reconciler / Executor
        |
        v
internal repository writer
        |
        v
Repository
   |-----------------------------|
   |                             |
MetadataStore                 BlobStore
(SQLite default)              (filesystem CAS default)
   |                             |
   |-----------------------------|
                 |
                 v
        immutable repository state
                 |
      +----------+-----------+----------------+
      |                      |                |
 typed reads              datasets       maintenance
      |                      |
      +----------+-----------+
                 |
           detached exports
```

`Repository` is the durable semantic boundary. `Engine` owns acquisition
orchestration. Neither SQLite nor filesystem CAS layout is part of the ordinary
public API.

Responsibility boundaries are:

- **sources** describe external origins declaratively;
- **source adapters** understand protocols and emit normalized evidence;
- **planning/reconciliation** decides work from caller intent and repository state;
- **execution** coordinates adapters, validation, derivation, and authoritative
  recording;
- **repository** owns artifact, observation, content, provenance, source snapshot,
  dataset, validation, retention, and lifecycle semantics;
- **metadata storage** owns identities and relationships;
- **blob storage** owns immutable bytes by content identity;
- **datasets/exports** provide reproducible consumer handoff;
- **materialized views, caches, and CLI presentation** are derived or operational
  state only.

## Core Invariants

All authoritative mutation occurs through Efloud-controlled repository writer
operations. Ordinary users and extensions do not assemble run/operation/provenance
records manually.

The repository must never commit metadata that references unavailable content. An
interrupted operation may leave an unreferenced blob; reachability-based cleanup
may remove it later.

Content objects are immutable and content-addressed. Logical artifact identity is
independent of content identity and physical storage location.

Absence is evidence, not a default assumption. An item may be recorded absent only
when successful source evidence establishes complete coverage of the relevant
scope.

Repeated observation of unchanged bytes preserves observation/provenance history
without duplicating content.

Filesystem paths, caches, mirrors, exports, refs, replicas, and storage keys never
participate in artifact or content identity unless explicitly modeled as source
data.

## Goals

- expose a small, discoverable ordinary Python API;
- keep advanced composition possible without making internal records root-level
  contracts;
- support heterogeneous and future source protocols without modifying repository
  semantics;
- normalize source membership, completeness, change evidence, and reconciliation;
- retain complete acquisition and derivation provenance;
- distinguish upstream assertions from independently computed content identity;
- preserve historical observations and explicit source snapshots;
- create exact immutable datasets with distinct specification, observation
  membership, and content-equivalence identities;
- make deterministic derived work reusable without erasing current-run provenance;
- support storage and metadata backends that are not filesystem/SQLite specific;
- make planning deterministic and policy decisions explainable;
- keep domain-specific interpretation outside Efloud;
- permit future refs, replicas, Merkle trees, plugin discovery, and distributed
  coordination without redesigning ordinary acquisition/dataset workflows.

## Non-Goals

- desktop file synchronization;
- workflow scheduling or general distributed compute;
- application-specific scientific/business interpretation;
- requiring a server database for ordinary local use;
- making FUSE/WinFsp a core dependency;
- exposing path, inode, mtime, hardlink, cache key, or SQLite row identity as
  semantic identity;
- retaining alpha API/import/repository-format compatibility;
- preserving old mirror/manifest/query behavior merely because an old caller uses
  it;
- requiring replicas, mutable refs, recursive Merkle trees, chunked storage, or
  plugin discovery before concrete requirements justify them.

# Public API Design

The public API describes user intent and repository semantics rather than the
architecture used to implement them.

## Ordinary package surface

The package root should expose approximately 10-15 ordinary concepts:

```text
Repository
Engine
Source
HttpSource / RestSource / RsyncSource / LocalSource / CollectionSource
SyncRequest
SyncResult
DatasetSpec
Dataset
DatasetManifest
EfloudError (+ deliberate public subclasses)
__version__
```

Planner/executor records, low-level identifier classes, storage implementations,
registries, adapter evidence classes, validation service internals, and repository
writer primitives live in focused advanced/internal modules and are not package-root
promises.

## Repository lifecycle

One public `Repository` type represents durable access. Creation and opening are
explicit:

```python
with Repository.create("repository") as repo:
    ...

with Repository.open("repository", mode="r") as repo:
    ...

with Repository.open("repository", mode="rw") as repo:
    ...
```

`mode="r"` guarantees non-mutating access. `mode="rw"` uses whatever writer
coordination the selected backend requires. A second public `ReadOnlyRepository`
type is unnecessary.

The repository `location` is a semantic location/configuration input. A string or
`Path` identifies the default local backend today, but the public contract must not
assume every future repository is a local directory.

Repository functionality should be discoverable through semantic facades rather
than one extremely broad method list, for example:

```text
repo.artifacts
repo.sources
repo.runs
repo.datasets
repo.provenance
repo.maintenance
```

Exact naming may evolve before implementation is complete, but the capability
boundary is normative: ordinary repository access exposes reads, dataset operations,
and deliberate maintenance; executor-facing mutation primitives remain internal.

The current broad `RepositoryView` protocol is not a public target. Internal
components depend on narrow capabilities appropriate to their work.

## Engine and synchronization

`Engine` owns planning and acquisition orchestration:

```python
with Repository.create("repository") as repo:
    engine = Engine(repo, sources=[...])
    result = await engine.sync()
```

`Engine` may accept explicit adapter, validator, policy, collection, and execution
composition for advanced callers. Collection behavior is a supported focused
extension contract rather than a package-root type. Repository/storage configuration remains separate from
per-run synchronization intent.

`EngineConfig` is not part of the target model. A single object must not combine
repository paths, compatibility output locations, cache housekeeping, aliases,
derived tasks, policies, and per-run flags.

`SyncRequest` contains per-run intent such as selected source IDs, refresh intent,
derived work inclusion, dry-run, and concurrency limits. Planning is non-mutating
and uses the same semantic path as execution.

`SyncResult` is the one ordinary result. It exposes direct semantic outcome: overall
success, run identity when present, produced observations/artifacts, skipped/failed
work, and structured diagnostics. Detailed plans and per-operation execution records
may remain available from `efloud.planning`/advanced APIs but are not required to
answer normal success/failure questions.

## Sources

`Source` is an open semantic contract. Every source has a stable source ID and a
namespaced adapter identity plus adapter-specific declarative configuration.

Built-in sources use protocol-specific types so invalid cross-protocol
combinations are unrepresentable:

```python
HttpSource(id="example", url="https://example.test/data.json")
RsyncSource(id="tree", url="rsync://example.test/module", paths=("subset/",))
LocalSource(id="analysis-input", path="inputs/model.json", artifact_key="analysis:model")
```

There is no public closed `SourceKind` enum and no monolithic source dataclass full
of unrelated optional HTTP/rsync/collection fields.

A third-party source can identify a registered adapter without modifying Efloud
core. Built-in source classes are conveniences over the same open adapter model.

Source definitions describe facts/configuration. Execution state belongs in runs,
operations, inventories, observations, and source snapshots. Protocol-specific
fields stay inside the source type/adapter that understands them.

## Dataset API

A dataset is immutable once resolved, so the public type is simply `Dataset`.

`DatasetSpec` is an immutable, compositional intensional selection description. It
can express exact observations, latest/as-of artifact selection, source/snapshot
selection, prefix/role/tag filters, and coherence constraints without requiring
every selector implementation class at the package root.

Resolution and persistence use distinct verbs:

```python
with Repository.open("repository", mode="r") as repo:
    dataset = repo.datasets.resolve(spec)

with Repository.open("repository", mode="rw") as repo:
    dataset = repo.datasets.freeze(spec)
```

`resolve` returns exact immutable membership without recording it. `freeze` records
the exact membership/specification association and requires write mode.

A dataset exposes exact members and content access:

```text
dataset.id
dataset.specification_id
dataset.content_identity
dataset.members()
dataset.member(key)
dataset.open(key)
dataset.verify()
```

`DatasetManifest` names the canonical detached portable representation, not an
internal intermediate resolution object. `Dataset.export(...)` creates a safe
materialized/detached handoff and returns or writes its manifest.

## Time and errors

Public temporal arguments use timezone-aware `datetime`. Repository observation
time is the default temporal basis; upstream time is separate source evidence.
Internal storage may use numeric timestamps.

Unbounded collections use `None` rather than magic negative limits.

Ordinary domain failures derive from `EfloudError`, with stable subclasses for
repository/open/schema, acquisition/execution, dataset resolution/constraints,
verification/integrity, coordination/busy state, and export/materialization as
needed. Normal callers should not need to parse generic exception strings.

# Domain Model

## Logical artifact

A logical artifact is an opaque stable key naming something whose content may
change over time, for example:

```text
reference:taxonomy:nodes
weather:noaa:station:KBDR:daily
pdb:8ef4:mmcif
```

Artifact identity never depends on absolute paths, cache roots, inode identity,
retrieval time, or storage backend.

## Content object

A content object is an immutable byte sequence identified by digest, initially:

```text
sha256:<hex digest>
```

Its semantic record includes content ID, byte size, and optional media type. Local
path, bucket key, or replica locator is storage information, not content identity.
Identical bytes reuse one content object across sources, artifacts, and repeated
observations.

## Observation and absence

An observation states that a logical artifact was observed with a particular
content object under particular acquisition circumstances. It includes artifact,
content, source when applicable, run/operation, repository observation time,
source-relative/upstream locator information, source-provided version/time evidence,
and transport/source metadata.

Repeated unchanged acquisition therefore yields one artifact, one content object,
and multiple observations.

An absence record states that a logical artifact was established absent within a
successfully observed source scope. It carries run/operation/source evidence.
Incomplete or failed source coverage may never create authoritative absence outside
what was proven.

## Source inventory, change evidence, and integrity expectations

`SourceInventory` is the normalized evidence of source membership and coverage.
Semantically it separates:

- inventory observation time;
- scope and completeness;
- item identity/artifact mapping;
- source locator/path;
- optional change/version tokens;
- optional upstream integrity expectations;
- source-specific metadata.

HTTP may produce a one-item complete inventory; rsync produces path-scoped tree
inventory; collection enumeration produces item membership; Git may eventually
produce commit/tree evidence.

Change tokens such as ETags or upstream revisions may optimize refresh decisions but
are not content identity.

An `IntegrityExpectation` is an upstream assertion. Efloud computes actual content
identity from stored bytes and records comparison as validation evidence:

```text
upstream assertion -> IntegrityExpectation
stored bytes        -> ContentId
comparison          -> ValidationResult
```

## Provenance and lifecycle

Every acquisition or derivation operation has a stable namespaced producer identity
and version. Runs and operations have explicit lifecycle states:

```text
operation: running -> succeeded | failed | cancelled
run:       running -> succeeded | partial | failed | cancelled
```

Plans/dry-runs do not create persisted planned operations simply because they are
inspected. Invalid transitions are rejected.

Provenance relates output observations to their run, operation, producer,
source/upstream evidence, normalized parameters, and input observations. Fetched and
derived artifacts use the same provenance model, forming a directed graph.

## Validation

Validation results are immutable evidence associated with content identity and
validator identity/version. Layers include storage integrity, source expectations,
generic encoding/container validation, and domain validators supplied by consumers.

Validation evidence may be reused when content and validator identity/version are
unchanged. Validators never silently mutate content.

## Source and tree snapshots

A source snapshot records what state of a source was actually observed, including
scope/completeness and source-specific evidence. "Not observed" is distinct from
"observed absent". Partial synchronization records only what was examined.

File-tree sources use immutable canonical tree snapshots. The initial
representation may be flat; a future recursive Merkle representation may share
unchanged subtrees. Tree identity derives from canonical semantic entries, not local
inode/ctime/absolute-path details.

Representation versioning may preserve repository history created after the clean
break, but this is an internal repository evolution concern rather than a promise to
open alpha repositories.

# Internal Execution Architecture

## Planning and reconciliation

Planning combines caller intent, source definitions, adapter capabilities, repository
snapshots/observations, policy, derived dependencies, and validation state into a
deterministic typed plan. Planning performs no acquisition or authoritative
mutation. Dry-run follows the same planning path.

Generic reconciliation compares normalized successful inventory with relevant
repository state and classifies items as new, changed, unchanged, or absent within
proven complete scope. Protocol adapters do not invent independent absence models.

## Execution and internal writer

Execution performs approved operations, controls concurrency/dependencies, invokes
adapters/derived tasks/validators, and records authoritative results through an
internal writer capability.

The writer capability may expose operations such as start/finish run and operation,
store/observe content, record absence, provenance, validation, and snapshots. These
are internal transactional primitives, not ordinary `Repository` methods for
application code.

## Adapter contracts

A source adapter has namespaced/versioned identity and capabilities. Dispatch uses
adapter identity/capability rather than a closed protocol enum.

Adapters receive only the declarative source, planned intent/evidence, and narrow
read capabilities they need. They emit normalized inventory/acquisition evidence and
do not write repository metadata.

Direct registration is sufficient initially. Future lazy plugin discovery may
populate the same registry without changing source or Engine semantics.

Collection/fanout is a first-class source pattern separating enumeration,
per-item fetch, artifact naming, and completeness/reconciliation. There is no
special permanent `REST_BASE` repository concept.

## Derived artifacts and indexes

Derived outputs are ordinary artifacts with provenance. A deterministic task
declares stable task identity/version, deterministic flag, dependency semantics
(`content` or `observation`), normalized parameters, exact inputs, and declared
outputs.

A canonical `DerivationKey` combines those semantics. Content-dependent work may
reuse results across byte-identical observations; observation-dependent work may
not. Reusing content still creates a current-run output observation so provenance
remains complete.

Indexes that are semantically derived data use the same derivation model. Disposable
database indexes used only to accelerate queries remain implementation caches.
Wall-clock TTL is appropriate for external refresh policy, not deterministic derived
identity.

# Repository And Storage

## Semantic repository service

Repository reads include artifact/current/history access, content opening and
verification, provenance, sources/snapshots/runs, validation evidence, datasets,
and deliberate maintenance reports.

The ordinary public service does not expose arbitrary CRUD or physical storage
placement.

## Metadata store

The default metadata implementation is SQLite. Universal structure belongs in
relational entities such as sources/revisions, runs, operations, artifacts, content,
observations/absences, provenance edges, validations, source/tree snapshots,
datasets/members, and materializations. Protocol/domain-specific details remain
structured metadata rather than transport-specific relational schema proliferation.

Foreign keys, uniqueness, lifecycle checks, and transactions enforce invariants
where practical.

A future PostgreSQL or other metadata backend must preserve repository semantics.

## Blob store

The default blob store is a portable content-addressed filesystem layout. The
semantic contract is storage-location independent:

```text
put bytes/path -> ContentRef
open(ContentId)
contains(ContentId)
verify(ContentId)
delete(ContentId)
```

A local file descriptor/path is an optional backend capability, useful for reflink
optimization, not a requirement of repository/dataset code.

Blob rules:

- immutable after installation;
- identity derived from bytes;
- idempotent put by content identity;
- successful put is immediately readable;
- atomic installation where supported;
- identical content stored once;
- backend paths/keys excluded from semantic identity.

Chunk-level deduplication is deferred until measurements justify it.

## Transactional ingestion

The semantic ingestion order is:

```text
acquire/stage bytes
      -> compute actual ContentId
      -> validate required expectations
      -> install/reuse immutable content
      -> metadata transaction
           content + observation + provenance + validation
           + source/snapshot/run/operation updates
      -> commit
```

Failed required integrity must not advance source state as successful. Alternate
backends preserve equivalent guarantees.

# Datasets, Exports, And Materialization

A dataset separates intensional specification from exact resolved membership.
Three identities remain distinct:

- specification identity: selection intent;
- dataset identity: exact observation membership;
- content identity: semantic membership plus content IDs.

Temporal/coherence constraints may require latest-before, same run, maximum
observation skew, complete source snapshots, or validator evidence. Resolution never
infers absence from incomplete coverage.

Detached manifests contain canonical exact members, source/snapshot evidence,
constraint results, paths, and a digest of the canonical envelope. They exclude
local blob paths and mutable export timestamps. The digest establishes integrity,
not signer authenticity.

Materialization/export must:

1. resolve and validate complete path layout before writing;
2. reject traversal, reserved paths, collisions, and unsafe destination overlap;
3. stage into a sibling/private temporary location;
4. verify staged content;
5. never overwrite an existing destination;
6. atomically publish where supported.

Preferred immutable materialization is native reflink/clone when supported, with
copy as universal fallback. Hardlinks are not a normal user strategy because they
could mutate authoritative filesystem-CAS bytes. Explicit symlink export may point
only into private exported content, not authoritative CAS.

Deleting a materialized view never affects repository correctness.

# Query And Inspection

Python code uses typed repository/domain reads. A string target/locator grammar may
exist for CLI inspection, but it is a presentation layer over typed APIs rather than
a repository dependency or ordinary Python contract.

Queries prioritize logical identity, provenance, snapshots, content identity, and
datasets. Physical storage locations are optional implementation diagnostics.

# Maintenance, Retention, And Recovery

Retention and cleanup operate on repository references, not arbitrary filesystem
paths. Content is collectible only when no retained observation, dataset, tree,
validation/provenance/materialization requirement, or other protected record needs
it.

Safe cleanup is reachability-based, supports a grace period, fails closed on
invalid metadata, and defaults to dry-run/reporting before deletion.

Writer coordination is a backend capability. The default local repository uses an
exclusive process/root lease in addition to SQLite transactions where needed.
Read-only opens do not acquire writer authority. Future distributed coordination may
replace this mechanism without changing ordinary `Repository` semantics.

Crash recovery may mark abandoned running lifecycle records failed/cancelled as
defined, but it never invents successful completion, replays unknown transport side
effects, or upgrades incomplete source evidence to complete. Retry occurs through a
new normal Engine run.

Historical pruning of valid observations is deferred until a concrete retention
policy is required.

# Future Extensions

## New protocols and plugin discovery

A new source protocol adds a source type/adapter and normalized evidence; it does not
change repository semantics or a core source enum. Plugin discovery, if later
needed, is another registry population mechanism.

## Alternate/remote storage

Alternate blob stores and metadata stores remain behind repository semantics.
`Repository.open/create` must not encode local filesystem or SQLite as universal
requirements.

## Mutable references

If human-friendly mutable names become necessary, model them explicitly as
compare-and-swap references:

```text
name -> immutable target ID
```

Refs remain separate from immutable identity and may become retention roots.

## Replica and availability tracking

If exact content can exist across/off the canonical local store, model availability
separately from `ContentId`: replica/store identity, locator, availability state,
verification time, and management ownership. An upstream mutable URL is not a
verified replica of exact content.

## Recursive Merkle trees

Recursive tree representation may replace/augment flat trees for scale while
preserving tree semantics and representation-versioned clean-break history. It does
not change Dataset or ordinary Repository APIs.

## Distributed coordination

Multi-machine writers may require remote metadata transactions, leases, or a
coordination service. Those mechanisms remain behind write-mode repository and
Engine execution contracts.

# Compatibility Policy

There is no maintained backwards compatibility for the alpha API or old repository
format.

The clean-break implementation deletes rather than preserves:

- deprecated `sync(cfg)` behavior and compatibility `EngineConfig` shape;
- merged sync manifest and mirror-state models/projections;
- old path resolution/materialization lookup;
- compatibility importers/recorders/extension adapters;
- old query/status/health/summary presentation facades;
- source alias/adoption migration helpers;
- TTL cache compatibility;
- import aliases retained solely for old callers;
- schema-v1/v2 in-place migration support.

Only the clean-break repository schema is supported by normal runtime opening.
Older repositories may be recreated/reacquired or handled by a one-off external
converter; such a converter is not part of the maintained Efloud runtime.

Downstream projects migrate to the clean API. A downstream legacy caller is not a
reason to preserve duplicate representations or execution paths.

# Suggested Package Structure

Avoid excessive fragmentation, but keep public/advanced/internal responsibilities
clear. A target shape is approximately:

```text
efloud/
  __init__.py          # small ordinary facade
  engine.py
  repository.py
  sources.py
  datasets.py
  errors.py

  inventory.py
  reconciliation.py
  derivation.py
  validation.py
  policy.py
  planning.py
  maintenance.py

  storage/
    metadata.py
    sqlite.py
    blobs.py
    filesystem.py

  adapters/
    http.py
    rest.py
    rsync.py
    collection.py
    git.py             # only when required
```

There is no permanent `compat/` package.

Internal dependency direction remains approximately:

```text
primitive semantic models
        |
        v
storage + internal repository capabilities
        |
        +----> public Repository reads/datasets/maintenance
        |
        v
inventory / reconciliation / derivation / validation
        |
        v
planning / execution / adapters
        |
        v
Engine
```

Read-only repository and dataset code must not depend on transport implementations.

# Design Invariants

All implementations must preserve:

- repository state is authoritative;
- ordinary public API is semantic and small;
- authoritative mutation uses internal repository writer operations;
- read mode cannot mutate repository state;
- content is immutable and content-addressed;
- storage location is not content identity;
- artifact identity is independent of storage paths;
- repeated observations preserve provenance without duplicate content;
- absence requires successful complete evidence for the relevant scope;
- source inventory/change evidence is distinct from content identity;
- integrity expectations are tested against independently computed content;
- fetched and derived artifacts share one provenance model;
- deterministic reuse never erases current-run provenance;
- source snapshot completeness is explicit;
- protocol-specific details do not leak into repository semantics;
- sources are extensible without changing a closed core enum;
- datasets resolve to exact observations and distinguish spec/membership/content
  identity;
- retained datasets protect all required content/evidence;
- manifests/materialized views are exports, never authority;
- deterministic inputs and repository state produce deterministic plans;
- policy decisions remain explainable;
- default local use requires no database server;
- alternate storage/coordination remains possible behind repository semantics;
- future refs/replicas/Merkle trees extend the model without changing ordinary
  acquisition/dataset workflows;
- alpha compatibility code and historical repository upgrades are not retained;
- domain-specific interpretation remains outside Efloud.
