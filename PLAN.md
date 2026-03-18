# PLAN.md

Purpose:

- describe the staged implementation plan for the v2 `efloud` architecture
- sequence work so current functionality stays usable throughout the migration
- define concrete deliverables, dependencies, and acceptance criteria for each
  phase

Rules:

- preserve existing user-visible behavior unless a phase explicitly introduces a
  compatibility layer or deprecation path
- prefer incremental internal replacement over a one-shot rewrite
- validate each phase with deterministic tests before starting the next phase
- keep manifests, query behavior, and local storage inspectable during the
  migration

## Strategy

The redesign should be delivered as a sequence of internal extractions followed
by public API improvements. The priority order is:

1. introduce seams inside the current engine without breaking behavior
2. move planning and execution responsibilities behind typed interfaces
3. formalize adapters, stores, policies, and domain models
4. add the new `Engine` and `Runtime` surfaces on top of the internal seams
5. retain current APIs through explicit compatibility modules until deprecation

This avoids a flag day migration and keeps the package testable after every
step.

## Cross-Phase Constraints

These constraints apply to every phase:

- preserve current support for HTTP, REST, `rsync`, and derived fanout behavior
- keep `sync(cfg)` operational until an explicit deprecation phase
- keep current query targets working
- keep canonical and timestamped manifest outputs available
- keep mirror-state generation available
- preserve deterministic file naming and metadata content where practical
- add tests for every compatibility shim and every new subsystem boundary

## Phase 0: Baseline And Mapping

Objective:

- document the current architecture and define the compatibility perimeter

Work:

- map current modules to future subsystem homes
- list current public exports and usage patterns
- list current manifest fields, query targets, and status payload expectations
- identify behavior that must remain stable through v2

Deliverables:

- updated `DESIGN.md`
- this implementation plan
- a written compatibility inventory for existing exports and manifest/query
  shapes

Acceptance criteria:

- current architecture is described well enough to review migration work against
- compatibility expectations are explicit before implementation starts

## Phase 1: Introduce Internal Runtime Seams

Objective:

- split the current monolithic sync path into explicit internal orchestration
  boundaries without changing behavior

Work:

- introduce an internal `Runtime` type that can execute a sync request
- extract planner and executor interfaces, initially backed by behavior
  equivalent to the current orchestration path
- move current manifest recording and mirror-state updates behind dedicated
  helper objects or services
- keep `sync(cfg)` as the primary public entrypoint, internally delegating to
  the runtime

Suggested module work:

- create `src/efloud/runtime.py` or the eventual v2 package equivalents
- reduce direct orchestration responsibility in `src/efloud/sync.py`
- keep manifest and state write behavior unchanged

Acceptance criteria:

- `sync(cfg)` still produces the same practical outputs
- tests covering current sync, manifest, and state behavior still pass
- runtime seams exist and can be extended without editing the public API

Risks:

- over-extraction that moves code without clarifying responsibility
- accidentally changing manifest content while refactoring internals

## Phase 2: Source Model And Compatibility Builders

Objective:

- introduce explicit source-spec types while preserving the current config path

Work:

- add new source-spec classes such as `HttpSource`, `RestSource`,
  `RsyncSource`, and `RestCollectionSource`
- define a compatibility builder that lowers current `SourceDefinition` values
  into the new source model
- retain current `SourceKind` and `SourceDefinition` as compatibility-facing
  types during the transition
- add alias and role behavior to the new source model

Suggested compatibility rules:

- existing `SourceDefinition(kind=...)` usage remains valid
- new source classes produce semantically equivalent behavior
- source identifiers remain stable across both APIs

Acceptance criteria:

- current tests for source resolution, aliases, and policy dispatch still pass
- new source classes can represent all currently supported source cases
- current configuration can be translated into the new runtime source registry

Risks:

- constructor churn that makes the API harder rather than simpler
- semantic mismatch between `REST_BASE` fanout behavior and collection sources

## Phase 3: Operation And Planning Model

Objective:

- make planning explicit and deterministic

Work:

