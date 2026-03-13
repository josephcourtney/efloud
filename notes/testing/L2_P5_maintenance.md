---
aliases:
  - L2-P5
linter-yaml-title-alias: L2-P5
tags:
title: L2-P5
---

# L2-P5 — Maintenance and Change Testing Phase

## 1. Phase intent

**Goal:**
Safely evolve a live system while preventing regressions.

**Primary risks addressed:**
Silent breakage, cumulative technical debt, erosion of test quality.

---

## 2. Applicability

Applies when:

* fixing bugs in production code,
* making incremental improvements,
* upgrading dependencies or infrastructure.

---

## 3. Required test classes

### Mandatory

* **Regression tests** for all non-trivial bug fixes.
* **Unit/component tests** for changed logic.
* **Smoke tests** to ensure core functionality remains intact.

### Conditional

* **Integration tests** if boundaries are affected.
* **Contract tests** if interfaces change.

### Conditional decision rule (risk acceptance)

If integration/contract coverage is omitted despite boundary/interface impact, record:

* the impacted boundary/interface,
* why omission is acceptable (e.g., canary rollout, feature flag, monitoring),
* owner,
* time-bounded remediation plan.

---

## 4. Explicit non-requirements

Not required by default:

* Full re-validation of unchanged functionality.
* Broad exploratory testing unrelated to the change.

---

## 5. Compliance criteria

The phase is compliant if:

1. Each change has tests that would fail without it.
2. Existing tests remain stable and meaningful.
3. No new flakiness or undue slowdown is introduced.

---

## 6. Assessment

1. Identify scope and impact of change.
2. Verify targeted regression coverage.
3. Apply L3 procedures for each mandatory test class and record deviations.
4. Review suite health before and after change via **L3-T10**.
5. Record outcome.

---

## 7. Forward rules

* Regression tests accumulate as long-term assets.
* Test debt or brittleness must be addressed incrementally.

---

## 8. Delegation

Invoke as needed:

* **L3-T1:** Unit Test
* **L3-T2:** Component Test
* **L3-T5:** Regression / Sanity Test
* **L3-T4:** Smoke Test
* **L3-T10:** Health and Metrics

---

## 9. Exit

Return assessment result to L1.
