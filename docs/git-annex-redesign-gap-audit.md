# Git/git-annex redesign gap audit

Purpose: establish the finite migration boundary for the experimental rewrite before deleting infrastructure. This is an implementation audit, not a second architecture specification; ADR-0011 records the experimental decision.

## Baseline

The experiment starts from `main` commit `53023cf9482e7a2cfca20a0f71f5cb05483ba1b8`.

The current implementation already contains important semantic machinery that should survive the rewrite:

- stable `ArtifactKey`, source identity, observations, explicit absences, source snapshots, and validation evidence;
- latest/as-of source selection and complete-snapshot selection;
- deterministic dataset specification/membership identity and detached manifests;
- declarative `efloud.toml`, canonical lock generation, and optional lock signing;
- source-definition revision history and provenance;
- writer coordination, crash recovery, and fail-closed maintenance semantics.

The experiment should replace infrastructure around those semantics rather than redesigning them without evidence.

## Responsibility migration matrix

| Current area | Current owner | Experimental target | Action |
|---|---|---|---|
| immutable byte store | `blob_store.py` / `FilesystemBlobStore` | git-annex | replace, then delete production filesystem CAS |
| content hash identity | `ContentId` + SHA-256 CAS | git-annex key wrapped by `ContentRef` | replace |
| byte-integrity verification | Efloud hashing | git-annex | replace |
| content presence / local path | CAS object paths | git-annex key/location operations | replace; remove semantic dependence on object paths |
| physical replication / get / drop | Efloud storage/maintenance code | git-annex | replace |
| filesystem tree identity | `TreeId`, `TreeEntry`, custom indexing/tree persistence | Git tree/commit | replace production identity mechanism |
| source inventory semantics | adapters + inventory/reconciliation | Efloud | retain and narrow |
| generic HTTP/rsync transfer | `transport/`, protocol runtime/retry/cache code | git-annex where practical | delete after source-specific gaps are classified |
| source-specific authenticated/API retrieval | adapters | Efloud-assisted temporary retrieval -> git-annex ingest | retain only where required |
| upstream Git repository history | not first-class | `GitSource` + Git source adapter; native refs/commits/blobs remain source evidence while exact file bytes enter `ContentStore` | add |
| semantic metadata | SQLite metadata/repository records | Efloud catalog | retain, shrink to unique semantics |
| public durable facade | `Repository` | `Repository` facade over catalog + content/tree infrastructure | retain public boundary; split internals |
| generic derivation DAG/execution | `derivation.py`, executor paths | DVC/downstream | remove from core |
| acquisition orchestration | planner/reconciler/executor/`Engine` | narrower `Engine` | retain only observation/acquisition orchestration |
| dataset semantic identity | datasets/manifests | Efloud | retain and make explicitly path-independent |
| detached lock | `project.py`, `lockfile.py` | Efloud canonical lock | retain and extend with annex/Git evidence |
| materialized layouts | export/materialization code | Efloud layout layer; optionally DataLad | separate from `DatasetId` |
| dataset distribution | custom export/distribution behavior | plain Git/git-annex; optional DataLad | reduce |
| computational handoff | currently internal derivation support | deterministic Efloud lock consumed by DVC/other tools | add boundary, not executor |

## Semantic characterization required before destructive replacement

The following behaviors must have explicit tests independent of a particular storage backend:

1. repeated observation of unchanged bytes records new provenance/evidence without duplicating semantic content;
2. changed bytes for one `ArtifactKey` create a new content identity without rewriting earlier observations;
3. explicit absence is recorded only from complete-enough inventory coverage;
4. partial, interrupted, or query-scoped inventory cannot prove global absence;
5. interrupted acquisition cannot create authoritative metadata referencing unavailable content;
6. semantic validation failure is distinct from byte-integrity failure;
7. unchanged content can accumulate newer validation evidence;
8. exact snapshot resolution is deterministic;
9. latest and latest-before resolution are deterministic and use observation time explicitly;
10. multi-source composition preserves source distinctions required by semantics;
11. canonical manifest bytes and `DatasetId` are deterministic across repeated resolution;
12. filesystem path/layout changes do not change semantic dataset identity;
13. later source/config/acquisition changes do not mutate frozen dataset membership or evidence;
14. incomplete snapshots cannot satisfy complete-reproducibility claims;
15. detached manifests/locks remain verifiable without SQLite or repository-layout knowledge.

Existing tests may satisfy an item; the experiment should reuse them when they assert the semantic contract rather than storage implementation details.

## Phase A evidence map

