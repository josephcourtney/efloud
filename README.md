# efloud

`efloud` is a local-first, versioned data-ingestion and artifact-repository library.

It acquires data from heterogeneous upstream sources, stores immutable content by
digest, records observations and provenance, validates content, and freezes exact
repository state into reproducible datasets for downstream analysis.

The project is pre-1.0. ADR-0010 has selected a clean-break public API and complete
removal of alpha backwards compatibility. The target contract is documented in
[`docs/api.md`](docs/api.md); `STATUS.md` records how much of that cutover is
implemented today.

## Core model

The central distinction is:

```text
logical artifact -> observation -> immutable content
```

A logical artifact names something whose bytes may change over time. Each
successful acquisition records an observation and points to a content-addressed
object. Repeated observations of unchanged bytes preserve acquisition history
without duplicating content.

The repository also records:

- immutable source-definition revisions;
- runs and operations with explicit lifecycle state;
- normalized source inventories and source/tree snapshots;
- content validation evidence;
- provenance for fetched and derived artifacts;
- immutable dataset membership and detached manifests;
- safe materialization/export and maintenance evidence.

The default local repository uses SQLite metadata and a filesystem
content-addressed store. Those are implementation defaults, not public semantic
requirements.

## What Efloud is for

Typical uses include:

- acquiring reference datasets while retaining historical observations;
- combining HTTP, REST/collection, and `rsync` sources behind one repository
  model;
- inspecting exactly what was observed, when, and from which source revision;
- validating downloaded content before advancing source state;
- reusing identical content and deterministic derived outputs without losing
  provenance;
- freezing exact observations into reproducible datasets;
- exporting a detached consumer handoff that does not require Efloud SQLite
  internals;
- operating offline after acquisition.

Efloud is not a desktop sync application, workflow scheduler, distributed compute
framework, or domain-specific scientific database.

## Architecture

The canonical path is:

```text
Sources
  -> adapters
  -> planner / reconciler / executor
  -> Repository
       -> MetadataStore
       -> BlobStore
```

The repository is authoritative. Filesystem views, caches, manifests, CLI status
payloads, and exported trees are derived or operational state.

Important invariants include:

- content is immutable and identified from the bytes Efloud stores;
- logical artifact identity is independent of filesystem/storage layout;
- absence requires successful complete source evidence;
- repeated unchanged observations preserve provenance without duplicate bytes;
- validation is immutable evidence and never silently changes content;
- datasets resolve to exact observations;
- exported/materialized trees cannot mutate authoritative content;
- recovery never invents successful operations or complete snapshots.

See [`DESIGN.md`](DESIGN.md) for the normative architecture.

## Target public API

The clean-break API intentionally exposes a much smaller ordinary surface:

```text
Repository
Engine
Source
HttpSource / RestSource / RsyncSource / CollectionSource
SyncRequest
SyncResult
DatasetSpec
Dataset
DatasetManifest
EfloudError
```

The current alpha implementation has not completed this cutover yet; the snippets
below describe the target interface rather than promising that every name is
currently available.

### Repository and acquisition

```python
with Repository.create("repository") as repo:
    engine = Engine(
        repo,
        sources=[
            HttpSource(
                id="example-json",
                url="https://example.test/data.json",
            )
        ],
    )
    result = await engine.sync()
```

`Engine` owns planning/acquisition. `Repository` owns durable semantic state.
Storage configuration is separate from per-run `SyncRequest` intent.

### Read-only access

```python
with Repository.open("repository", mode="r") as repo:
    state = repo.artifacts.latest("source:example-json")
```

One public repository type supports explicit read-only or writable modes. The
broad current `RepositoryView` and separate `ReadOnlyRepository` class are
transitional implementation shapes, not the target API.

### Reproducible datasets

```python
with Repository.open("repository", mode="r") as repo:
    dataset = repo.datasets.resolve(spec)

with Repository.open("repository", mode="rw") as repo:
    frozen = repo.datasets.freeze(spec)
    manifest = frozen.export("export")
```

