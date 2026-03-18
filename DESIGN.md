# DESIGN

> This document is normative. It defines the intended v2 architecture for `efloud`,
> the compatibility constraints on that architecture, and the invariants new work
> must preserve while the implementation migrates from the current alpha design.

## Intent And Scope

`efloud` is a library for building inspectable local mirrors of remote data. The
design must satisfy two goals that pull in opposite directions:

- keep the default user experience simple
- allow protocol, storage, policy, and execution behavior to evolve without
  forcing invasive changes to the engine core

The v2 architecture therefore uses:

- one easy public `Engine`
- an internal composed `Runtime`
- a typed sync plan made of operations
- adapter-driven protocol behavior
- explicit storage abstractions
- decision-based policy objects
- queryable, stable, human-readable metadata by default

The design is not a clean-slate replacement of current behavior. It must remain
compatible with the package's existing strengths:

- stable root-oriented storage
- manifest-based transparency
- mixed HTTP, REST, and `rsync` support
- derived fanout materialization
- query and status helpers
- deterministic outputs suitable for testing and automation

## High-Level Goals

- expose a compact top-level API for ordinary use
- separate planning from execution so dry-run and future resume/checkpoint work
  become straightforward
- isolate protocol-specific logic behind adapters instead of branching through
  the orchestration core
- make artifact identity explicit rather than coupling all state to filesystem
  paths
- preserve transparency through manifests, plans, query responses, and readable
  on-disk records where possible
- support incremental growth toward richer policies, indexes, derived tasks, and
  alternate storage backends

## Non-Goals

- building a generic desktop sync client
- hiding all implementation details behind opaque runtime objects
- replacing human-readable metadata with opaque binary state
- requiring advanced composition for ordinary use
- introducing distributed orchestration or remote workers in the default design

## Public API Tiers

The public API is organized into three tiers.

### Tier 1: Easy Mode

This is the default user experience.

```python
from efloud import Engine, HttpSource, RsyncSource, RestCollectionSource

engine = Engine(root="cache", sources=[...])
result = await engine.sync()
payload = engine.query("source:foo")
status = engine.status()
```

Requirements:

- one constructor for ordinary users
- batteries-included runtime assembly
- no requirement to understand planners, executors, or stores
- deterministic defaults

### Tier 2: Configured Engine

This keeps the default orchestrator while allowing selective customization.

```python
engine = Engine(
    root="cache",
    sources=[...],
    refresh_policy=...,
    artifact_store=...,
    metadata_store=...,
    derived_tasks=[...],
    indexes=[...],
)
```

Requirements:

- callers can override specific subsystems without forking the whole runtime
- optional components still use the standard query and metadata model
- defaults remain stable when not overridden

### Tier 3: Fully Composed Runtime

This is the escape hatch for advanced deployments.

```python
runtime = Runtime(
    planner=...,
    executor=...,
    adapter_registry=...,
    stores=...,
    policies=...,
    event_bus=...,
    query_service=...,
)
await runtime.run(SyncRequest.all_sources())
```

Requirements:

- all major subsystems are swappable
- compatibility helpers may adapt Tier 1 or Tier 2 objects onto this runtime
- the public contract remains explicit and typed

## Architectural Decomposition

The default v2 structure is:

```text
Engine
  -> Runtime
      -> SourceRegistry
      -> ProtocolAdapterRegistry
      -> Planner
      -> Executor
      -> StoreSet
      -> PolicySet
      -> QueryService
      -> EventBus
```

Responsibilities:

- `Engine`: convenience facade, compatibility surface, and default runtime
  assembly
- `Runtime`: orchestration boundary that coordinates planning, execution,
  storage, policy, and querying
- `Planner`: converts a sync request plus current state into a deterministic
  operation plan
- `Executor`: executes planned operations while respecting dependencies and
  concurrency rules
- `ProtocolAdapterRegistry`: resolves the adapter responsible for a source or
  operation
- `StoreSet`: owns artifact, metadata, state, cache, and index persistence
- `PolicySet`: owns refresh, retention, naming, and validation decisions
- `QueryService`: answers user and tooling queries against logical and physical
  state
- `EventBus`: emits observability and extension events without becoming the main
  user model

## Domain Model

### Source Specs

Source specs are declarative inputs. They carry source facts, not execution
 state.

Shared source fields:

- `id`
- `description`
- `tags`
- `role`
- `aliases`
- `policy`
- `metadata`

Protocol-specific source types include:

- `HttpSource`
- `RestSource`
- `RsyncSource`
- `RestCollectionSource`

Rules:

- source identity must be stable across runs
- protocol-specific fields belong only to protocol-specific source types
- source specs may include policy hints, but policy execution belongs to policy
  objects
- source specs must remain serializable for manifests and diagnostics

### Artifact Model

Artifacts have a logical identity independent of their storage backend.

`ArtifactRef` represents:

- artifact identifier
- source identifier
- artifact type
- logical path
- media type
- storage key

`ArtifactRecord` extends that with:

