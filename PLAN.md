# PLAN.md

Purpose: define the execution strategy for the experimental Git/git-annex redesign. `docs/adr/0011-delegate-generic-infrastructure.md` records the decision under test; `docs/git-annex-redesign-gap-audit.md` is the finite migration audit; `TODO.md` holds immediate tasks.

## Strategy

Treat this branch as a clean pre-1.0 experiment. Preserve semantic behavior, not legacy implementation. Replace one infrastructure boundary at a time, prove the replacement with characterization/integration tests, then delete the superseded production code. Do not add compatibility shims, parallel configuration systems, or speculative generic abstractions.

The public package boundary remains small: `Repository`, `Engine`, sources, sync request/result, dataset spec/dataset/manifest, public errors, and version. Internal catalog/content/tree implementations are not downstream API.

## Milestone A — Characterize semantics and classify legacy infrastructure

Use the gap audit to map every current test and persistent field to a retained semantic requirement or a replaceable implementation detail.

Add missing characterization coverage for unchanged/changed observations, coverage-backed absence, partial inventory, interrupted acquisition, validation history, exact/latest/latest-before resolution, multi-source composition, deterministic/path-independent dataset identity, and frozen evidence stability.

Exit: all retained semantics are storage-backend-independent tests and every legacy subsystem has a migration owner.

## Milestone B — Introduce narrow infrastructure ports

Introduce only the ports required by the target model: semantic `Catalog`, annex-oriented `ContentStore`, Git-oriented `TreeStore`, source-semantic `SourceAdapter`, and semantic `Validator`.

Refactor orchestration and dataset logic to depend on those ports. Keep the current backend only as temporary scaffolding until the git-annex slice passes.

Exit: domain/resolution code does not depend directly on the filesystem CAS or custom tree implementation; source adapters do not own durable byte placement.

## Milestone C — Prove Git/git-annex infrastructure

Implement centralized Git/git-annex command execution, repository initialization, cryptographic content-only key policy, ingest, presence, verification, URL registration/acquisition, get/drop, key inspection, and Git tree/commit operations.

Use real temporary repositories for integration tests and machine-readable output where available. Test retries/interruption, unusual filenames, duplicate bytes, content corruption, drop/reacquire, and dirty worktree recovery.

Exit: git-annex satisfies the content-custody contract and Git satisfies the filesystem-tree contract without leaking object paths or commit identity into semantic identity.

## Milestone D — Cut content identity and repository persistence over **(substantially complete)**

Redefine `ContentRef` to carry semantic content identity plus an opaque annex custody key. The custody key is persisted as infrastructure evidence, never as a filesystem path or dataset identity. Route Repository byte ingest/open/presence/verification through `ContentStore`, and route durable semantic records through `Catalog`.

Implementation sequence:
1. establish the semantic `ContentRef` ↔ annex-key mapping using git-annex `examinekey`;
2. cut Repository ingest, standalone content staging, reopen, open, presence, and verification over to git-annex;
3. cut read-only access over to the same annex custody boundary;
4. add real repository integration coverage for deduplication, reopen, custody-key persistence, and integrity verification;
5. remove remaining production assumptions that `content_objects.storage_key` is a filesystem locator;
6. delete or rewrite tests that assert the removed filesystem CAS contract; replace them with semantic custody assertions;
7. redesign repository maintenance around git-annex custody rather than scanning `objects/sha256` paths; **complete**.
8. cut Repository semantic persistence over the narrow Catalog port; isolate materialization/custom-tree state behind a temporary legacy capability; **complete**.

The cutover must preserve the transaction ordering: annex custody must be established before semantic catalog records can reference the content. A failed catalog write may leave unreferenced annex content, but must never create an authoritative reference to unavailable content.

Exit: all new observations and repository content operations use annex-backed content refs; no production semantic query requires a custom CAS path; detached dataset identity remains independent of the annex key; maintenance audits and cleans through git-annex custody; semantic Repository persistence depends only on Catalog.

## Milestone E — Delete replaced transfer/tree/derivation machinery

For each source, classify acquisition as native git-annex, special remote, or adapter-assisted temporary retrieval. Retain source-specific discovery/authentication semantics and delete generic retry/copy/cache/transport code that git-annex replaces.

Replace custom tree identity with Git projections. Remove generic derivation DAG/execution from core; keep only transformations necessary to acquire, interpret, validate, normalize, or expose source data.

Exit: production has one content backend (git-annex), one filesystem-tree identity mechanism (Git), and no general workflow executor.

## Milestone F — Strengthen observation, validation, dataset, and lock semantics

Formalize inventory scope/coverage and explicit absence. Version validation evidence independently of byte integrity. Rebuild dataset resolution and canonical manifests around path-independent semantic membership. Adapt existing `efloud.toml`/lock machinery to record exact annex/Git/source/dataset evidence without making paths or Git commits semantic dataset identity.

Exit: exact/latest/latest-before resolution is deterministic across machines and every dataset member has an explanation chain to observation/coverage/validation evidence.

## Milestone G — Materialized views and external-tool handoff

Separate layout specifications from dataset identity. Materialize annexed content through one simple default layout first. Add optional DataLad integration only after plain Git/git-annex behavior is complete.

Define the deterministic DVC handoff through `efloud.lock`; do not import DVC in core. Define explicit promotion provenance for generated outputs that become canonical Efloud data.

Exit: the same semantic dataset can have multiple layouts/distribution mechanisms, and downstream workflow tools consume a small deterministic lock boundary.

## Milestone H — Migration, deletion, and acceptance

Provide a one-shot, restartable migration for repositories that must be preserved. Migration code may read old state but must not keep old schemas/APIs alive in normal runtime behavior.

Delete the legacy CAS, custom tree hashing/state, generic transfer scheduler/cache, redundant materialization state, and generic derivation executor. Update DESIGN/API/storage/dataset/interoperability documentation only once the experiment has demonstrated the target contracts.

Exit: the definition of done in ADR-0011 and the gap audit is satisfied; applicable `just check`, type checking, architecture contracts, full tests/coverage, supported Python minors, and platform acceptance pass on the exact final commit.

## Verification policy

Do not claim a milestone complete from mocked command tests alone when it depends on Git/git-annex behavior. Real OS/filesystem and temporary-repository integration tests are required where practical. DataLad and DVC remain absent from core test dependencies unless testing their optional/external interoperability boundaries.