`DatasetSpec` represents selection intent; `Dataset` represents exact immutable
membership; `DatasetManifest` is the detached portable representation. `resolve`
is non-persistent, while `freeze` records membership.

## Source extensibility

The target source model is open rather than based on a permanent closed
`SourceKind` enum. Built-in protocol-specific source types provide strong typing,
while a third-party source can identify a namespaced registered adapter without a
core Efloud change.

Adapters emit normalized inventory/acquisition evidence and do not mutate
repository metadata directly. This preserves one repository/reconciliation model
across HTTP, REST, rsync, collections, and future protocols.

## Derived artifacts and validation

Derived outputs are ordinary repository artifacts with provenance. Deterministic
work may reuse existing content when its declared dependency semantics permit it,
but current-run output observations are still recorded.

Validation is layered: storage integrity, source integrity expectations, generic
encoding/container validation, and domain validation supplied by consumers.
Evidence is reusable by content and validator identity/version.

## Detached exports

Dataset exports carry exact membership, observation/content identity, source and
snapshot evidence, constraints, and canonical export paths. Export publication
validates the full layout, stages and verifies content, never overwrites an
existing destination, and publishes atomically where supported.

A detached consumer can verify exported bytes without reading Efloud SQLite.

## Maintenance and recovery

Writable local repositories use exclusive writer coordination; read-only access
has no mutation authority. Audit is non-repairing. Cleanup is reachability-based,
defaults to dry-run behavior, and preserves all protected historical references.
Recovery marks abandoned lifecycle state failed rather than inventing completion;
a new Engine run performs retries through normal reconciliation.

The coordination/storage mechanisms may change for future remote or distributed
repositories without changing ordinary repository semantics.

## Backwards compatibility

The next API deliberately provides **no alpha backwards compatibility**.

The implementation plan removes:

- deprecated `sync(cfg)` and the compatibility-oriented `EngineConfig` shape;
- merged sync manifests and mirror-state projections;
- historical import/recording compatibility modules;
- old path-resolution, query/status/health/summary facades;
- source-alias/adoption migration helpers;
- TTL-cache compatibility and old import aliases;
- schema-v1/v2 in-place repository upgrades.

Old repository roots are not a supported runtime input after the cutover. They may
be recreated/reacquired or handled by a one-off external converter if one is ever
needed. Downstream packages such as BVP must migrate to the new repository/dataset
boundary rather than preserving Efloud compatibility code.

See [`docs/compatibility-inventory.md`](docs/compatibility-inventory.md) for the
finite removal inventory.

## Future extensions

The target API is designed so currently proposed advanced features remain additive
or internal:

- new protocols add source/adapter types without changing repository semantics;
- plugin discovery can populate the existing adapter/validator registries;
- alternate blob or metadata stores remain behind `Repository`;
- recursive Merkle trees can change tree representation without changing dataset
  workflows;
- mutable refs can map names to immutable IDs explicitly;
- replica tracking can model availability separately from content identity;
- distributed coordination can replace local writer locks behind writable
  repository semantics.

These features remain deferred until concrete requirements justify them.

## Development

The project uses `uv` and `just`.

```bash
uv sync
uv run just check
```

The repository quality gate covers syntax, Ruff format/lint, static typing, import
architecture, tests, and coverage across the supported Python range.

## Project status

The repository-centered architecture is substantially implemented, including
canonical acquisition/persistence, validation/provenance, snapshots, immutable
datasets, detached exports, writer coordination, audit/cleanup, and recovery.

The active work is now the clean API cutover described in ADR-0010, migration of
canonical internals to that boundary, complete deletion of compatibility and old
schema support, and then final durability/export/CI/BVP acceptance.

See [`STATUS.md`](STATUS.md), [`PLAN.md`](PLAN.md), and [`TODO.md`](TODO.md) for the
current handoff and implementation sequence.
