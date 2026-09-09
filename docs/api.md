# Public API contract

## Stable semantic surface

`Engine` owns canonical planning/execution. `Repository` is the exclusive writer
and historical metadata service. `RepositoryView` is the read capability used by
selectors, queries, adapters, and materializers; `ReadOnlyRepository` opens an
existing current-schema store without initialization, migration, or acquisition.
Negative `source_snapshots_for(limit=-1)` requests all history.

Dataset selectors are `ExactObservation`, `Latest`, `LatestBefore`, `LatestAll`,
`ExactSourceSnapshot`, `LatestCompleteSourceSnapshot`, and `SourceSelection`.
Snapshot selectors require complete source coverage and unambiguous observation
bindings. Partial scope snapshots are inspectable but cannot satisfy a complete
source snapshot selector. Time bounds are inclusive repository observation times.
Namespace filtering is an artifact-key prefix, not a new metadata entity.

`DatasetDefinition` combines role-bearing `DatasetSelection` records and optional
`DatasetConstraints`. A definition identifies intent; `DatasetId` identifies exact
observation membership; `content_identity` identifies byte-equivalent membership.
Free-standing `resolve_dataset(view, definition)` returns a manifest without
persistence. `Repository.resolve_dataset` additionally records membership.

Detached manifest v1 contains canonical sorted members with artifact, observation,
content, role, size, media type, source revision, and logical path metadata. It
includes the original definition, specification ID, exact membership ID, content
identity, frozen snapshot evidence and constraint results. `to_bytes()` emits
canonical UTF-8 JSON plus a final newline and a digest of the envelope. It excludes
local blob paths and export timestamps. Import is read-only and verifies source,
observation, and content evidence. A manifest digest proves consistency, not signer
authenticity.

`DatasetMaterializer` accepts only a `RepositoryView`. `plan` and `export(dry_run=True)`
validate layout without writing. `export` verifies staged content and publishes a
complete sibling tree. Existing destinations are never overwritten. Default paths
are `artifacts/<SHA-256 of artifact key>`; explicit safe paths can be provided.
`auto` uses native CoW when the stream exposes a supported local descriptor and
falls back to copy. `reflink` reports unsupported cloning. `symlink` links to a
private export content directory, keeping repository blobs independent.

`RepositoryMaintenance` is the local storage maintenance service. Audit does not
repair; cleanup and recovery default to dry runs. Cleanup computes fresh reachability
under the same lease used by writers and preserves historical metadata. Recovery
fails abandoned running lifecycle records; a new Engine run retries acquisition
through normal reconciliation. It never invents successful completion evidence.

## Extension contracts

A `SourceAdapter` exposes a namespaced/versioned `AdapterDescriptor` and implements
`acquire(AdapterExecutionContext)`. The context includes a `RepositoryView`, source
configuration, and planned operation. Return `HttpAcquisition`, `RsyncAcquisition`,
or `CollectionAcquisition`; do not write repository metadata. Inventory completeness,
change tokens, integrity expectations, and acquisition failures are explicit typed
evidence. Registration is direct through `AdapterRegistry`; external plugin discovery
is intentionally absent. Validators register versioned `ContentValidator` contracts
and return immutable content evidence without changing bytes.

## Compatibility and implementation

`EngineSyncResult.compatibility` contains optional JSON/mirror projections.
`efloud.sync.sync` warns and delegates to Engine. Legacy projection lookup lives in
`efloud.compat.materialization`; historical importers and runtime fixture helpers
live under `efloud.compat`. Repository serializers named `repository_compat` and
`repository_state` remain projection adapters. They are never authoritative stores.
Legacy TTL indexes and manifest-based fanout extension seams are compatibility
facilities; new custom acquisition should implement `SourceAdapter`.

SQLite, blob placement, schema migration helpers, and coordination internals are
implementation modules, not package-root promises. Supported schema-v1/v2 upgrades
remain in `schema_migrations`; the former v3 subclass is only an import alias.
Rsync configuration uses `RsyncMode`, `rsync_mode`, and `rsync_paths`. Source revision
history is preserved, so old recorded definitions retain their original fields.