The semantic characterization is intentionally mapped to storage-independent assertions. Tests may still execute through the current backend until the cutover, but the listed assertion is not the legacy CAS/tree/transport mechanism itself.

| # | Characterization | Retained evidence |
|---|---|---|
| 1 | unchanged bytes create new observations without new semantic content | `tests/unit/test_repository.py::test_content_dedup_and_observation_history` |
| 2 | changed bytes create new content without rewriting history | `tests/unit/test_dataset_export_public_acceptance.py::test_frozen_membership_and_detached_evidence_ignore_later_source_changes` |
| 3 | absence requires sufficient complete coverage | `tests/unit/test_absence_evidence.py::test_inventory_absence_requires_complete_coverage`, `::test_inventory_absence_requires_target_inside_scope` |
| 4 | partial/scoped inventory cannot prove global absence | `tests/unit/test_inventory_reconciliation.py::test_incomplete_inventory_never_infers_absence`, `::test_complete_scoped_inventory_only_infers_absence_inside_known_scope`, plus public incomplete-snapshot acceptance |
| 5 | interrupted acquisition cannot create authoritative references to unavailable content | `tests/unit/test_phase14_17.py::test_blob_before_metadata_commit_is_a_safe_orphan`; preserve the metadata atomicity assertion while replacing blob-path cleanup details |
| 6 | semantic/source validation is distinct from byte integrity | `tests/unit/test_phase12_validation.py::test_required_http_integrity_failure_does_not_advance_source`, `::test_invalid_json_fails_validation_without_mutating_content` |
| 7 | validation evidence is reusable/versioned for unchanged content | `tests/unit/test_phase12_validation.py::test_validation_reuses_content_and_validator_version_evidence`, `::test_invalid_gzip_is_reusable_validation_evidence` |
| 8 | exact snapshot resolution is deterministic | `tests/unit/test_phase14_17.py::test_snapshot_reopens_elsewhere_and_ignores_later_mutation`, `::test_partial_snapshots_never_become_complete_datasets` |
| 9 | latest/latest-before are observation-time deterministic | `tests/unit/test_repository.py::test_latest_before_dataset_selection` |
| 10 | multi-source composition preserves source/role evidence | `tests/unit/test_semantic_characterization.py::test_multi_source_dataset_preserves_source_and_role_evidence` |
| 11 | repeated resolution/export produces stable dataset/manifest identity | `tests/unit/test_dataset_export_public_acceptance.py::test_resolve_is_read_only_while_freeze_persists_same_identity`, `tests/unit/test_phase14_17.py::test_materialization_is_detached_deterministic_and_read_only` |
| 12 | repository path and export layout do not affect `DatasetId` | `tests/unit/test_repository.py::test_dataset_identity_is_independent_of_repository_location`, `tests/unit/test_semantic_characterization.py::test_dataset_identity_is_independent_of_detached_export_layout` |
| 13 | frozen membership/evidence survives later source changes | `tests/unit/test_dataset_export_public_acceptance.py::test_frozen_membership_and_detached_evidence_ignore_later_source_changes` |
| 14 | incomplete snapshots cannot establish complete reproducibility | `tests/unit/test_dataset_export_public_acceptance.py::test_incomplete_source_snapshot_never_implies_absence_or_reproducibility`, `tests/unit/test_phase14_17.py::test_partial_snapshots_never_become_complete_datasets` |
| 15 | detached manifests/locks are repository-layout independent | `tests/unit/test_dataset_export_public_acceptance.py::test_freeze_export_manifest_reopens_and_verifies_after_repository_is_gone`, `::test_generic_standard_library_consumer_validates_manifest_and_bytes`, `tests/unit/test_project_declaration.py::test_project_sync_lock_roundtrip_and_detached_source_resolution` |

No additional broad characterization suite is required. Future tests should be added only when a replacement boundary exposes a concrete semantic gap.

## Legacy-only test classification

The following assertions are not requirements of the replacement architecture and should be deleted or rewritten when their owning subsystem is removed:

