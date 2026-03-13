---
aliases:
  - L2-P3
linter-yaml-title-alias: L2-P3
tags:
title: L2-P3
---

# L2-P3 — Stabilization and Pre-Release Testing Phase

## 1. Phase intent

**Goal:**
Stabilize behavior, validate integrations, and reduce release risk.

**Primary risks addressed:**
Integration failures, regressions, contract drift.

**Deferred risks:**
Long-term performance optimization, rare failure modes.

---

## 2. Applicability

Applies when:

* feature set is largely complete,
* preparing for beta or release,
* APIs and data models are stabilizing.

This phase assumes interfaces are stable enough to be treated as commitments.

---

## 3. Required test classes

### Mandatory

* **Unit tests** for all core logic.
* **Component tests** for subsystems.
* **Integration tests** for critical external boundaries.
* **Contract tests** for stable APIs/schemas.
* **Smoke/system tests** for critical end-to-end paths.

### Conditional

* **Regression tests** for discovered issues.

### Conditional decision rule (risk acceptance)

If any mandatory class is waived due to exceptional circumstances, the waiver must be recorded with:

* explicit scope of waiver,
* operational mitigations (monitoring, rollback plan),
* owner and expiration/revisit date,
* planned remediation tests to add.
---

## 4. Explicit non-requirements

Not required by default:

* Exhaustive performance testing
* Chaos testing
* Full security penetration testing

---

## 5. Compliance criteria

The phase is compliant if:

1. Critical paths are covered at unit → integration → smoke level.
2. External interfaces behave according to contract.
3. Regressions are caught early and localized.
4. Test suite is reliable and repeatable.

---

## 6. Assessment

1. Enumerate critical user and system flows.
2. Verify coverage across required test classes.
3. Apply L3 procedures for each mandatory test class and record deviations.
4. Evaluate suite health (runtime, flakiness, clarity) via **L3-T10**.
4. Record outcome.

---

## 7. Forward rules

* Stabilization tests become permanent release gates.
* Known risks must be tracked explicitly if deferred.

---

## 8. Delegation

Invoke as needed:

* **L3-T1:** Unit Test
* **L3-T2:** Component Test
* **L3-T3:** Integration Test
* **L3-T4:** System / Smoke Test
* **L3-T7:** Contract Test
* **L3-T10:** Health and Metrics

---

## 9. Exit

Return pass / conditional pass / fail to L1.

---

