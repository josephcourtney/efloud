# ADR-0009: Frozen snapshot membership, detached exports, and local maintenance

Status: Accepted

## Decision

Snapshot-backed datasets require complete coverage, exact content-bearing
observations, and an unambiguous observation binding in snapshot evidence.
Repository observation time is the temporal basis. Unknown source-definition
revisions cannot satisfy role/tag requirements. Snapshot encodings that do not
establish exact membership are not accepted by the clean-break runtime.

Detached manifest v1 carries the specification, exact membership, semantic
content metadata, source revision and snapshot evidence, constraint results, and
explicit relative export paths. Import checks identities and repository evidence;
detached verification checks exported bytes without SQLite. It never reacquires.

Exports are assembled in a sibling temporary directory and published only after
verification. Existing destinations and unsafe or colliding paths are rejected.
Copy and CoW exports are independent of repository content. Explicit symlink
exports point to private exported content, never writable authoritative CAS paths.

Writable local repositories hold a nonblocking OS advisory lock for their entire
lifetime, including schema initialization, validation staging, and acquisition.
Read-only repository mode does not take a writer lock. Maintenance uses the same
exclusive lease. Crashes release the lease automatically. Recovery marks abandoned
running operations/runs failed; retries use a new run and canonical Engine
orchestration, never replay unknown transport side effects or claim an incomplete
snapshot is complete.

Safe cleanup preserves every historical metadata reference, including tree,
validation and materialization references. It defaults to a dry run and requires
an explicit time and grace period. Historical pruning is outside this decision.

## Consequences

Only one writable repository instance per local root is supported at a time.
Consumers should use read-only repository mode. Detached manifests are integrity
records, not signatures or proof of authenticity.

ADR-0010 supersedes the earlier compatibility consequence of this decision:
historical alpha repository schema upgrades and compatibility APIs are no longer
retained as supported runtime behavior.