| Legacy assertion family | Current examples | Disposition |
|---|---|---|
| filesystem CAS object paths/counts/layout | `test_blob_store_contract.py`, blob-path/count assertions in repository and acceptance tests | delete; retain only content immutability/dedup/presence semantics through `ContentStore` |
| custom SHA-256 storage verification and corruption mechanics | `FilesystemBlobStore` corruption/path tests, CAS-specific maintenance checks | replace with real git-annex verification/presence/drop/reacquire integration tests |
| orphan-blob filesystem scanning and CAS reachability cleanup | maintenance portions of `test_phase14_17.py` | replace with fail-closed annex-aware maintenance; do not preserve CAS traversal |
| custom `TreeId`/`TreeEntry` hash persistence | `test_indexing.py`, tree-hash/path assertions in snapshot tests | delete production mechanism; retain exact source membership/completeness semantics and replace tree evidence with Git |
| transport implementation internals | low-level HTTP/rsync retry/cache/process assertions in `test_transport_http_utils_rsync.py` | delete when delegated; retain only adapter/source evidence behavior that Efloud still owns |
| generic derivation DAG/execution/reuse | `test_engine_derived.py`, derivation-specific portions of phase 8/11 tests | delete from core; retain generic observation provenance needed for acquisition semantics |
| legacy schema migration support | historical schema/migration tests | reject unsupported pre-experiment formats explicitly; do not preserve migration code in normal runtime |

Tests that mix a retained semantic assertion with one of these implementation assertions should be split during the corresponding cutover instead of retained wholesale.

## Persisted semantic field classification

SQLite remains a semantic catalog, not a second content/tree/workflow implementation.

| Persisted concept | Classification | Experimental destination |
|---|---|---|
| source ID and source-definition revisions | keep | catalog |
| run/operation identity, lifecycle, producer/version, normalized acquisition parameters | keep | catalog provenance |
| logical artifact key | keep | catalog |
| immutable content reference, byte size, media type | keep, identity source changes | catalog stores annex-backed `ContentRef`; git-annex owns byte identity/presence/integrity |
| physical content path/location/copy count | derive/delete | query git-annex; never semantic catalog identity |
| observations and explicit absences | keep | catalog temporal evidence |
| provenance edges | keep | catalog |
| semantic/source validation evidence | keep | catalog |
| storage-integrity validation records generated by Efloud | delete | git-annex verification owns byte integrity |
| source snapshot time/scope/completeness/evidence | keep | catalog |
| exact source-snapshot membership binding | keep | catalog semantic membership/evidence |
| custom `TreeId` and persisted `TreeEntry` hash identity | delete/replace | Git tree/commit evidence; not `DatasetId` |
| dataset specification, frozen dataset identity, exact members, roles, resolution evidence | keep | catalog and detached manifest/lock |
| materialization/export filesystem paths as authoritative state | delete | layout/export layer only; optional operational audit must not affect identity |
| generic derivation keys/task execution state | delete from core | downstream DVC/consumer workflow |
| historical alpha schema compatibility/migrations | delete | clean-break current schema plus one-shot external migration if later required |

## Public contract migration destination

- `Repository`: retained public semantic facade; internally composes catalog, annex content custody, and Git tree/history capabilities.
- `Engine`: retained but narrowed to discovery/reconciliation/acquisition/observation orchestration.
- `Source` and built-ins: retained declarative contracts using stable namespaced adapter/provider identity.
- `DatasetSpec`, `Dataset`, and `DatasetManifest`: retained as semantic intent, exact immutable membership, and portable detached evidence.
- `efloud.toml`: retained as editable intent and continues to round-trip the same semantic models as Python APIs.
- `efloud.lock`: retained as canonical exact resolved state and extended with Git/git-annex evidence without making either tool's repository identity the Efloud dataset identity.

## Git repositories as first-class temporal sources

Git has two independent roles in the redesign and they must not be conflated:

1. Git is Efloud infrastructure for filesystem-tree/history evidence produced by Efloud itself.
2. A remote or local Git repository may also be an external data source observed by Efloud.

The second role is modeled through the ordinary source/observation system. A Git repository is not a parallel repository ontology and its commit, tree, or blob IDs do not become Efloud artifact, content, observation, or dataset IDs.

### Declarative source

Add a first-class `GitSource` whose declaration contains only source intent, for example:

```python
GitSource(
    id="project-x",
    remote="https://example.org/project-x.git",
    refs=("refs/heads/main",),
    paths=("data/**",),
)
```

The source definition must identify the remote and selected refs/path scope deterministically. Execution state such as clone location, fetch state, and temporary worktrees belongs to the adapter/runtime rather than the declarative source.

### Logical artifact identity

By default, one selected repository-relative path is one logical artifact:

```text
ArtifactKey = source:<source-id>:path:<repository-relative-path>
```

The path identifies the upstream logical file, not Efloud storage. A file's bytes may change many times while its `ArtifactKey` remains stable.

Rename detection must not silently redefine identity. Git rename detection is heuristic, so a rename is conservatively modeled as absence of the old path plus appearance of the new path. An adapter or domain-specific provider may record an explicit provenance relationship when stronger identity evidence exists.

