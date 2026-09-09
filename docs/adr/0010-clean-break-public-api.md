# ADR-0010: Adopt a clean-break public API and remove alpha compatibility

Date: 2026-09-09

Status: Accepted

## Context

Efloud's repository-centered architecture has replaced the original path-, mirror-,
and merged-manifest-centered design, but the package still carries a large alpha
compatibility surface. The package root exports implementation-level planning,
execution, storage, identifier, validation, and adapter types; `EngineConfig` mixes
canonical runtime intent with legacy cache/mirror/output settings; `Repository`
exposes executor-facing mutation primitives; source extensibility is constrained by
a closed `SourceKind` enum; and compatibility serializers, query/status facades,
importers, aliases, historical schema migrations, and mirror/manifest projections
remain in the tree.

The project is pre-1.0. Preserving these alpha interfaces would make the accidental
shape of the migration permanent, increase maintenance cost, and make future
features such as alternate storage, new source protocols, replica tracking,
mutable refs, plugin discovery, and distributed coordination harder to add without
further API churn.

## Decision

Efloud will make a clean break from all alpha public and repository-format
compatibility. Compatibility is not a product requirement for the next API.

The target public model is deliberately small:

- `Repository` owns durable repository access. It is opened or created explicitly
  and may be opened read-only or writable through one public type.
- `Engine` owns acquisition orchestration, planning, execution, policy, adapters,
  and validation. A repository does not expose executor lifecycle primitives as
  ordinary user-facing operations.
- `Source` is an open semantic protocol identified by a namespaced adapter ID.
  Built-in protocol-specific types such as `HttpSource`, `RestSource`,
  `RsyncSource`, and `CollectionSource` provide typed convenience without a closed
  core source-kind enum.
- `SyncRequest` represents per-run caller intent. `SyncResult` is the single normal
  synchronization result rather than a stack of compatibility and executor result
  wrappers.
- `DatasetSpec` is the compositional intensional dataset description. `Dataset` is
  a resolved immutable dataset. `DatasetManifest` is the canonical detached,
  portable representation.
- Advanced extension contracts remain available from focused submodules, not from
  the package root.
- Public temporal arguments use timezone-aware `datetime` values. Internal storage
  may retain numeric timestamps.
- Ordinary API failures use an Efloud exception hierarchy rather than requiring
  callers to distinguish generic `KeyError`, `ValueError`, or `RuntimeError`
  messages.

`Repository.create(location, ...)` and `Repository.open(location, mode=...)` make
creation, migration policy, and mutability explicit. A repository location is a
semantic location/configuration input, not permanently defined as a filesystem
`Path`; the default implementation remains local SQLite plus filesystem CAS.

Repository read functionality is organized through semantic facades such as
artifacts, sources, runs, datasets, provenance, and maintenance. The broad
`RepositoryView` protocol and executor-facing repository mutation methods are
internal capabilities. Read-only behavior is enforced by repository mode rather
than by a second public `ReadOnlyRepository` class.

Dataset resolution distinguishes side effects explicitly:

- `repo.datasets.resolve(spec)` resolves without recording membership.
- `repo.datasets.freeze(spec)` records immutable membership and requires a writable
  repository.
- `Dataset.export(...)` creates a detached/materialized handoff.

The package root should contain only the ordinary semantic API, approximately
10-15 concepts. Planner/executor records, storage implementations, low-level IDs,
registries, validation internals, and repository writer primitives remain in
advanced/internal modules and are not root-level promises.

### Compatibility removal

All alpha compatibility facilities are to be deleted rather than deprecated or
preserved behind adapters. This includes legacy sync/config/manifest/state/query
facades, mirror/output projections, compatibility importers and recorders,
source-alias migration helpers, TTL cache compatibility, import aliases, and
historical repository schema upgrade code.

Only the repository schema produced by the clean-break implementation is supported.
Older Efloud repositories are not opened or upgraded in place. A user who needs old
data may recreate/reacquire it or use a one-off external migration/export tool;
such a tool is not part of the maintained Efloud runtime.

Downstream projects, including BVP, must migrate to the new public API and detached
dataset contract rather than keeping Efloud compatibility APIs alive.

## Consequences

The public surface becomes substantially smaller and more discoverable, while the
internal repository model remains sophisticated. Future storage and coordination
changes can occur behind `Repository`; new acquisition protocols can be added
without editing a core enum; future dataset selectors can be added compositionally;
and refs, replicas, or Merkle-tree representations can be introduced without
changing ordinary acquisition and dataset workflows.

This is intentionally breaking. Existing imports, old repository roots, BVP legacy
manifest/tree callers, and alpha examples may stop working. The change therefore
belongs in a clearly documented pre-1.0 breaking release.

A significant amount of code and tests becomes removable. The goal is removal, not
relocation into a permanent `compat` package.

## Alternatives considered

### Keep compatibility isolated indefinitely

Rejected. Isolation prevents canonical dependencies but retains maintenance cost,
public ambiguity, old repository schemas, and constraints on future API design.

### Gradually deprecate every alpha entry point

Rejected. The project is pre-1.0 and the compatibility surface is large enough that
a long deprecation period would spend substantial effort preserving interfaces that
are not intended to survive.

### Freeze the current primary API and remove only obvious legacy modules

Rejected. The current primary API still exposes too much internal machinery and
contains closed or path-centric choices (`SourceKind`, `EngineConfig`, separate
read-only repository type, broad root exports) that should not become long-term
contracts.
