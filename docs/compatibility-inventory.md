# Phase 16 compatibility inventory and disposition

This inventory is the prerequisite to implementation, based on direct Python
imports, transitive canonical callers, and a read-only inspection of BVP's current
callers. Compatibility support means an explicit boundary, never a representation
required by canonical ingestion. The active work queue is in TODO.md.

## Facilities and owners

| Facility | Current callers / consequence | Classification | Decision and owner |
| --- | --- | --- | --- |
| `compat.repository_recording.RepositorySyncRecorder` | No production caller; historical recorder tests only | Obsolete migration code | Remove; migrate provenance/lifecycle regressions to canonical execution. Repository owns mutation. |
| `compat.repository_derived.import_derived_results` | Recorder above and historical collection/derived tests | Obsolete duplicate implementation | Remove; move meaningful collection/provenance regressions to `collection_recording` and `operation_recording`. |
| `compat.sync_runtime` | No production caller; old phase-runner unit tests | Obsolete duplicate implementation | Remove old orchestration/manifest recording; retain relevant tests against adapters/executor or supported projection utilities. |
| `derived.DerivedTask`, `RepositoryDerivedTask` | Models, planner, operation recorder, fanout; currently manifest-shaped | Required by canonical execution | Replace with explicit read context, exact observation inputs, declared outputs and task result. Derived execution owns provenance. Legacy calls require an adapter. |
| `fanout.FanoutEnumerator`, `RestBaseFanoutTask` | Collection adapter; BVP sync engine; enumerators currently take manifests | Required execution contract plus external legacy caller | Make the canonical enumerator consume a read context and declared inputs. Preserve legacy enumeration through an explicit compatibility adapter; retain shared fanout transport/data types. |
| `collection_adapter`, `operation_recording` calls to `repository_manifest` | Canonical Engine transitively constructs JSON before extension execution | Required today, forbidden in final architecture | Remove both calls. Canonical extensions read RepositoryView and exact input observations. |
| `engine` → `compat.outputs`, `repository_outputs` | Every sync constructs/publishes projections | Required today, forbidden in final architecture | Engine returns semantic execution results only. Compatibility callers explicitly invoke a projection adapter after execution. |
| `models.NormalizedManifest`, `Manifest*`, `SyncResult` | Legacy serializers, inspectors, BVP imports; co-located with EngineConfig | Supported external compatibility data contract | Keep legacy import path as a compatibility facade; canonical configuration moves to a dependency-free configuration module. |
| `repository_compat` | Collection/execution/Engine, legacy query/status, output publisher | Supported projection serializer | Remove canonical incoming edges. Keep read-only serialization and repository-existence inspection for explicit legacy consumers. |
| `repository_outputs`, `compat.outputs` | Engine today, projection tests | Supported external output adapter | Retain only explicit invocation after canonical execution. Projection failures must not change recorded run status. |
| `repository_state` | Repository output publisher; mirror-state tests | Supported external projection adapter | Retain read-only repository-to-tree projection. It must not be an ingestion or dataset dependency. |
| `manifest` | Legacy runtime, resolve helper, BVP manifest reader/merge tests; fanout type import | Supported external serializer/reader | Retain for BVP/external projection readers; remove fanout's canonical dependency. No authoritative import or mutation API. |
| `state` | Repository-state adapter, inspection helpers, BVP integrity-tree callers | Supported external tree utility / projection format | Retain existing import surface; it is not repository authority. No canonical executor/read-model dependency. |
| `resolve`, `compat.materialization` | Legacy projection path lookup and BVP-related compatibility consumers | Supported deprecated path adapter | Retain explicit compatibility reads; canonical materialization is DatasetMaterializer. Never use lookup as repository content authority. |
| TTL portion of `indexing` | Legacy configuration/query and external callers | Supported deprecated cache facility | Isolate TTL declarations from canonical configuration. Keep deterministic repository indexes on a canonical module and retain a compatibility re-export. |
| `policy` manifest arguments | Planner and legacy runtime share refresh interfaces | Required execution policy with legacy shape | Canonical policy receives repository evidence. Adapt legacy manifest policy explicitly if retained; no implicit manifest construction in planner. |
| `query`, `status`, `health`, `store_inspection`, `source_results`, `summary` | Legacy source/cache/status presentation and external callers | Supported compatibility inspection/presentation | Retain facade support; stable queries use RepositoryQueryService/RepositoryStatusService and datasets. Eliminate incoming edges from canonical execution and configuration. |
| `sync.sync` | Deprecated external helper | Supported compatibility entry point | Continue delegating to canonical Engine, then explicitly project its result. No second ingestion path. |
| `schema_migrations` v1/v2 upgrade SQL | SQLite initialization and migration regressions | Supported schema-upgrade mechanism | Retain and test upgrades. Historical SQL is required to open supported stores; it is not an alternative runtime implementation. |
| `sqlite_metadata_v3` alias | No production caller; legacy explicit imports/tests | Supported import alias | Retain trivial re-export of the one canonical SQLite implementation; no subclass or duplicate schema behavior. |

BVP still imports legacy manifest readers and tree utilities. Those are support
requirements for the external adapter surface, not justification for canonical
execution to consume a manifest. BVP scientific classification/catalog rules stay
outside Efloud. No BVP source files are changed by this inventory.

## Finite migration/removal checklist

- [ ] Introduce canonical extension read context, exact inputs, and typed derived results.
- [ ] Migrate collection enumerators and derived execution; implement explicit legacy task/enumerator adapters.
- [ ] Split canonical configuration and deterministic indexing from legacy models/TTL caches.
- [ ] Remove implicit Engine projection generation; retain explicit output/deprecated sync adapters.
- [ ] Remove the three obsolete import/runtime modules and migrate or retire their identified tests.
- [ ] Remove compatibility dependencies from canonical refresh policy and public imports.
- [ ] Enforce the final boundary with import contracts and compatibility-disabled end-to-end tests.
- [ ] Re-run supported schema migration, repository durability, consumer/export, and external BVP acceptance.

Canonical execution/configuration owns none of the retained projection formats.
The compatibility modules own old schemas and path-oriented helper signatures.
Any support gap found during caller migration must be recorded here before changing
this disposition; retaining duplicate ingestion solely to keep an old test is not
an accepted support requirement.