### Native revision evidence and observation time

Importing Git history exposes source states that predate the moment Efloud learned about them. Efloud must therefore keep epistemic observation time separate from source-native revision evidence:

- `observed_at`: when Efloud obtained the evidence;
- `source_revision`: upstream commit object ID;
- `source_blob`: upstream blob object ID for a content-bearing file state;
- `source_time`: upstream commit time, retained as source-provided metadata rather than Efloud observation time;
- parent revision IDs: retained where needed to preserve the upstream revision DAG.

Historical commits discovered during one fetch must not receive fabricated old `observed_at` values. Commit timestamps also must not be treated as an authoritative total ordering of Git history; ancestry is the native ordering evidence.

The catalog may use a focused source-revision record or equivalent internal representation for commit/parent/ref evidence. This is advanced source evidence and does not belong at the package root.

### Acquisition and history import

A Git source adapter should:

```text
fetch selected refs into a managed Git cache
        ↓
record observed ref -> commit mappings
        ↓
walk newly discovered reachable revisions
        ↓
identify selected-path state transitions
        ↓
extract exact blob bytes
        ↓
ingest bytes through ContentStore / git-annex
        ↓
record ordinary Efloud observations or absences
```

The managed Git clone/bare repository is a disposable acquisition cache. Its filesystem path and object layout are not semantic state. Deleting that cache must not invalidate already-recorded Efloud artifact history.

For each changed file state, the blob bytes are ingested through the same `ContentStore` used by REST, rsync, local files, and other adapters. Therefore identical bytes obtained from Git and another source resolve to the same `ContentRef`; the Git blob ID remains source-native provenance/change evidence rather than a second content identity.

A deletion at an imported commit becomes ordinary absence evidence when the adapter has sufficient commit-tree/path-scope coverage to establish it. Unchanged commits need not duplicate content observations merely because another commit exists; Efloud records meaningful state/evidence transitions while preserving enough source-revision evidence to explain the history.

### Ref movement, rewritten history, and repeated fetches

Repeated acquisition must be incremental and idempotent:

- already-known native revisions do not create duplicate semantic observations;
- newly reachable commits append history;
- a branch/tag moving to a new commit creates new ref-observation evidence;
- force-pushes and rebases never rewrite or delete Efloud's previously recorded observations;
- revisions that later become unreachable upstream remain historical evidence that Efloud actually obtained earlier.

### Unified artifact history

Git-backed files must be queryable through the same public artifact-history surface as REST responses and rsync files. Conceptually:

```text
Repository.history(ArtifactKey(...))
    -> content observation
    -> content observation
    -> absence observation
    -> content observation
```

Git-originated records carry richer native revision evidence, but callers should not need a separate Git-specific history API merely to ask which exact contents a logical artifact has had. Git-aware callers may additionally inspect ancestry/ref evidence rather than flattening the native DAG by timestamp.

### Identity boundaries

The following identities remain distinct:

```text
ArtifactKey          Efloud logical source artifact
ContentRef           exact bytes, backed by git-annex
ObservationId        Efloud historical evidence
upstream commit OID  source-native revision evidence
upstream blob OID    source-native content/change evidence
Git tree/commit      optional Efloud projection/history evidence
DatasetId            immutable semantic dataset membership
```

No upstream Git OID and no Efloud projection commit participates in `DatasetId` unless explicitly represented as semantic source evidence by the dataset specification.

### Git-source acceptance criteria

The Git source implementation is acceptable when:

1. a Git repository and ref/path scope can be declared as a normal `Source`;
2. one repository-relative file path is exposed as a stable `ArtifactKey` across content changes;
3. distinct historical file contents become ordinary annex-backed `ContentRef`s;
4. identical bytes obtained through Git and REST/rsync/local acquisition receive the same Efloud content identity;
5. deletion and reappearance produce the same absence/content history states used by other source types;
6. historical commits imported later preserve actual Efloud `observed_at` time separately from source commit time;
7. Git ancestry/ref evidence is retained without treating commit timestamps as total history order;
8. repeated fetches are idempotent and append only newly discovered evidence;
9. force-pushed or rebased upstream history does not rewrite previously recorded Efloud evidence;
10. removing the managed Git acquisition cache does not invalidate recorded artifact history;
11. heuristic rename detection does not silently change `ArtifactKey` identity;
12. ordinary artifact-history queries expose Git file versions through the same semantic record types as REST and rsync history;
13. upstream commit/tree/blob IDs never become `DatasetId` or replace `ContentRef`.

