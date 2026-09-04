# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Record collection and derived outputs as repository artifacts

Files: `src/efloud/fanout.py`, `src/efloud/derived.py`, `src/efloud/repository_recording.py`, tests

- import successful `REST_BASE` / fanout item outputs as logical artifact observations
- preserve per-item request metadata and materialization paths
- represent deterministic derived outputs with input observation provenance instead of treating them as opaque manifest payloads
- record failed/missing collection items without inventing content observations

Acceptance: a fanout/derived run can be reopened from `metadata.sqlite` and its item artifacts, content, producer operation, inputs, and source snapshot can be inspected without reading a sync manifest.

## 2. Generate compatibility manifests and state from repository records

Files: `src/efloud/manifest.py`, `src/efloud/state.py`, `src/efloud/repository_compat.py`, `src/efloud/query.py`, `src/efloud/status.py`, tests

- derive HTTP/REST, reconciled rsync, and collection/derived compatibility facts from repository metadata
- preserve required legacy payload shapes while making SQLite/blob state authoritative
- generate mirror/tree integrity facts from recorded source snapshots rather than rescanning mirrors where equivalent repository data exists
- retain read fallback only for repositories that predate repository metadata

Acceptance: representative compatibility manifests/status/query payloads can be regenerated after deleting canonical manifest and mirror-state files.

## 3. Remove remaining read-side manifest/mirror authority

Files: source-result, resolve, health, store-inspection, summary, and compatibility modules; tests

- route current-state reads through repository APIs whenever repository metadata exists
- identify and delete duplicate source-result/state logic made obsolete by repository projections
- keep legacy-file import/migration explicit rather than silently mixing two sources of truth

Acceptance: no normal read path for an initialized repository requires canonical JSON manifests or `.mirror_meta.json` for authoritative artifact/source state.

## 4. Run and repair the full repository quality gate

Files: repository-wide as required

- run formatting/lint, static typing, import contracts, focused repository tests, and full pytest suite
- repair any issues introduced during the repository migration
- verify SQLite v1→v2 migration and compatibility fallback fixtures

Acceptance: the normal project quality gate passes from a clean checkout.