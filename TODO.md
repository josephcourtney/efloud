# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Land repository-native query and public read APIs

Files: `src/efloud/repository_query.py`, `src/efloud/__init__.py`, query-focused tests

- expose artifact, observation, source-snapshot/tree, and dataset reads without consulting sync manifests
- support locator evaluation directly against immutable blob content
- export `Repository`, `Engine`, dataset selectors/types, repository identities, and the repository query service from the package API
- keep legacy `query_target()` behavior intact during this cutover

Acceptance: focused tests cover present/absent artifact state, exact observation lookup, snapshot/tree lookup, dataset membership, and blob-backed locator evaluation.

## 2. Move source/run/status inspection onto repository metadata

Files: `src/efloud/metadata_store.py`, `src/efloud/sqlite_metadata.py`, repository query/status modules, tests

- add read methods for sources, runs, operations, source snapshots, and materializations needed by status/reporting
- make new source/run/status payloads derive from SQLite repository state
- retain compatibility manifest/status functions until parity is demonstrated

Acceptance: representative source and run status can be produced after reopening the repository with no manifest or mirror-state read.

## 3. Implement authoritative rsync reconciliation

Files: `src/efloud/transport/rsync.py`, repository ingestion/reconciliation modules, tests

- obtain an explicit enumeration for the covered rsync scope
- reconcile that enumeration against prior repository state
- emit content observations for changed/new files and absence observations only when coverage proves deletion
- create complete snapshots for fully enumerated scopes and scoped incomplete snapshots otherwise
- avoid unconditional full-tree rehashing of unchanged files

Acceptance: tests cover addition, modification, unchanged content, deletion, partial-scope sync, failed/incomplete enumeration, and repeated sync deduplication.

## 4. Switch compatibility outputs to repository-derived views

Files: manifest/state/query/status compatibility modules and tests

- generate canonical manifest/state facts from repository records where equivalent data exists
- verify parity against current compatibility fixtures
- remove any remaining read-side assumption that mirrors or JSON manifests are authoritative

Acceptance: repository state is sufficient to reproduce required compatibility outputs for HTTP/REST and reconciled rsync fixtures.