- introduce `SyncRequest`, `SyncPlan`, `PlanningDecision`, and `Operation`
- define the initial operation kinds required to express current behavior
- implement a default planner that reproduces the current sync flow through
  planned operations
- add dry-run support based on real planning output rather than transport
  branching

Initial operation coverage:

- HTTP fetch
- REST fetch
- `rsync` full mirror
- `rsync` path mirror
- derived task execution
- index build where configured
- manifest/state bookkeeping operations if needed for observability

Acceptance criteria:

- planner output is deterministic for the same request and planning state
- dry-run uses the plan and does not require duplicated orchestration logic
- operation dependency ordering is explicit and test-covered

Risks:

- defining operation kinds too loosely, leading to untyped `inputs` blobs
- baking storage details into operation payloads too early

## Phase 4: Protocol Adapter Registry

Objective:

- move transport-specific behavior behind adapter dispatch

Work:

- define `ProtocolAdapter` and `ProtocolAdapterRegistry`
- implement built-in adapters for:
  - HTTP files
  - REST JSON files
  - `rsync`
  - REST collection fanout
- move protocol-specific planning and execution logic out of the engine core
- make operation-to-adapter resolution explicit

Migration notes:

- the initial adapters may wrap existing transport helpers directly
- keep transport modules reusable; do not duplicate HTTP or `rsync` logic

Acceptance criteria:

- adding a new protocol no longer requires editing the engine orchestration core
- current source kinds can all be handled through adapter dispatch
- adapter planning and execution paths are individually testable

Risks:

- scattering shared behavior between adapters without a clear base contract
- moving too much policy logic into adapters

## Phase 5: Store Abstractions

Objective:

- separate artifact, metadata, and state persistence concerns

Work:

- introduce `ArtifactStore`, `MetadataStore`, and `StateStore`
- add optional `IndexStore` and `CacheStore`
- implement filesystem-backed defaults that preserve current on-disk behavior as
  closely as practical
- move manifest writing behind the metadata store
- move mirror-state read and write behavior behind the state store

Compatibility requirements:

- default local paths must remain queryable
- canonical and timestamped manifests must still exist unless explicitly
  deprecated later
- mirror-state compatibility with current readers must be preserved

Acceptance criteria:

- the runtime no longer writes directly to storage primitives outside store
  interfaces
- query and status helpers can obtain the information they need through store
  abstractions
- filesystem-backed defaults remain inspectable on disk

Risks:

- losing straightforward filesystem semantics in the name of abstraction
- breaking current query/status helpers that assume direct paths

## Phase 6: Metadata, Artifact, And Provenance Records

Objective:

- make artifact identity and provenance first-class

Work:

- introduce `ArtifactRef`, `ArtifactRecord`, and `ProvenanceRecord`
- record operation outputs in the metadata store
- connect derived artifacts and indexes to the same artifact/provenance model
- teach the query layer to expose logical artifact identity alongside physical
  storage details

Acceptance criteria:

- fetched artifacts, derived outputs, and indexes all have consistent metadata
  records
- query responses can show both logical identity and storage location when
  applicable
- provenance is rich enough to debug how an artifact was produced

Risks:

- dual-writing incompatible metadata during the migration
- creating records that are too generic to be useful

## Phase 7: Decision-Based Policy System

Objective:

- replace boolean refresh decisions with structured decision objects

Work:

- define `RefreshDecision` and `RefreshPolicy`
- implement a layered default refresh policy that covers:
  - explicit refresh
  - missing outputs
  - previous failure
  - TTL expiry
  - dependency changes
  - skip or revalidate fallback
- define source-level policy hints
- add retention, naming, and optional validation policy interfaces

Compatibility path:

- adapt current `DefaultSyncPolicy` and `RoleDrivenSyncPolicy` semantics into the
  new decision model
- preserve current refresh flags on compatibility config objects

Acceptance criteria:

- planner decisions include machine-readable policy reasoning
- current refresh behavior remains representable
- `rsync` path selection remains supported through policy decisions

Risks:

- turning policy objects into orchestration objects
- losing simple default behavior under too many policy knobs

## Phase 8: Derived Tasks And Indexes As Planned Work

Objective:

