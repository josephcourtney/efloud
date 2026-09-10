# Target public API contract

This document defines the implemented clean-break public API selected by ADR-0010.
`STATUS.md` records the current verification focus and remaining acceptance work.

## Principles

The ordinary API describes user intent and repository semantics, not planner,
executor, SQLite, blob-placement, compatibility, or migration machinery.

The package root should expose approximately 10-15 ordinary concepts. Advanced
contracts remain available from focused submodules, but importing `efloud` should
present one obvious path for acquisition, repository reads, reproducible datasets,
and exports.

The public API is allowed to break alpha callers and does not preserve historical
repository schemas.

## Ordinary package surface

The intended package-root concepts are:

- `Repository`
- `Engine`
- `Source`
- built-in typed source constructors/types such as `HttpSource`, `RestSource`,
  `RsyncSource`, `LocalSource`, and `CollectionSource`
- `SyncRequest`
- `SyncResult`
- `DatasetSpec`
- `Dataset`
- `DatasetManifest`
- the small public Efloud exception hierarchy
- `__version__`

Low-level repository IDs, planner/executor records, storage implementations,
registries, validation service internals, maintenance result internals, and adapter
evidence types are not package-root promises.

## Repository

`Repository` is the durable semantic access point. Creation and opening are
explicit operations:

```python
with Repository.create("repository") as repo:
    ...

with Repository.open("repository", mode="r") as repo:
    ...

with Repository.open("repository", mode="rw") as repo:
    ...
```

`mode="r"` guarantees non-mutating access. `mode="rw"` acquires the writer
coordination required by the selected backend. There is no separate public
`ReadOnlyRepository` class.

The `location` accepted by `create`/`open` is not semantically restricted to a
filesystem `Path`. The default implementation is local SQLite plus filesystem CAS,
but future configured or remote repository backends must be able to fit behind the
same repository contract.

Repository functionality should be grouped into discoverable semantic facades,
for example:

```text
repo.artifacts
repo.sources
repo.runs
repo.datasets
repo.provenance
repo.maintenance
```

These expose domain-level reads and deliberately supported maintenance operations.
Executor-facing methods such as starting runs/operations, ingesting bytes, recording
absence, publishing snapshots, and recording validation are internal writer
capabilities and are not ordinary public methods.

Broad implementation protocols such as the current `RepositoryView` are internal.
Components should depend on the narrowest read capability they require.

## Acquisition and Engine

`Engine` owns acquisition orchestration. It receives an opened repository and a set
of declarative sources:

```python
with Repository.create("repository") as repo:
    engine = Engine(repo, sources=[...])
    result = await engine.sync()
```

Advanced callers may supply explicit adapter, validator, policy, or execution
configuration through focused arguments/configuration objects. Repository storage
configuration is separate from per-run synchronization intent.

`EngineConfig` is not part of the target API. Legacy mirror/cache/log paths,
manifest filenames, compatibility output settings, aliases, and housekeeping flags
do not belong in one canonical engine configuration object.

`SyncRequest` contains per-run intent such as selected sources, dry-run, derived
work inclusion, refresh intent, and concurrency limits. Planning remains
non-mutating and may be exposed through `Engine.plan(request)`; detailed plan and
operation types live in `efloud.planning`, not the package root.

`SyncResult` is the single ordinary result. It reports semantic outcome directly,
including run identity when one exists, produced observations/artifacts, skipped or
failed sources/operations, and structured diagnostics. Callers should not have to
traverse `EngineSyncResult -> SyncExecutionResult -> OperationExecutionResult` or a
compatibility result wrapper for ordinary success/failure information.

## Sources

`Source` is an open semantic protocol rather than a closed enum hierarchy. A source
has a stable source ID and a namespaced adapter identity plus adapter-specific
configuration.

Built-ins provide strongly typed protocol-specific source classes so invalid
cross-protocol combinations are unrepresentable:

```python
HttpSource(
    id="example-json",
    url="https://example.test/data.json",
)

RsyncSource(
    id="reference-tree",
    url="rsync://example.test/module",
    paths=("subset/",),
)

LocalSource(
    id="analysis-input",
    path="inputs/model.json",
    artifact_key="analysis:model",
    media_type="application/json",
)
```

There is no public `SourceKind` enum and no single `SourceDefinition` dataclass with
HTTP-, rsync-, collection-, and compatibility-specific optional fields.

A third-party source type can identify a registered adapter without requiring a
change to Efloud core. Built-in source classes are conveniences over the same open
contract, not privileged repository concepts.

## Dataset API

