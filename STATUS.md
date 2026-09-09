# STATUS.md

Purpose: compact handoff record of current state, active focus, verified evidence, and immediate gaps.

## Current focus

Migrate canonical planner/executor/adapters/derived work onto the clean public source/repository/result contracts, then delete all alpha compatibility and historical schema support. `docs/compatibility-inventory.md` is a deletion inventory, not a support matrix.

## Recently completed

- The clean package-root API is implemented: one explicit `Repository` type with `create`/`open` and read/write modes, `Engine`, typed built-in sources, `SyncRequest`/`SyncResult`, `DatasetSpec`/`Dataset`/`DatasetManifest`, and public error categories.
- Ordinary repository reads are grouped under artifact/source/run/dataset/provenance/maintenance facades; low-level repository writer, `RepositoryView`, `ReadOnlyRepository`, selector/materializer, storage, registry, and executor records are no longer package-root exports.
- Public temporal selection uses timezone-aware `datetime`; unbounded snapshot history uses `limit=None`; dataset resolve/freeze/export and detached manifest verification are exposed through the new facade.
- README and installed-wheel packaging examples use only the clean API, with an end-to-end regression covering acquire → freeze → export → detached verify → read-only reopen.

## Pre-cutover baseline

- 186 tests passed on Python 3.12.12, 3.13.9, and 3.14.0 before the clean API work.
- Ruff lint/format, ty, whitespace, and all 7 import contracts passed.
- Coverage was 86.16% lines / 62.80% branches.
- Failure injection covered interrupted writes, retry/recovery, concurrent processes, and export publication races.

## Remaining gaps

- Canonical internals still bridge clean sources onto `SourceDefinition`/`SourceKind` and the legacy `EngineConfig`; adapter dispatch/context and writer/read capabilities must migrate under TODO 1.
- Compatibility/projection/presentation modules, adoption/aliases, TTL caches, and historical schema migrations remain until TODO 2 deletion.
- Full durability, detached export, Linux publication, final quality gates, remote CI, and BVP acceptance must be repeated after internal migration and compatibility deletion.

## Resume point

Start with TODO 1: replace the temporary source/config bridge and broad internal repository capabilities with the clean canonical contracts, then execute the finite compatibility deletion in TODO 2.
