## Overview

This process is split into three layers

| Level                         | Primary axis      | Question it answers                                                            |
| ----------------------------- | ----------------- | ------------------------------------------------------------------------------ |
| **L1 — Lifecycle**            | *When*            | “At this stage of the project, what classes of testing must exist?”            |
| **L2 — Phase-scoped**         | *Why / readiness* | “Given this phase, what does ‘adequate testing’ mean and how do we assess it?” |
| **L3 — Test-type procedures** | *How*             | “How do we design, write, review, and judge this kind of test?”                |


### Control-flow model

```
Lifecycle Procedure (L1)
 ├─ calls → Phase Procedure (L2)
 │    ├─ calls → Test-Type Procedures (L3)
 │    └─ returns → Phase compliance result
 └─ continues → next lifecycle decision
```

Each level should:

* **Own decisions appropriate to its scope**
* **Delegate execution detail downward**
* **Consume only summarized outcomes upward**

### Recording decisions and risk acceptance

When any conditional requirement is omitted, or any test class is waived, record:

* the risk and failure mode being accepted,
* rationale and mitigations,
* owner,
* revisit trigger (phase promotion, release, incident, scale threshold).

## Levels
## Level L1: Project lifecycle procedure

**Purpose**: define **when** different categories of testing are expected and how they evolve over time

### Responsibilities

* Declare **required test classes per phase**
* Declare **gating vs advisory** tests
* Select which **L2 phase procedure(s)** apply

#### Output

* A checklist of required L2 procedures to run
* A release or progression decision

##  Level L2: Phase-scoped procedures

**Purpose**: define what *adequate testing* means **for a given phase**, independent of test mechanics.

### Responsibilities

- define phase intent
  * Primary risks at this phase
  * What failures are unacceptable
  * What uncertainty is still tolerated

- declare test classes
- define compliance criteria
  * qualitative
  * quantitative
  * explicitly not required
- describe assessment process
  * How to evaluate whether the phase is satisfied
  * What evidence is acceptable (reports, markers, CI results)
- delegate to level L3 procedures

#### Output

* Pass / conditional pass / fail
* Actionable remediation items

## Level L3: Test-type procedures (leaf nodes)

**Purpose**: Describe concrete actions to perform

### Responsibilities
#### How to design this test

* When it is appropriate
* What it should and should not assert
* Boundary rules (I/O, mocks, determinism)
* Common patterns (AAA, property invariants, contracts)

#### How to evaluate an individual test

* Does it test behavior or implementation?
* Is it isolated and deterministic?
* Is it readable and minimal?
* Would a small refactor break it unnecessarily?

#### How to evaluate the suite as a whole

* Coverage of responsibilities and invariants
* Redundancy and overlap
* Signal-to-noise ratio
* Flakiness and runtime budget
* Maintenance cost vs confidence

### Cross-cutting: scope adjustment is expected

Tests are not “born” at the correct scope in all cases. It is acceptable—and expected—to move tests between scopes over time to optimize:

* failure localization,
* runtime budgets,
* flake reduction,
* confidence per test.