- size
- checksum
- creation timestamp
- metadata
- provenance

Rules:

- logical identity must not depend on absolute filesystem paths
- default filesystem-backed implementations must still expose the resolved local
  path for transparency
- query responses must expose both logical identity and physical location when a
  physical location exists

### Provenance Model

Provenance records describe how an artifact came to exist.

Required provenance fields:

- `run_id`
- `source_id`
- `operation_id`

Optional provenance fields may include:

- input artifact identifiers
- upstream locator
- transport metadata
- task name and version

Rules:

- derived tasks and indexes must record provenance in the same model as fetched
  artifacts
- provenance should be stable enough to support debugging, audit, and rebuild
  decisions

## Runtime Model

`Runtime` coordinates the main pluggable subsystems.

```python
@dataclass
class Runtime:
    planner: SyncPlanner
    executor: SyncExecutor
    adapter_registry: ProtocolAdapterRegistry
    stores: StoreSet
    policies: PolicySet
    event_bus: EventBus
    query_service: QueryService
```

### Store Set

The runtime groups storage concerns into a `StoreSet`.

Required stores:

- `artifact_store`
- `metadata_store`
- `state_store`

Optional stores:

- `cache_store`
- `index_store`

Rules:

- storage concerns must remain separate even when multiple stores share the same
  filesystem root
- the default implementation may colocate files on disk but must preserve
  conceptual boundaries

### Policy Set

The runtime groups policy concerns into a `PolicySet`.

Required policies:

- `refresh_policy`
- `retention_policy`
- `naming_policy`

Optional policies:

- `validation_policy`

Rules:

- policies make decisions; they do not perform transport or storage work
- policy outputs must be structured enough to explain why work was planned

## Planning And Execution

### Sync Request

`SyncRequest` defines the caller's intent.

Core request fields:

- `targets`
- `refresh`
- `dry_run`
- `rebuild_indexes`
- `rebuild_derived`

Requirements:

- empty targets means all sources
- requests must be serializable for observability and diagnostics

### Sync Plan

`SyncPlan` contains:

- `run_id`
- ordered operations
- planning decisions

`PlanningDecision` explains:

- the subject being considered
- the action selected
- the reason
- structured decision details

Requirements:

- plans must be deterministic for a given request and planning state
- dry-run must use the same planning path as real execution
- decisions must be recorded in a form suitable for humans and machines

### Operation Model

Execution is expressed as typed operations such as:

- `fetch_http`
- `fetch_rest`
- `mirror_rsync`
- `mirror_rsync_paths`
- `enumerate_collection`
- `fetch_collection_item`
- `delete_artifact`
- `build_derived`
- `build_index`
- `validate_artifact`

Each operation contains:

- `op_id`
- `kind`
- `source_id`
- typed input payload
- dependency identifiers

Requirements:

- operations must be safe to topologically order
- dependencies must be explicit
- operation records must be stable enough for future retry, resume, and audit

### Planner Interface

The planner is responsible for assembling a full plan from:

- requested targets
- registered sources
- adapter capabilities
- store state
- policy decisions
- derived task and index definitions

The planner must not perform network or filesystem mutation as part of planning.

### Executor Interface

The executor is responsible for:

- dependency-aware scheduling
- concurrency control
- adapter dispatch
- operation result recording
- event emission

The executor must not invent new work outside the approved plan except for local
 bookkeeping required to persist results.

## Protocol Adapter Architecture

Protocol-specific logic moves behind adapters.

Each adapter must:

- declare which source type it supports
- plan operations for that source
- execute operations it owns

Default built-ins:

- `HttpFileAdapter`
- `RestJsonAdapter`
- `RsyncAdapter`
- `RestCollectionAdapter`

Rules:

- adding a new protocol must not require editing the engine core
- adapter planning semantics may differ by protocol, but operation and metadata
  recording semantics must remain consistent across adapters
- adapter output must preserve transparency in query and manifest layers

## Storage Architecture

### Artifact Store

The artifact store owns artifact bytes and payload materialization.

Default implementation:

- `FilesystemArtifactStore`

Potential alternates:

- object storage
- content-addressed storage
- SQLite-backed storage

Rules:

- filesystem remains the default
- callers must be able to resolve a human-meaningful location when one exists
- stores must support deterministic writes suitable for tests

### Metadata Store

The metadata store owns:

- run records
- operation records
- artifact records
- provenance
- statuses

Default implementation:

- JSON manifest files, potentially with light indexing support

Rules:

- metadata must remain readable and inspectable by default
- v1 manifest compatibility must be preserved during migration

### State Store

The state store owns:

- mirror-state hash trees
- source freshness data
- transport-specific sync state that is not artifact content

Rules:

- mirror-state concerns must not be conflated with artifact storage
- future migration to database-backed state must not require planner or query
  rewrites

## Policy Architecture

Policies return decisions rather than bare booleans.

### Refresh Policy

The refresh policy returns a `RefreshDecision` containing:

