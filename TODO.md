# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Run and repair the Phase 8 quality gate

Files: repository-wide as required

- run `.venv/bin/ruff format src/ tests/`
- run `.venv/bin/ruff check src/ tests/`
- run `.venv/bin/ty check src/ tests/`
- run focused provenance/lifecycle/derivation/index tests
- run existing repository/status/manifest/engine compatibility tests
- run `.venv/bin/pytest`
- verify public imports for `ProducerRef`, `DerivedTaskSpec`, derivation APIs, and derived indexes

Acceptance: the normal project quality gate passes from a clean checkout without regressions in existing acquisition, manifest/status compatibility, or repository behavior.

## 2. Redefine the generic blob-store semantic contract

Files: `src/efloud/blob_store.py`, repository/content models, tests

- retain semantic operations for put/open/contains/verify/delete
- keep path/stream ingestion as convenience rather than identity
- remove assumptions that generic callers can resolve a local storage path
- move filesystem-only path access behind `FilesystemBlobStore` or an explicit optional capability
- preserve idempotent puts and content-addressed identity

Acceptance: a fake non-path-backed blob store can satisfy repository ingestion/open/verify behavior without exposing filesystem paths.

## 3. Remove `storage_key` from repository-facing semantics where possible

Files: content/reference models, metadata store/schema/facade/query/dataset code, tests

- separate semantic `ContentRef` fields from backend-specific storage location
- keep backend location private to the blob-store implementation or storage metadata
- ensure repository/query/dataset code opens content only through `BlobStore`
- preserve compatibility for existing SQLite stores during migration

Acceptance: relocating the filesystem CAS or replacing it with a non-path backend does not change content/artifact/observation/dataset identity or require repository-facing path logic.

## 4. Characterize interrupted-ingestion/orphan behavior

Files: blob-store/repository failure tests and documentation

- document that blob puts are idempotent
- test metadata failure after successful blob write
- verify this can leave an orphan blob but never a committed reference to missing content
- preserve orphan cleanup for the later GC phase rather than coupling it to transaction rollback

Acceptance: interrupted metadata commits may leave safe unreachable blobs, but repository records never reference unavailable content.
