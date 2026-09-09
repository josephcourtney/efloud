# efloud

`efloud` is a local, versioned data-ingestion and artifact-repository library.

It acquires data from heterogeneous upstream sources, stores immutable content by digest, records observations and provenance, and exposes repository-backed queries and immutable datasets for downstream analysis. Filesystem mirrors and JSON manifests remain useful compatibility views, but they are not the authoritative state model.

## Core Model

The central distinction is:

```text
logical artifact -> observation -> immutable content
```

A logical artifact names a thing whose bytes may change over time. Each successful acquisition records an observation of that artifact and points to a content-addressed object. Repeated observations of unchanged bytes therefore preserve acquisition history without duplicating content.

The repository also records:

- source definitions and immutable definition revisions
- runs and operations with explicit lifecycle state
- source inventories and source/tree snapshots
- content validation evidence
- provenance edges for fetched and derived artifacts
- immutable dataset membership
- materialization records and compatibility projections

The default local repository uses SQLite for metadata and a filesystem content-addressed store for immutable blobs.

## What It Is For

`efloud` is intended for applications that need reproducible local acquisition rather than ad hoc network requests throughout an analysis pipeline.

Typical uses include:

- mirror reference datasets while retaining their historical observations
- combine HTTP, REST/collection, and `rsync` sources behind one repository model
- inspect exactly what was observed, when, and from which source definition
- validate downloaded content before advancing source state
- reuse identical content and deterministic derived outputs without losing provenance
- freeze exact artifact observations into immutable datasets for downstream analysis
- operate offline after acquisition

It is not a desktop file-sync application, workflow scheduler, or domain-specific scientific database.

## Current Architecture

The canonical acquisition path is:

```text
Engine
  -> SyncPlanner
  -> SyncExecutor
  -> Repository
       -> MetadataStore (SQLite by default)
       -> BlobStore (filesystem CAS by default)
```

Source adapters understand protocol-specific acquisition. Repository semantics are protocol-independent. Compatibility manifests, mirror-state files, and filesystem layouts are derived from repository state rather than acting as secondary databases.

The supported read boundary is `RepositoryView`. Both the mutable `Repository` and `ReadOnlyRepository` provide that semantic read capability. Immutable datasets and repository query/status services depend on the read capability rather than requiring mutation authority.

## Basic Acquisition

```python
import asyncio
from pathlib import Path

from efloud import Engine, SourceDefinition, SourceKind


async def main() -> None:
    with Engine(
        Path("./repository"),
        sources=[
            SourceDefinition(
                id="example-json",
                description="Example JSON payload",
                url="https://example.test/data.json",
                kind=SourceKind.HTTP,
            ),
        ],
    ) as engine:
        result = await engine.sync()
        print(result.ok)
        print(result.repository_run_id)


asyncio.run(main())
```

`Engine.plan()` uses the same deterministic planning path without performing acquisition. A dry-run request likewise performs no authoritative repository mutation.

## Repository Reads

Downstream code can inspect repository state without running acquisition:

```python
from pathlib import Path

from efloud import ReadOnlyRepository


with ReadOnlyRepository(Path("./repository")) as repository:
    for artifact_key in repository.artifact_keys():
        state = repository.latest_state(artifact_key)
        print(artifact_key, state)
```

`ReadOnlyRepository` opens SQLite in read-only mode and does not initialize or migrate repository state.

## Immutable Datasets

A dataset freezes exact observation membership. Dataset specification identity, exact observation membership identity, and content-equivalence identity are distinct.

```python
from pathlib import Path

from efloud import DatasetDefinition, Latest, Repository


with Repository(Path("./repository")) as repository:
    dataset = repository.resolve_dataset(
        DatasetDefinition.from_selectors(Latest("source:example-json"))
    )
    member = dataset.artifact("source:example-json")
    print(dataset.id, member.content_id)
```

Once resolved, later acquisition does not change that dataset's membership.

Snapshot selectors use complete recorded membership. `SourceSelection` filters by source,
role, tags, artifact-key prefix, and inclusive observation-time bounds. Role/tag
filters use the source revision recorded with each observation; unknown historical
revisions fail those filters explicitly. `DatasetConstraints` supports complete
snapshot evidence, same-run membership, maximum observation skew, and existing
validator/version evidence. Failed constraints raise `DatasetConstraintError` with
structured results. Resolution never runs acquisition or validation.

```python
from pathlib import Path
from efloud import (
    DatasetDefinition, DatasetMaterializer, LatestCompleteSourceSnapshot,
    ReadOnlyRepository, Repository, export_dataset_manifest,
)

with Repository(Path("repository")) as repository:
    dataset = repository.resolve_dataset(DatasetDefinition.from_selectors(
        LatestCompleteSourceSnapshot("example-json")
    ))
    dataset_id = dataset.id

with ReadOnlyRepository(Path("repository")) as repository:
    manifest = export_dataset_manifest(repository.dataset(dataset_id))
    materializer = DatasetMaterializer(repository)
    plan = materializer.export(manifest, Path("export"), dry_run=True)
    materializer.export(manifest, Path("export"))
    assert manifest.verify(Path("export"))
```

