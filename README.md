# efloud

`efloud` is a local-first, versioned data-ingestion and artifact-repository library.

It acquires data from heterogeneous upstream sources, stores immutable content by
digest, records observations and provenance, validates content, and freezes exact
repository state into reproducible datasets for downstream analysis.

The project is pre-1.0. ADR-0010 selected a clean-break public API and complete
removal of alpha backwards compatibility. The clean public facade described below
is implemented; canonical internals are still being migrated to that boundary
before the compatibility implementation is deleted.

## Core model

The central distinction is:

```text
logical artifact -> observation -> immutable content
```

A logical artifact names something whose bytes may change over time. Each
successful acquisition records an observation and points to a content-addressed
object. Repeated observations of unchanged bytes preserve acquisition history
without duplicating content.

The repository also records immutable source-definition revisions, runs and
operations, source/tree snapshots, validation evidence, provenance, immutable
dataset membership, detached manifests, and maintenance evidence.

The default local repository uses SQLite metadata and a filesystem
content-addressed store. Those are implementation defaults, not public semantic
requirements.

## Public API

Ordinary callers use a deliberately small package-root surface:

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
EfloudError and category exceptions
```

Planner/executor records, storage implementations, repository IDs, validator and
adapter registry details, `RepositoryView`, `ReadOnlyRepository`, `SourceKind`,
`SourceDefinition`, `EngineConfig`, and dataset selector/materializer classes are
advanced or transitional submodule details rather than package-root concepts.

### Create a repository and acquire data

```python
from efloud import Engine, HttpSource, Repository

source = HttpSource(
    id="example-json",
    url="https://example.test/data.json",
)

with Repository.create("repository") as repo:
    result = await Engine(repo, [source]).sync()
    if not result.ok:
        print(result.diagnostics)
```

`Repository.create()` creates a new writable repository. Acquisition requires a
writable repository; `Engine` owns planning and execution while `Repository` owns
durable semantic state.

Per-run intent is passed separately:

```python
from efloud import SyncRequest

request = SyncRequest(
    source_ids=("example-json",),
    include_derived=True,
    max_concurrency=4,
)
result = await engine.sync(request)
```

### Read without mutation authority

```python
from efloud import Repository

with Repository.open("repository", mode="r") as repo:
    observation = repo.artifacts.latest("source:example-json")
    if observation is not None:
        with repo.artifacts.open("source:example-json") as stream:
            data = stream.read()
```

There is one public repository type. `mode="r"` opens without mutation authority;
`mode="rw"` obtains the writer coordination required by the backend.

Repository reads are grouped by semantic namespace:

```text
repo.artifacts
repo.sources
repo.runs
repo.datasets
repo.provenance
repo.maintenance
```

### Resolve and freeze reproducible datasets

`DatasetSpec` is immutable selection intent. Public temporal selectors require
timezone-aware `datetime` values.

```python
from datetime import UTC, datetime

from efloud import DatasetSpec, Repository

spec = DatasetSpec.latest_before(
    "source:example-json",
    datetime(2026, 9, 9, tzinfo=UTC),
)

with Repository.open("repository", mode="r") as repo:
    dataset = repo.datasets.resolve(spec)  # exact, but not persisted
    assert dataset.verify()
```

Persist exact membership with `freeze`:

```python
with Repository.open("repository", mode="rw") as repo:
    dataset = repo.datasets.freeze(spec)
    print(dataset.id)
```

Selections can be composed with `include()` and constrained with `require()`.
Source/snapshot, role/tag/prefix, exact-observation, latest, latest-before, and
latest-all selection are available without exposing the underlying selector
classes at the package root.

### Export a detached dataset

```python
with Repository.open("repository", mode="rw") as repo:
    dataset = repo.datasets.freeze(spec)
    manifest = dataset.export("export", strategy="copy")

assert manifest.verify("export")
```

`DatasetManifest` is the detached portable representation. It contains exact
observation/content membership and source/snapshot evidence, not local CAS paths.
It can be serialized and verified without opening Efloud SQLite:

```python
from efloud import DatasetManifest

serialized = manifest.to_bytes()
reopened = DatasetManifest.from_bytes(serialized)
assert reopened.verify("export")
```

Export planning, dry-run, and explicit `auto`, `reflink`, `copy`, and `symlink`
strategies remain available through dataset methods. Publication validates paths,
stages and verifies content, never overwrites an existing destination, and uses
atomic publication where supported.

### Inspect repository maintenance state

```python
with Repository.open("repository", mode="r") as repo:
    report = repo.maintenance.audit()
    assert report.ok
```

Destructive cleanup and recovery remain advanced maintenance operations while the
canonical mutation surface is being reduced. Their safety semantics remain
reachability-based and writer-coordinated.

## Source extensibility

Built-in source classes have namespaced adapter identities and protocol-specific
fields, so HTTP configuration cannot accidentally carry rsync-only options. The
public `Source` protocol is open rather than a closed `SourceKind` hierarchy.

The current facade bridges built-in sources onto the existing executor. The next
implementation milestone replaces the executor's remaining `SourceKind`/
`EngineConfig` dispatch with namespaced adapter dispatch and narrow execution
contexts, at which point third-party source implementations can participate
without a core enum change.

## Derived artifacts and validation

Derived outputs are ordinary repository artifacts with provenance. Deterministic
work may reuse existing content when its declared dependency semantics permit it,
but current-run output observations are still recorded.

Validation is layered: storage integrity, source integrity expectations, generic
encoding/container validation, and domain validation supplied by consumers.
Evidence is reusable by content and validator identity/version.

## Backwards compatibility

The clean API deliberately provides **no package-root aliases for the alpha API**.
Old implementation modules still exist temporarily because canonical execution has
not yet completed its migration. The implementation plan removes them rather than
supporting them indefinitely, including deprecated `sync(cfg)`, compatibility
`EngineConfig`, merged sync manifests and mirror projections, historical importers,
old query/status presentation facades, source-alias/adoption helpers, TTL-cache
compatibility, import aliases, and schema-v1/v2 in-place upgrades.

Old repository roots are not part of the post-cutover support contract. They may be
recreated/reacquired or handled by an external one-off converter if required.
Downstream packages such as BVP migrate to the clean repository/dataset boundary
instead of keeping compatibility representations alive.

See [`docs/compatibility-inventory.md`](docs/compatibility-inventory.md) for the
finite removal inventory.

## Future extensions

The public boundary keeps currently proposed advanced features additive or
internal:

- new protocols add source/adapter types without changing repository semantics;
- plugin discovery can populate adapter/validator registries;
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
architecture, tests, packaging, and coverage across the supported Python range.

## Project status

The clean package-root API and public repository/source/result/dataset facade are
implemented. The next work is to migrate planner/executor/adapters/derived work and
other canonical internals onto those contracts, delete backwards compatibility and
historical schema support, and then repeat durability/export/CI/BVP acceptance on
the reduced implementation.

See [`STATUS.md`](STATUS.md), [`PLAN.md`](PLAN.md), and [`TODO.md`](TODO.md) for the
current handoff and implementation sequence.
