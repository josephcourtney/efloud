---
aliases:
  - L2-P1
linter-yaml-title-alias: L2-P1
tags:
title: L2-P1
---

# L2-P1 — Exploratory / Prototype Testing Phase
## Procedure L2-P1: Exploratory / Prototype Testing Phase


## 1. Phase intent

**Goal:**
Reduce uncertainty and validate feasibility with minimal friction.

**Primary risks addressed:**
Building the wrong thing; misunderstanding domain constraints.

**Deferred risks:**
Long-term correctness, regression protection, non-functional properties.

(Definitions and test taxonomy per *automated_testing.md*.)

---

## 2. Applicability

Applies when:

* exploring new ideas or architectures,
* validating assumptions,
* building throwaway or experimental code.

---

## 3. Required test classes

### Mandatory

* None.

### Advisory

* **Unit tests** for critical logic or surprising behavior.
* **Property-based tests** for core invariants or transformations.
* **Spike or exploratory tests** used as executable experiments.

### Conditional decision rule (risk acceptance)

If advisory tests are omitted for a critical assumption, the omission must be recorded as a risk with:

* description of the assumption,
* intended validation method (test, measurement, manual check),
* owner,
* revisit trigger (typically promotion to L2-P2).

---

## 4. Explicit non-requirements

Not required:

* Coverage targets
* Component, integration, or system tests
* Regression guarantees
* CI enforcement

---

## 5. Compliance criteria

This phase is compliant if:

1. Key assumptions are explicitly tested or otherwise validated.
2. Tests (if written) are clearly marked as experimental.
3. No prototype artifacts are misrepresented as production-ready.

---

## 6. Assessment

1. Identify assumptions and unknowns.
2. Verify that major risks have been explored.
3. Record outcomes and learning.

---

## 7. Forward rules

* Tests may be discarded or promoted in later phases.
* Any prototype code promoted forward must be re-evaluated under L2-P2.

---

## 8. Delegation

Optional:

* **L3-T1:** Unit Test (Pure Logic)
* **L3-T6:** Property-Based Testing

If either of the above is chosen, apply the corresponding L3 procedure in full and record deviations.

---

## 9. Exit

Return findings (not pass/fail) to L1.