Exports include `dataset-manifest.json`. The default `auto` strategy tries native
CoW and falls back to an independent copy; explicit `copy`, `reflink`, and
`symlink` modes are available. Symlink mode points into a private content directory
inside the export, so edits cannot affect CAS content. Destinations must be new,
outside the repository, with an existing parent directory. Unsafe paths, reserved
manifest paths, case-insensitive collisions, and file/directory conflicts fail
before publication. Explicit path mappings may be supplied to
`export_dataset_manifest`; defaults are deterministic artifact-key digests.

`DetachedDatasetManifest.from_bytes` checks the version and manifest digest.
`import_dataset_manifest(view, manifest)` reopens and verifies exact membership in
another repository without writing metadata. `manifest.verify(export_root)`
checks detached bytes without consulting SQLite. Neither operation reacquires
missing content. A repository transfer must preserve observation metadata as well
as blobs; matching bytes alone do not recreate observation identity.

## Maintenance and recovery

```python
from pathlib import Path
from efloud import RepositoryMaintenance

maintenance = RepositoryMaintenance(Path("repository"))
report = maintenance.fsck()  # read-only; report.issues and report.reachability
# Supply explicit observation time and grace policy:
candidates = maintenance.cleanup(now=2000000000.0, grace_period=86400.0)
# Apply the same policy after reviewing candidates:
# maintenance.cleanup(now=2000000000.0, grace_period=86400.0, dry_run=False)
```

Every writable `Repository` holds an exclusive local OS lease until closed.
Concurrent writable opens or maintenance raise `RepositoryBusyError`; use
`ReadOnlyRepository` for concurrent consumers. Always close writers or use a
context manager. A process crash releases its lease. `recover(finished_at=...,
dry_run=False)` marks abandoned running operations and runs failed, preserving
content and snapshots. It is idempotent. Retry interrupted acquisition through a
fresh `Engine.sync()` run; recovery never replays unknown transport side effects
or upgrades partial snapshots to complete.

Safe cleanup retains all historical observation, tree, dataset, provenance,
validation, and materialization content references. It reports a reason for each
candidate and defaults to a dry run. Historical pruning remains deferred.
The current writer/maintenance backend targets local POSIX filesystems.

## Public API and compatibility

The stable package API exposes repository reads, datasets, exports, maintenance,
`Engine`, and deliberate source-adapter/validator contracts. Adapters receive a
`RepositoryView` and return typed acquisition evidence; authoritative writes belong
to the executor and repository. See [the API contract](docs/api.md).

Legacy `sync(cfg)` delegates to `Engine` and emits a deprecation warning.
Compatibility projections are available as `EngineSyncResult.compatibility`.
Legacy serializers and importers remain explicit compatibility tools, not dataset
or query dependencies. Storage implementation classes are imported from their
implementation modules, not the package root. `ContentRef` no longer accepts a
storage key. Rsync configuration uses `RsyncMode`, `rsync_mode`, and `rsync_paths`;
`MirrorMode` is confined to `efloud.compat.registry`.

## Source Support

Current acquisition paths include:

- HTTP files
- REST responses
- `rsync` file-tree sources
- REST collection/fanout acquisition
- repository-recorded derived artifacts and indexes

Additional source adapters are intentionally use-case driven. Protocol-specific behavior should remain behind adapter/inventory contracts rather than adding protocol-specific repository semantics.

## Repository Layout

A default repository is approximately:

```text
repository/
  metadata.sqlite       # authoritative metadata
  objects/
    sha256/...          # authoritative immutable content
  http/                 # compatibility/materialized HTTP files
  mirrors/              # compatibility/materialized rsync trees
  cache/                 # disposable HTTP cache state
  rate_limits/           # operational rate-limit state
  log/                   # compatibility manifests
```

Only repository metadata and retained content objects are authoritative. Caches, manifests, mirror state, and materialized filesystem views are reconstructable or compatibility-oriented state.

## Validation And Provenance

Content identity is computed from the bytes efloud actually stores. Upstream checksums are integrity expectations, not content identity, until independently verified.

Validation evidence is recorded separately from observations. Required validation failure does not advance source state as if acquisition succeeded.

Fetched and derived outputs use the same provenance model. Deterministic derived work may reuse existing content while still recording a fresh observation for the current run.

## Development

The project uses `uv` and `just`.

```bash
uv sync
uv run just check
```

The canonical CI gate checks syntax, Ruff formatting/linting, static typing, import architecture, the complete test suite, and coverage. The full test suite also runs across every supported Python minor version.

The declared Python range is 3.12 through 3.14.

## Project Status

Alpha — `0.0.10`.

The repository-centered architecture is implemented for the main acquisition, persistence, validation, provenance, query, and immutable-dataset paths. The active work is completing immutable dataset selection/coherence semantics and a detached consumer manifest, followed by safe materialization/export and cleanup of legacy compatibility APIs.

Long-lived maintenance features such as repository-wide writer coordination, crash recovery, audit/fsck, and safe garbage collection are not complete yet. Treat the public API as pre-1.0 while those boundaries continue to harden.

`DESIGN.md` is normative for architectural semantics; `STATUS.md` and `PLAN.md` describe current completion and remaining work.
