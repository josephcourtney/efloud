# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Verify Phase 12 validation-as-evidence implementation

Files: repository-wide as required

- run `just syntax; just format; just lint; just typecheck; just test`
- verify `tests/unit/test_phase12_validation.py` remains green
- verify existing repository ingestion/orphan-failure tests still preserve atomic
  content-metadata/observation behavior
- verify existing Engine, query, collection/fanout, rsync reconciliation, Phase 10,
  and Phase 11 regression coverage remains green
- verify configured HTTP/REST `IntegrityExpectation` values are enforced even when a
  custom adapter omits them from its acquisition result
- verify required failed validation creates no successful source observation or
  source snapshot while retaining immutable content and validation evidence
- verify unchanged content plus an unchanged validator identity/version reuses prior
  validation evidence
- verify domain validators can be injected through `ValidationRegistry` without
  efloud importing domain packages
- verify `content:<content-id>` and observation queries expose repository-backed
  validation evidence
- verify no new unjustified lint/type suppressions were introduced

Acceptance: syntax, formatting, lint, typecheck, and the full test suite pass from a
clean checkout. Required integrity failures prevent source advancement, validation
failures do not mutate stored bytes, validation evidence is reusable by content plus
validator identity/version, and domain validators remain extension-provided.

## 2. Begin Phase 13 immutable-dataset and temporal-policy completion

Files: `src/efloud/datasets.py`, repository/query surfaces, focused dataset tests, and
BVP parity fixtures where available

- inventory the existing exact/latest/latest-before/latest-all dataset foundation
  before adding new abstractions
- add selection by source/tag/role/namespace only where the repository can determine
  those selectors from authoritative metadata
- define an explicit temporal time basis rather than relying on an implicit timestamp
  interpretation
- add required-complete-source-snapshot constraints without inferring absence from
  incomplete coverage
- add optional maximum-observation-skew and same-run constraints where requested
- keep frozen exact observation membership immutable after newer ingestion
- produce deterministic dataset export metadata independent of repository root or
  local blob paths
- establish the BVP catalog/verification parity gate using generic efloud dataset
  semantics rather than domain-specific repository logic

Acceptance: frozen datasets remain unchanged after subsequent ingestion, temporal
resolution never infers absence from incomplete coverage, local root/blob placement
does not affect dataset identity, requested temporal/coherence constraints are
explicit and testable, and downstream BVP catalog behavior can be represented through
generic efloud APIs.
