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
| source-specific authenticated/API retrieval | adapters | Efloud-assisted temporary retrieval → git-annex ingest | retain only where required |
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

## Phase A acceptance criteria — characterization and boundaries

Phase A is complete when:

- every characterization item above maps to at least one focused test;
- tests that only assert legacy CAS paths, custom tree hashes, transfer internals, or generic derivation execution are classified for deletion rather than preserved as requirements;
- no new compatibility API is introduced;
- the current persistent semantic fields are classified as `keep`, `derive from git-annex/Git`, or `delete`;
- the public `Repository`, `Engine`, source, dataset, manifest, declarative-project, and lock contracts have an explicit migration destination.

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