- integrate derived tasks and indexes into the planner instead of running them
  as post-sync side effects

Work:

- define dependency-aware derived task and index interfaces
- plan derived and index operations through the planner
- add explicit reconciliation semantics for collection-like outputs
- keep current fanout behavior available through a REST collection adapter or
  compatibility layer

Acceptance criteria:

- derived work and indexes are included in the sync plan with dependencies
- rebuild behavior is requestable and test-covered
- deletion or tombstone behavior for collection outputs is explicit

Risks:

- breaking current `RestBaseFanoutTask` workflows without a migration shim
- mixing planner dependencies with runtime storage traversal in ad hoc ways

## Phase 9: Query Service

Objective:

- move querying onto a dedicated service over typed targets and stores

Work:

- define `QueryTarget` for root, source, artifact, store, index, and run targets
- implement `QueryService`
- keep current query target forms valid
- add artifact and run queries without regressing current source locator support

Acceptance criteria:

- existing query calls continue to work
- query results expose both logical and physical perspectives when available
- new query target kinds are individually tested

Risks:

- leaking store internals into query payloads
- regressing current `source:<id>#/pointer` behavior

## Phase 10: Events, Locks, And Concurrency Controls

Objective:

- add explicit observability and execution coordination

Work:

- define `Event` and `EventBus`
- emit events for planning, execution, artifact materialization, failures, and
  completion
- introduce a lock manager with a filesystem lock default
- implement executor concurrency configuration including bounded parallelism and
  per-adapter or per-source limits

Acceptance criteria:

- one-root-at-a-time sync safety is explicit
- parallel execution respects dependencies
- events are emitted through a consistent interface

Risks:

- making events mandatory for normal use
- introducing concurrency before operation dependencies are mature

## Phase 11: Public Engine API

Objective:

- expose the new top-level `Engine` and composed `Runtime` surfaces

Work:

- implement Tier 1 `Engine`
- implement Tier 2 configurable `Engine`
- expose Tier 3 `Runtime`
- add builders or adapters from current config objects to the new API
- update package exports and documentation

Compatibility path:

- keep `sync(cfg)` available as a wrapper over the runtime
- keep current exported config and source types until a later deprecation phase

Acceptance criteria:

- ordinary users can use the new `Engine` without understanding runtime internals
- advanced users can compose a custom runtime
- compatibility wrappers are tested and documented

Risks:

- exposing an `Engine` facade before internal seams are stable
- accidentally creating two divergent orchestration implementations

## Phase 12: Deprecation And Cleanup

Objective:

- remove obsolete internals only after the replacement architecture is proven

Work:

- identify modules now serving only compatibility roles
- move manifest compatibility logic into a dedicated `compat` package
- deprecate legacy configuration and orchestration surfaces with explicit user
  guidance
- remove dead branching and duplicate implementations

Acceptance criteria:

- deprecated paths have clear replacements
- compatibility remains explicit until the project chooses a removal release
- the codebase has one canonical orchestration path

## Testing Plan

Testing must evolve with the architecture. Required test layers:

- unit tests for source models, operations, policy decisions, and adapters
- component tests for planner and executor integration
- compatibility tests for legacy `sync(cfg)` and manifest/query behavior
- regression tests for derived fanout and `rsync` path sync behavior
- query/status tests covering both old and new target forms

Special focus areas:

- manifest compatibility
- deterministic planning output
- artifact provenance recording
- dry-run semantics
- concurrency safety

## Documentation Plan

At each major phase:

- update `README.md` only when user-facing behavior changes
- keep `DESIGN.md` aligned with the intended architecture
- update this plan to reflect completed, active, and deferred phases
- add ADRs for irreversible design decisions that materially constrain future
  work

## Exit Criteria For The Migration

The v2 migration is complete when:

- the runtime owns planning, execution, storage, policy, and query composition
- built-in protocol behavior is adapter-driven
- artifacts and provenance are first-class
- derived work and indexes are dependency-aware planned operations
- the new `Engine` is the preferred public API
- compatibility surfaces for current functionality are either retained
  intentionally or explicitly deprecated
- the test suite covers both the new architecture and the supported legacy
  compatibility path
