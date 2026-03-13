---
aliases:
  - L2-P4
linter-yaml-title-alias: L2-P4
tags:
title: L2-P4
---

# L2-P4 — Release and Hardening Testing Phase

## 1. Phase intent

**Goal:**
Ensure correctness, reliability, and operability for production use.

**Primary risks addressed:**
Production outages, data corruption, security failures, unacceptable performance.

---

## 2. Applicability

Applies when:

* preparing a production release,
* enabling a major user cohort,
* operating under regulatory or SLA constraints.

---

## 3. Required test classes

### Mandatory

* **Unit and component tests** (baseline correctness).
* **Integration tests** for all critical dependencies.
* **System/smoke tests** for key user flows.
* **Contract tests** for all published interfaces.

### Conditional (risk-driven)

* **Performance tests**
* **Security tests**
* **Data-quality tests**
* **Observability tests**

### Conditional decision rule (risk acceptance)

For any conditional category that is relevant to the risk profile but not implemented, record:

* the specific failure mode(s) being accepted,
* why it is acceptable now (mitigations, limited rollout, monitoring),
* owner,
* revisit trigger (next release, incident, scale threshold, regulatory milestone).
---

## 4. Explicit non-requirements

Not required:

* Exhaustive edge-case exploration beyond defined risk scope.

---

## 5. Compliance criteria

The phase is compliant if:

1. All release-critical paths pass under realistic conditions.
2. External contracts are verified.
3. Operational signals (logs/metrics) are sufficient to diagnose failure.
4. Identified risks are mitigated or explicitly accepted.

---

## 6. Assessment

1. Review release scope and risk profile.
2. Verify required test evidence.
3. Apply L3 procedures for each mandatory test class and record deviations.
4. Evaluate suite health and enforcement readiness via **L3-T10**.
5. Confirm CI and release gates enforce required tests.
6. Record release decision.

---

## 7. Forward rules

* Release tests remain gating for future releases.
* Operational failures must feed back into L2-P5.

---

## 8. Delegation

Invoke as needed:

* **L3-T3:** Integration Test
* **L3-T4:** System / Smoke Test
* **L3-T7:** Contract Test
* **L3-T8:** Performance / Security / Data Quality (as applicable)
* **L3-T10:** Health and Metrics

---

## 9. Exit

Return release decision to L1.

---