A dataset is always immutable once resolved. The public names therefore omit the
redundant `Immutable` prefix.

`DatasetSpec` is an immutable, compositional description of selection intent. It
supports exact observations, latest/as-of artifact selection, source/snapshot
selection, role/tag/prefix filtering, and coherence constraints. Individual
selector implementation classes do not need to dominate the package root.

Public temporal inputs use timezone-aware `datetime`. Repository observation time
remains the default temporal basis unless another basis is explicitly selected.
Internal persistence may use numeric timestamps.

Resolution and persistence use distinct verbs:

```python
with Repository.open("repository", mode="r") as repo:
    dataset = repo.datasets.resolve(spec)   # exact but not recorded

with Repository.open("repository", mode="rw") as repo:
    dataset = repo.datasets.freeze(spec)    # exact and recorded
```

Both return `Dataset`. A dataset exposes exact immutable members and content access:

```python
dataset.id
dataset.content_identity
dataset.members()
dataset.member("logical:key")
dataset.open("logical:key")
dataset.verify()
```

`DatasetManifest` is reserved for the canonical detached portable representation.
It contains exact observation/content membership, source/snapshot evidence,
constraint results, logical export paths, and a canonical envelope digest. It never
contains local CAS paths.

Export is a dataset operation rather than requiring ordinary callers to construct a
separate materializer service:

```python
manifest = dataset.export("export")
manifest.verify("export")
```

Dry-run/planning and explicit copy/reflink/symlink strategies remain available as
advanced export options. Publication preserves the existing safety invariants:
validate layout first, stage completely, verify bytes, never overwrite an existing
destination, then publish atomically where supported.

## Queries and inspection

Python callers use typed repository/domain methods. The old string query grammar
(`artifact:<key>`, locators, merged status payloads) is not a core Python API.
A CLI or inspection utility may implement a query language on top of typed
repository reads without making that parser a repository dependency.

Collection methods use conventional values such as `limit=None` for unbounded
history; negative magic sentinels such as `limit=-1` are not part of the target API.

## Extension contracts

Advanced extension points remain explicit and narrow. `efloud.collections` is a
supported advanced module for `CollectionDefinition`, `CollectionContext`,
`CollectionItem`, and `CollectionInventory`; ordinary callers do not need those
types unless defining dynamic collection behavior. Public `Engine(..., collections=...)`
passes those definitions into the canonical planner/executor without exposing the
repository writer.

A source adapter has a namespaced/versioned descriptor and receives only the source,
planned intent/evidence, and read capabilities needed for acquisition. It returns
typed normalized inventory/acquisition evidence and never mutates repository
metadata directly.

Adapter dispatch is keyed by namespaced adapter identity/capability, not a closed
`SourceKind` enum. Direct registration is sufficient initially. Future plugin
discovery may construct the same registries lazily without changing `Engine` or
source semantics.

Derived tasks receive exact declared input observations/content and a narrow
read-only execution context. They declare deterministic identity/version,
dependency semantics, outputs, and parameters, and return typed outputs. Legacy
manifest-shaped task/enumerator interfaces are removed.

Validators remain versioned immutable evidence producers. Storage backends and
metadata implementations remain advanced composition points but do not appear in
ordinary acquisition/dataset workflows.

## Errors and types

Ordinary domain failures derive from `EfloudError`, with stable subclasses for
repository/open/schema errors, acquisition/execution errors, dataset resolution or
constraint failures, verification/integrity failures, busy/coordination errors, and
export/materialization errors as appropriate.

Opaque identifier value types may remain available under an advanced `efloud.types`
or domain module, but normal callers may pass/receive strings where identity type
safety does not justify package-root complexity.

## Backwards compatibility

There is none for the alpha API or old repository format.

The clean-break implementation removes:

- deprecated `sync(cfg)` and `EngineConfig` compatibility behavior
- merged sync manifests and mirror-state compatibility projections
- path lookup/materialization compatibility helpers
- historical repository importers/recorders
- old query/status/health/summary presentation facades
- source alias migration helpers and TTL cache compatibility
- import aliases retained only for old callers
- schema-v1/v2 in-place upgrade support

Older repositories must be recreated/reacquired or handled by an external one-off
migration/export utility. The maintained Efloud runtime opens only the clean-break
schema.

## Future-extension rule

Future refs, replica tracking, alternate blob stores, remote metadata stores,
recursive Merkle trees, plugin discovery, and distributed coordination must extend
or remain behind the semantic objects above rather than adding storage- or
coordination-specific concepts to the ordinary package root.
