# PLAN.md

Purpose: define how the current design will be completed, including milestone ordering, dependencies, and contingent follow-on work. Current completion state belongs in `STATUS.md`; concrete execution tasks belong in `TODO.md`.

`DESIGN.md` is authoritative for architecture, requirements, and invariants. ADR-0010 defines the clean-break public API and removal of alpha compatibility; ADR-0007, ADR-0008, and ADR-0009 remain authoritative for source revisions, dataset identity, detached exports, and maintenance except where ADR-0010 explicitly supersedes compatibility retention.

## Execution strategy

Treat the next API as a deliberate pre-1.0 break. Do not preserve an old caller while designing the new surface. First establish the small semantic API and the internal capabilities it requires, then migrate canonical execution to those capabilities, delete compatibility completely, and only afterward run durability/export/downstream acceptance against the reduced system.

### Milestone 1 — Establish the clean public boundary

Implement the contract in `docs/api.md` before broad compatibility deletion so canonical code has a stable migration target.

The target separates:

- `Repository` durable access from `Engine` acquisition orchestration;
- repository/storage configuration from per-run `SyncRequest` intent;
- open source/adapter identity from protocol-specific built-in source types;
- one ordinary `SyncResult` from detailed planner/executor records;
- `DatasetSpec`, `Dataset`, and `DatasetManifest` from selector/materializer implementation classes;
- ordinary root-level API from advanced extension/internal types.

Repository creation/opening must make mode explicit and use one public repository type. Public low-level writer lifecycle primitives move behind internal capabilities. Public temporal parameters use timezone-aware datetimes.

Exit condition: examples for acquisition, read-only inspection, dataset resolution/freeze/export, maintenance, and an external source adapter can be expressed through the target API without compatibility names or private implementation details.

### Milestone 2 — Migrate canonical internals to the new contracts

Move planner, executor, adapters, validators, collection acquisition, derived tasks, policies, queries, datasets, and maintenance onto the clean source/repository/result contracts.

Replace the closed `SourceKind` dispatch model with namespaced adapter identity and typed built-in sources. Split broad repository read/write capabilities so each component depends only on what it needs. Keep planner/executor detail available internally or from advanced submodules without making those records ordinary package-root concepts.

Exit condition: canonical acquisition, derivation, validation, querying, datasets, and maintenance run without importing any compatibility, merged-manifest, mirror-state, old schema, or legacy source/config type.

### Milestone 3 — Delete backwards compatibility completely

Use `docs/compatibility-inventory.md` as a finite deletion inventory, not a support matrix.

Delete the compatibility package, deprecated sync/config/manifest/state/query presentation stack, mirror/output projections, adoption and alias helpers, TTL-cache compatibility, import aliases, historical schema migrations, old repository-opening paths, and compatibility-only tests/fixtures/docs.

The maintained runtime opens only the clean-break schema. Unsupported older repository schemas fail clearly rather than migrating in place. BVP and other downstream callers migrate to the new API; they do not keep compatibility code alive.

Exit condition: there is no maintained backwards-compatibility implementation and repository/package architecture checks prevent its reintroduction.

### Milestone 4 — Re-validate durability on the reduced mutation surface

After compatibility deletion, re-audit writer coordination, initialization, content staging, validation, metadata commit, crash recovery, reachability, and cleanup against the actual remaining mutation paths.

Do not broaden this milestone into historical retention/pruning. Safe cleanup removes only storage objects that are unreachable from surviving authoritative metadata.

Exit condition: destructive maintenance cannot race supported writers, and recovery/cleanup cannot invalidate or fabricate repository evidence.

### Milestone 5 — Close dataset and detached-export acceptance through the new API

Exercise the complete resolve/freeze → export → reopen/verify workflow only through the target public API.

Include incomplete-coverage behavior, source-definition changes, missing/corrupt content, export collision/path safety, concurrent destination publication, and native Linux publication/CoW branches. Verify a generic consumer can use the detached manifest without Efloud internals or SQLite.

Exit condition: reproducible handoff is domain-neutral, detached, and independent of compatibility representations.

### Milestone 6 — Complete release verification

Run the non-mutating quality gate, supported-Python matrix, packaging checks, architecture contracts, coverage comparison, repository-wide legacy-name scan, and remote CI against the committed checkout.

The packaging contract should explicitly check the intended package-root exports and absence of removed compatibility modules.

Exit condition: the committed implementation matches `docs/api.md`, contains no accidental compatibility surface, and passes all required local and CI gates.

### Milestone 7 — Validate the downstream BVP boundary

Migrate and run the BVP acceptance fixture using only the clean public source/repository/dataset API and detached manifests.

Classify any failure first as either a generic Efloud capability gap or a BVP-specific interpretation requirement. Generic gaps may extend the clean API; BVP-specific semantics remain in BVP.

Exit condition: BVP can implement its workflow without private SQLite, old manifests/tree state, compatibility projections, or legacy fanout/derived interfaces.

## Contingent later milestones

These remain outside the clean-break implementation unless a concrete requirement activates them.

### Historical retention and pruning

If storage pressure requires deletion of valid historical state, define explicit retention roots and policies first. Preserve retained datasets and transitive provenance and require dry-run impact reporting before destructive pruning.

### Additional source adapters and plugin discovery

Add a protocol adapter when a real source cannot be represented by existing built-ins. New adapters use namespaced adapter identity and normalized inventory/acquisition evidence without adding protocol-specific repository semantics. Plugin discovery may later become another way to populate the same registry; it must not change source or Engine semantics.

### Advanced storage and distribution

Recursive Merkle trees, mutable refs, replica/availability tracking, alternate blob stores, remote metadata stores, and distributed coordination remain behind repository semantics. The clean API must not encode local filesystem paths, SQLite, or POSIX locks as permanent semantic requirements.

## Verification policy

Every milestone must preserve the architecture and invariants in `DESIGN.md` and relevant ADRs. Completion requires focused regression tests for changed repository invariants, explicit non-mutation tests for read mode and dry-run behavior, clean-schema initialization coverage, package/import contracts, and downstream fixtures that use generic public interfaces rather than private implementation details.
