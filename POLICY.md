# Project Documentation and History Policy

This document defines the purpose, intended contents, and usage policies for the primary project documents and for git commit messages. The goal is to ensure clarity of intent, prevent scope overlap, minimize document drift, and maintain a coherent, auditable development history in a git-only workflow.

---

## 1. DESIGN.md

### Purpose
DESIGN.md is the canonical, durable record of the project’s intent and architecture. It defines *what the system is* and *what properties it must preserve*.

### Contents
DESIGN.md SHOULD contain:
- High-level project goals and non-goals
- Core architectural structure and decomposition
- Key abstractions and their responsibilities
- Invariants and correctness constraints
- External and internal requirements (functional and non-functional)
- Policies (e.g., security, compatibility, data ownership, error handling)
- Stable architectural decisions, referenced by ADRs where applicable

DESIGN.md SHOULD NOT contain:
- Step-by-step implementation plans
- Task lists or sequencing details
- Temporary workarounds or exploratory notes
- Low-level implementation details that change frequently

### Usage Policy
- DESIGN.md is updated only when the intended architecture, invariants, or requirements change.
- Changes to DESIGN.md are infrequent and deliberate.
- Rationale for significant architectural decisions belongs in ADRs and is referenced, not duplicated.
- DESIGN.md describes the *current* intended design, not its historical evolution.

---

## 2. PLAN.md

### Purpose
PLAN.md defines how the design in DESIGN.md will be realized. It records execution strategy, ordering, and non-obvious implementation considerations.

### Contents
PLAN.md SHOULD contain:
- High-level implementation phases or milestones
- Ordering constraints and dependencies
- Migration strategies and transitional states
- Non-obvious implementation considerations
- Temporary or contingent decisions made for execution purposes
- References to relevant DESIGN sections and ADRs

PLAN.md SHOULD NOT contain:
- Detailed per-function or per-file task breakdowns
- Progress tracking or status reporting
- Long-term architectural rationale (belongs in DESIGN/ADRs)

### Usage Policy
- PLAN.md may evolve as implementation proceeds.
- It is acceptable for parts of PLAN.md to become obsolete once executed; completed sections may be marked as such or pruned.
- PLAN.md explains *how* and *in what order* work is intended to proceed, not whether it has already been completed.

---

## 3. STATUS.md

### Purpose
STATUS.md captures the current state of the project for continuity and handoff. It answers: “Where are we now, and what matters next?”

### Contents
STATUS.md SHOULD contain:
- Current focus or active area of work
- Summary of recently completed plan elements
- Known gaps, limitations, or incomplete areas
- Identified problems, risks, or blockers
- Notes helpful for resuming work (e.g., partial implementations, placeholders, pending decisions)

STATUS.md SHOULD NOT contain:
- Detailed task lists (belongs in TODO.md)
- Long-term plans or architectural descriptions
- Historical narratives once they are no longer relevant

### Usage Policy
- STATUS.md is short-horizon and pragmatic.
- It is updated as work progresses and pruned to remain high-signal.
- It may reference sections of PLAN.md or ADRs rather than restating them.
- STATUS.md is not an archive; obsolete information should be removed.

---

## 4. TODO.md

### Purpose
TODO.md is an ephemeral, execution-level task list used to drive immediate development work.

### Contents
TODO.md SHOULD contain:
- Highly detailed, concrete tasks to be performed
- Short-horizon work items (what will be done next)
- Where useful, explicit references to files, classes, methods, tests, or tools
- Acceptance criteria or notes on required tests/verification

TODO.md SHOULD NOT contain:
- Completed tasks
- Long-term plans or speculative ideas
- Architectural rationale
- Historical records

### Usage Policy
- TODO.md is inherently temporary.
- Completed items are removed before committing.
- TODO.md may be rewritten freely as understanding evolves.
- The absence of an item from TODO.md does not imply it was never done; completed work is reflected in commits and the changelog.

---

## 5. CHANGELOG.md

### Purpose
CHANGELOG.md records notable changes to the project for users and downstream consumers, following keep-a-changelog conventions.

### Contents
CHANGELOG.md SHOULD contain:
- User-visible additions, changes, fixes, deprecations, and removals
- Notable internal changes that affect behavior, performance, or compatibility
- Breaking changes and migration notes

CHANGELOG.md SHOULD NOT contain:
- Task-level detail
- Implementation minutiae
- Exploratory or abandoned work
- Development process notes

### Usage Policy
- Entries are added as work is completed.
- The changelog is curated and narrative, not exhaustive.
- CHANGELOG.md is not a substitute for commit history.

---

## 6. Architecture Decision Records (ADRs)

### Purpose
ADRs capture the rationale behind significant, durable design and architectural decisions.

### Contents
Each ADR SHOULD contain:
- Title, date, and status (e.g., Proposed, Accepted, Superseded)
- Context and problem statement
- Decision
- Consequences (positive and negative)
- Alternatives considered (briefly)

### Usage Policy
- ADRs are written for decisions that are costly to reverse or likely to be questioned.
- DESIGN.md references ADRs for “why”; ADRs do not restate the entire design.
- Superseded decisions are marked explicitly and linked forward.
- ADRs are stored in a dedicated directory (e.g., `docs/adr/`) and are numbered for stable reference.

---

## 7. Git Commit Messages

### Purpose
Commit messages, together with diffs, form the authoritative, fine-grained technical history of the project.

### Contents
Each commit message SHOULD include:
- A concise, imperative subject line describing the change
- A body (when non-trivial) explaining:
  - rationale and intent
  - notable tradeoffs or constraints
  - behavioral changes or edge cases
  - tests added or modified
  - references to DESIGN sections, ADRs, or PLAN items as applicable

### Usage Policy
- Commits should be logically scoped and self-contained.
- Commit messages are the primary location for detailed implementation history.
- Stable identifiers (e.g., `ADR-003`, `INV-4`, `PLAN-2.1`) SHOULD be used to enable traceability via git alone.
- Commits document *what changed and why*, not project status or task tracking.

---

## Summary of Responsibilities

- DESIGN.md: intent, architecture, invariants
- PLAN.md: execution strategy and ordering
- STATUS.md: current state and continuity
- TODO.md: immediate, detailed tasks (temporary)
- CHANGELOG.md: curated, user-facing change history
- ADRs: durable decision rationale
- Git commits: detailed technical evolution and traceability

Each artifact has a distinct role; overlap should be avoided in favor of explicit references.