- action
- reason
- details

Actions may include:

- `skip`
- `fetch`
- `revalidate`
- `mirror`
- `mirror_paths`
- `rebuild`

Default refresh behavior should layer simple rules in priority order:

1. explicit refresh request
2. missing artifact
3. previous run failure
4. TTL expiration
5. dependency change
6. otherwise skip or revalidate depending on transport

Source-level policy hints may include:

- TTL
- refresh-on-error
- allow-revalidate
- priority

Rules:

- the decision model must remain explainable
- refresh logic should be centralized, not reimplemented inside adapters

### Retention, Naming, And Validation

Retention, naming, and validation policies are separate concerns.

Requirements:

- retention rules must describe artifact deletion or tombstoning behavior
- naming rules must stabilize logical paths and storage keys
- validation rules must be optional and must not silently mutate artifacts

## Derived Tasks

Derived tasks become dependency-aware planned work rather than purely
 post-sync callbacks.

Each derived task should declare:

- `name`
- `version`
- dependencies
- planned operations

Requirements:

- derived work must participate in planning and policy decisions
- reconciliation behavior for collection-like outputs must be explicit
- deletion semantics must be configurable through a reconciliation policy

## Indexing

Indexes are first-class derived artifacts with stronger cache semantics.

Each index definition should declare:

- identifier
- description
- dependencies
- TTL
- builder

Requirements:

- index build decisions must be dependency-aware
- query interfaces must surface both status and payload
- existing TTL-backed JSON index behavior should remain representable during
  migration

## Query Architecture

The query layer sits above stores and metadata, not directly on raw files.

Supported target kinds should include:

- `root`
- `source:<id>`
- `source:<id>#/locator`
- `artifact:<artifact-id>`
- `index:<index-id>`
- `run:<run-id>`
- `store:<store-id>`

Requirements:

- query results must expose logical identity and physical location when possible
- source queries must continue to support locator resolution
- v1 query forms must remain supported during migration

## Event Architecture

Events support observability and optional extension.

Useful default event types include:

- `plan.built`
- `source.planned`
- `operation.started`
- `operation.completed`
- `operation.failed`
- `artifact.materialized`
- `artifact.deleted`
- `derived.completed`
- `index.completed`
- `run.completed`

Rules:

- events are supplementary, not the main user interface
- the default event bus may be a no-op
- event payloads must be structured and deterministic

## Locking And Concurrency

Locking and concurrency are explicit runtime concerns.

### Locking

The default runtime uses a filesystem lock for one-root-at-a-time sync safety.

Requirements:

- lock ownership must be explicit
- failure to acquire a lock must produce a clear error

### Concurrency

The executor must support:

- serial execution
- bounded parallel execution for independent operations
- per-adapter or per-source concurrency limits

Rules:

- concurrency must respect operation dependencies
- concurrency defaults must favor correctness over maximum throughput

## Default Runtime Assembly

The default `Engine` constructor assembles:

- filesystem-backed artifact storage
- manifest-backed metadata storage
- filesystem-backed state and index stores
- default policy set
- built-in protocol adapters
- a default planner
- a default executor
- a null event bus
- a query service

This assembly must remain an implementation detail of Tier 1 and Tier 2 usage.

## Compatibility Requirements

The v2 design must preserve compatibility with current functionality while the
 implementation migrates.

Required compatibility guarantees:

- existing `sync(cfg)` behavior remains available through a compatibility layer
- current `EngineConfig` and `SourceDefinition` can be adapted into v2 runtime
  inputs during the transition
- current manifest consumers continue to function, either against the existing
  schema or an explicit compatibility serializer
- current query targets remain valid
- current derived fanout workflows remain expressible
- current index registry behavior remains representable

Compatibility may be achieved by adapters, shims, translators, or staged
 deprecations, but not by silently dropping current capabilities.

## Package Layout

A target v2 package layout is:

```text
efloud/
  api/
    engine.py
    builders.py
  domain/
    sources.py
    artifacts.py
    provenance.py
    operations.py
    plans.py
    results.py
  adapters/
    base.py
    http.py
    rest.py
    rsync.py
    rest_collection.py
  stores/
    artifacts.py
    metadata.py
    state.py
    index.py
    cache.py
    filesystem.py
    sqlite.py
  policy/
    refresh.py
    retention.py
    naming.py
    validation.py
  planner/
    default.py
  executor/
    default.py
    parallel.py
    locks.py
  query/
    parser.py
    service.py
    locators.py
  observe/
    events.py
    logging.py
  compat/
    manifest_v1.py
```

This layout is intended to make subsystem boundaries visible without forcing a
large public API.

## Design Invariants

All implementations must preserve these invariants:

- sync output is deterministic for deterministic upstream inputs
- metadata remains inspectable and stable enough for automation
- the default experience stays simple
- advanced customization does not require patching core engine code
- artifacts remain queryable after materialization
- protocol-specific details do not leak into unrelated subsystems
- compatibility shims are explicit and testable
