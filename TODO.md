# TODO.md

File Purpose: Short-horizon, detailed task list for immediate development work.

Rules:

- This is execution-level and ephemeral.
- Remove completed items before committing.
- Prefer concrete references and explicit acceptance criteria.

## 1. Complete Phase 13 immutable-dataset and temporal-policy work

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

## 2. Keep continuous integration authoritative

Files: `.github/workflows/ci.yml`, `justfile`, project test configuration as required

- keep the Python 3.14 CI job behaviorally aligned with the normal local
  syntax/format/lint/typecheck/test sequence
- keep the complete pytest suite running on Python 3.12 and 3.13 while those versions
  remain in `project.requires-python`
- preserve locked dependency resolution and read-only workflow permissions
- treat new CI failures as repository regressions rather than bypassing checks in the
  workflow

Acceptance: every push to `main` and pull request receives green CI only after the
full Python 3.14 development gate and complete tests across Python 3.12-3.14 succeed.
