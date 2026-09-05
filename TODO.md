# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Rerun the repaired Phase 6-7 quality gate

Files: repository-wide as required

- run `.venv/bin/ruff format src/ tests/`
- run `.venv/bin/ruff check src/ tests/`
- run `.venv/bin/ty check src/ tests/`
- run focused inventory/reconciliation, fanout/collection, repository-derived, and rsync tests
- run `.venv/bin/pytest`
- verify public inventory/fanout imports and existing HTTP, REST, collection/fanout, and rsync behavior

Acceptance: the normal project quality gate passes from a clean checkout without regressions in existing acquisition or repository behavior.

## 2. Add stable producer identity and lifecycle semantics

Files: repository models/store/schema/facade, derived/acquisition recording, tests

- add a namespaced `ProducerRef` carrying stable producer identity and version
- attach producer identity/version to repository operations
- replace free-form run/operation status mutation with explicit lifecycle states
- reject invalid lifecycle transitions while preserving existing persisted records
- keep dry-run/planned work out of persisted execution history unless execution begins

Acceptance: every persisted operation identifies its producer/version and invalid run/operation lifecycle transitions are rejected deterministically.

## 3. Add deterministic derivation identity and reuse

Files: `src/efloud/derived.py`, repository metadata/query modules, indexing modules, tests

- define `DerivedTaskSpec` and canonical `DerivationKey`
- include task identity/version, normalized parameters, declared outputs, and normalized inputs
- support content-sensitive and observation-sensitive dependency semantics
- reuse prior deterministic output content when the derivation key matches
- still record a new current-run output observation and provenance when content is reused

Acceptance: deterministic content-based derivations can reuse prior byte-identical outputs without losing current-run provenance, while observation-sensitive derivations distinguish independent observations of identical bytes.

## 4. Migrate persistent semantic indexes onto derivation semantics

Files: `src/efloud/indexing.py`, repository metadata/query modules, tests

- represent persistent semantic index outputs as specialized derived artifacts
- replace TTL validity with derivation-key validity where index generation is deterministic
- retain TTL only for source refresh/acquisition concerns
- preserve compatibility APIs while repository-backed derivation state becomes authoritative

Acceptance: deterministic index freshness/reuse can be decided from producer/version, parameters, and inputs without wall-clock TTL.