## Phase A acceptance criteria — characterization and boundaries

Phase A is complete when:

- every characterization item above maps to at least one focused test;
- tests that only assert legacy CAS paths, custom tree hashes, transfer internals, or generic derivation execution are classified for deletion rather than preserved as requirements;
- no new compatibility API is introduced;
- the current persistent semantic fields are classified as `keep`, `derive from git-annex/Git`, or delete;
- the public `Repository`, `Engine`, source, dataset, manifest, declarative-project, and lock contracts have an explicit migration destination.

The evidence map and classifications above satisfy the design portion of Phase A. Phase A is considered validated only after the exact branch head containing the characterization tests passes the applicable local checks.

## Phase B acceptance criteria — infrastructure ports

Introduce the smallest ports needed for replacement:

- `ContentStore`: annex-key/content custody operations only;
- `TreeStore`: Git tree/commit operations only;
- `Catalog`: semantic records and queries only;
- `SourceAdapter`: discovery/logical identity/change/coverage semantics only;
- `Validator`: semantic validation only.

Phase B is complete when:

- domain/selection/dataset code does not import the filesystem CAS;
- source adapters do not directly place durable bytes;
- `Repository` composes semantic catalog and infrastructure ports rather than being the byte store itself;
- pure fakes support semantic unit tests;
- the existing backend may remain only until the first git-annex integration slice is proven.

## Phase C acceptance criteria — Git/git-annex proof

Before cutting over production storage:

- initialize an ordinary Git/git-annex repository deterministically;
- use a cryptographic content-only annex backend (no filename semantics in key identity);
- ingest identical bytes twice and obtain the same annex key;
- verify, drop, and reacquire content without changing Efloud semantic identity;
- register/acquire ordinary URLs using git-annex where practical;
- use machine-readable command output where available;
- map subprocess failures into stable Efloud infrastructure errors;
- test interrupted/repeated operations and unusual filenames on real filesystem primitives;
- record Git commits for projected source trees without using commit/tree identity as `DatasetId`.

## Explicit non-goals for the first slice

Do not yet:

- add DataLad as a dependency;
- add DVC as a dependency;
- preserve historical repository schemas in normal runtime code;
- expose git-annex object paths as public API;
- rewrite source scientific/domain semantics;
- expose catalog/writer implementations at the package root;
- implement a generic external-workflow abstraction.

## First implementation slice

1. Preserve/complete semantic characterization tests.
2. Add narrow content/tree/catalog protocols without changing package-root exports.
3. Add a centralized Git/git-annex command boundary and real temporary-repository integration tests.
4. Introduce annex-backed `ContentRef` only after the command boundary is proven.
5. Cut `Repository` over to the new content backend before deleting the filesystem CAS.

This ordering keeps the experiment falsifiable: if git-annex cannot satisfy the content-custody contract cleanly, the branch can stop before semantic identities or repository persistence are rewritten.

## Git-source implementation slice

Implement `GitSource` only after annex-backed content identity, the catalog boundary, and inventory/absence coverage semantics are stable enough that Git history can exercise them rather than creating a second model.

1. Add declarative `GitSource` with remote, selected refs, and path scope; include it in `efloud.toml` round-tripping through the same source model used by the Python API.
2. Add a namespaced Git source adapter using the existing centralized Git command boundary.
3. Fetch into a managed bare/disposable cache whose path is operational state, not semantic identity.
4. Persist observed ref tips and focused source-native revision evidence (commit ID, parents, source time) needed to explain imported history.
5. Walk only newly discovered reachable revisions and derive selected-path state transitions without relying on rename heuristics for identity.
6. Extract changed blob bytes and ingest them through `ContentStore`; never expose the managed Git object database as Efloud content custody.
7. Translate deletions/reappearances into ordinary absence/content evidence under commit/path coverage rules.
8. Make repeated fetches idempotent and preserve evidence across force-pushes, rebases, ref deletion, and cache recreation.
9. Extend the ordinary artifact-history query so Git file histories return the same observation/absence record types used by REST and rsync sources, with optional native revision evidence attached.
10. Add real-Git integration tests covering linear history, merges, branch movement, deletion/reappearance, force-push, repeated fetch, identical cross-source bytes, unusual paths, and cache deletion.

This slice should precede any work that treats dataset resolution as finished, because a historical Git source is a strong acceptance test that `ArtifactKey`, observation time, source-native revision evidence, absence, and `ContentRef` are truly protocol-independent.
