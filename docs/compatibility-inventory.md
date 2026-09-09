# Alpha compatibility removal inventory

ADR-0010 removes backwards compatibility as a requirement. This document is now a
finite deletion/replacement inventory: every listed alpha compatibility facility
must either disappear or be replaced by a canonical semantic equivalent. Nothing
listed here is retained merely because an old Efloud or BVP caller uses it.

The active execution queue is in `TODO.md`.

## Removal and replacement inventory

| Facility | Current role / callers | Clean-break disposition |
| --- | --- | --- |
| `compat.repository_recording.RepositorySyncRecorder` | Historical recorder tests only | Delete. Preserve only canonical lifecycle/provenance regressions. |
| `compat.repository_derived.import_derived_results` | Historical derived/import tests | Delete. Canonical derived execution records typed outputs/provenance directly. |
| remaining `efloud.compat.*` | Legacy extension adapters, materialization/path lookup, outputs, registry aliases | Delete the package completely. No permanent compatibility namespace remains. |
| `sync.sync` | Deprecated `sync(cfg)` entry point | Delete. `Engine.sync()` is the acquisition entry point. |
| `models.Manifest*`, `NormalizedManifest`, old `SyncResult` | Merged-manifest compatibility contract | Delete. `SyncResult` becomes the canonical semantic result; detached dataset interchange uses `DatasetManifest`. |
| `EngineConfig` | Mixes canonical runtime intent with cache/mirror/log/output/legacy settings | Delete/replace. Storage/open configuration, `Engine` construction, and per-run `SyncRequest` are separate. |
| `registry.SourceKind`, monolithic `SourceDefinition` | Closed protocol enum plus many protocol-specific optional fields | Replace with open `Source` protocol and typed built-in sources keyed by namespaced adapter identity. |
| `source_aliases` | Alpha naming/compatibility aliases | Delete. Domain packages own naming migrations; source IDs are explicit. |
| `adoption` | Imports retained alpha mirror/filesystem content | Delete. Old stores are not adopted by the maintained runtime. |
| `repository_compat` | Repository-to-merged-manifest serializer | Delete. |
| `repository_outputs` / `compat.outputs` | Manifest/mirror projection publication | Delete. Canonical sync has no projection side effects. |
| `repository_state` | Repository-to-mirror-state projection | Delete. |
| `manifest` | Old merged manifest reader/serializer | Delete. Dataset manifests remain a separate clean contract. |
| `state` | Legacy mirror/tree state utility | Delete or move any generally useful tree primitive into canonical tree code with a new API; no old import surface survives. |
| `resolve` / compatibility materialization lookup | Path-oriented content resolution | Delete. Typed repository reads and `Dataset.export` replace path lookup. |
| TTL cache portion of `indexing` | Wall-clock external/source cache compatibility | Delete. Retain only deterministic repository-backed derived-index semantics where still useful. |
| manifest-shaped policy methods | Planner compatibility with old manifest/cache model | Delete. Policies receive typed repository/source evidence only. |
| `query`, `status`, `health`, `store_inspection`, `source_results`, `summary` | Old path/cache/status presentation stack | Delete as compatibility facades. Retain/rebuild only functionality justified by typed repository APIs or CLI presentation. |
| `RepositoryQueryService` string target grammar | Current typed-repository-backed but parser-oriented inspection API | Remove from the ordinary Python API; keep only if a CLI needs it, layered above typed reads. |
| `ReadOnlyRepository` public class | Duplicates most read methods to enforce read-only behavior | Replace with `Repository.open(..., mode="r")`; retain backend-specific internal read-only stores as needed. |
| `RepositoryView` broad public protocol | Large general read capability exposed at package root | Make internal and split into narrow capabilities for datasets, adapters, validation, and queries. |
| public low-level `Repository` writer lifecycle methods | Executor-facing run/operation/ingest/snapshot/validation mutation | Move behind an internal writer capability/service; ordinary `Repository` exposes semantic reads, datasets, and deliberate maintenance only. |
| `EngineSyncResult` + nested execution result stack | Internal execution structure exposed as normal API | Collapse ordinary caller output into one canonical `SyncResult`; detailed planning/execution records remain advanced/internal. |
| `DerivedTask` / `RepositoryDerivedTask` legacy shapes | Planner/operation recording and historical callers | Replace with one canonical derived-task contract using exact inputs, declared outputs, and narrow read context. No legacy adapter. |
| `FanoutEnumerator` / `RestBaseFanoutTask` legacy shape | Collection execution and BVP legacy caller | Replace with canonical collection-source enumeration/fetch contract. BVP migrates. |
| `sqlite_metadata_v3` | Import alias | Delete. |
| schema-v1/v2 migration SQL and migration fixtures | In-place opening of old repository roots | Delete. Keep only clean-schema initialization and future migrations introduced after the clean break. |
| compatibility directories (`http`, `mirrors`, `log`, legacy cache/output paths) | Alpha filesystem projections/operational layout | Remove from canonical configuration/layout. Keep only operational directories required by current transports, under an explicitly non-authoritative area. |
| package-root low-level exports | ~100 public names spanning internals | Reduce to the target ordinary API in `docs/api.md`; advanced types live in focused submodules. |

## Downstream callers

BVP currently uses legacy manifest/tree/fanout interfaces. Those callers must be
changed to consume Efloud's public repository/dataset/source contracts. They are not
support requirements for Efloud compatibility code.

BVP-specific catalog rules, scientific classification, expected artifacts, domain
validation, and naming conventions remain in BVP. If migration exposes a genuinely
generic capability gap, implement that capability in the clean Efloud API rather
than restoring an old representation.

## Old repository policy

Only the repository schema produced by the clean-break implementation is supported.
The runtime must fail clearly when asked to open an unsupported historical schema;
it must not silently migrate or partially interpret it.

A one-off converter may be written outside the maintained runtime if old data later
proves valuable. Such a converter must read the old format explicitly and emit the
new public interchange/repository inputs; it must not reintroduce historical schema
code into normal repository opening.

## Finite removal checklist

- [ ] Land the target source, repository, engine/result, dataset, error, and time APIs.
- [ ] Migrate planner/executor/adapters/validators/derived work to the new internal
      capabilities without compatibility types.
- [ ] Migrate BVP acceptance fixtures to the new public boundary.
- [ ] Delete `efloud.compat` and every obsolete module/category listed above.
- [ ] Delete historical schema migrations, aliases, adoption paths, and their tests.
- [ ] Remove old root exports, config fields, imports, docs, examples, fixtures, and
      architecture exceptions.
- [ ] Add import/packaging contracts that forbid reintroduction of compatibility,
      old projection modules, and low-level package-root exports.
- [ ] Run a repository-wide search for legacy names and classify every remaining
      occurrence as canonical terminology, historical changelog/ADR text, or a bug.
- [ ] Verify a clean repository can acquire, inspect, freeze, export, reopen,
      verify, maintain, and recover with no compatibility modules installed.

Completion means there is no maintained backwards-compatibility implementation,
not merely that canonical execution no longer imports it.
