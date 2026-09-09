# Durability audit after compatibility removal

This audit enumerates the authoritative mutation surface that remains after the clean-break compatibility deletion. Non-authoritative transport staging and detached export files are excluded.

| Mutation path | Coordination / crash boundary | Required invariant | Acceptance evidence |
| --- | --- | --- | --- |
| Repository create/open for write | `WriterLease` is acquired before writable metadata/blob stores are exposed | At most one authoritative writer or destructive maintenance process owns a repository | public writer-contention and cross-process crash-release tests |
| Source registration | SQLite transaction under active writer lease | definition revision history is append-only and new evidence pins the active revision | source-definition revision tests |
| Run lifecycle | SQLite lifecycle rows under writer lease | terminal runs cannot regain running state; runs cannot finish with running operations | lifecycle transition tests |
| Operation lifecycle | SQLite lifecycle rows under writer lease | producer identity is explicit; terminal state is one-way; recovery only converts abandoned running work to failed | producer/lifecycle and recovery tests |
| Content staging | blob write precedes metadata registration | interruption may leave an orphan blob, never metadata pointing at bytes that were never written | injected metadata-failure and closed-writer tests |
| Observation/provenance ingestion | one metadata transaction records content, observation, and provenance after blob staging | no partial observation/provenance bundle is published | observation-bundle failure and provenance-history tests |
| Absence recording | single metadata transaction under writer lease | absence is published only with explicit source evidence and cannot conflict with its locator/path | absence-evidence tests |
| Validation evidence | single validation record after immutable content exists | validation-only content remains reachable; validation failure does not mutate content | validation reuse/integrity and cleanup reachability tests |
| Tree/source snapshots | tree content is recorded before snapshot publication; source snapshot is atomic | a crash can leave conservative unreferenced tree metadata but cannot invent a complete source snapshot | interrupted-snapshot recovery test |
| Deterministic derived outputs/indexes | exact input observations plus derivation identity under the same writer | reuse preserves bytes but creates fresh observation/provenance evidence | derivation/index reuse tests |
| Dataset freeze | dataset membership/specification rows commit transactionally under the writer lease | immutable membership is either recorded completely or not advanced | dataset identity/reopen and public freeze tests |
| Cleanup | exclusive writer lease even for dry-run planning; complete reachability recomputation; semantic and reachable-content audit before deletion | destructive cleanup refuses invalid metadata/reachable corruption and deletes metadata before blobs | fail-closed cleanup, grace-boundary, validation-only, provenance, and writer coordination tests |
| Recovery | exclusive writer lease; only `running` lifecycle records are changed | recovery never creates successful operations or complete snapshots; retry occurs in a new run | interrupted-write/snapshot and process-crash retry tests |

## Findings closed by this pass

- `store_bytes_content()` now checks the active writer lease before touching the blob store.
- Missing operation producer metadata is rejected instead of receiving a synthetic legacy producer.
- Destructive cleanup now fails closed on SQLite/FK errors, semantic identity/source/snapshot corruption, and missing or corrupt reachable content.
- Unbounded source snapshot history uses `None` through the internal repository/storage contracts rather than translating back to `-1`.
- Grace-period boundary, dry-run selection-reason, semantic-corruption, reachable-corruption, and provenance-preservation cases are explicit regressions.

## Accepted conservative behavior

`record_tree_snapshot()` can leave an unreferenced tree if the process fails after tree recording but before snapshot publication. Tree-entry content remains conservatively reachable. This leaks metadata/storage rather than inventing history or deleting referenced content, so it is safe; future tree garbage collection may reclaim it only with an independently proven reachability rule.

Explicit `reflink` export remains strict: it may raise `OSError` when the host filesystem does not support native CoW. The integration test skips only that strategy on unsupported filesystems rather than silently treating `reflink` as `copy`; exercising a supported native Linux CoW filesystem remains part of the dataset/export acceptance milestone.
