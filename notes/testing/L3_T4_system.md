# L3-T4 — System / Smoke Test: Design, Writing, Evaluation

## 1. Purpose

Validate **end-to-end, user-facing behavior** by treating the application as a **black box**. “Smoke” is the **small, critical-path subset** used for fast gating.

## 2. Applicability

Use when you need confidence that:

* the system boots and runs in a realistic configuration,
* critical workflows function across real wiring,
* major regressions are caught at the user boundary.

Do not use system tests to replace unit/component coverage; they are slower, more brittle, and less localizing.

### 2.1 When not to use this test type

Avoid system tests when:

* the behavior can be validated at unit/component scope with better localization (prefer **L3-T1/L3-T2**),
* the risk is boundary semantics rather than full wiring (prefer **L3-T3** and/or **L3-T7**),
* a snapshot would be used as a substitute for semantic assertions (prefer targeted assertions; use **L3-T9** sparingly).

## 3. Design rules

### 3.1 Keep scope minimal and critical

* Prefer a **small set of high-value flows**:

  * startup/shutdown
  * one “happy path” per top-tier user journey
  * one critical error-handling journey (if high risk)
* Avoid comprehensive scenario matrices; push detail down to unit/component/integration.

### 3.2 Black-box assertions only

Assert:

* externally visible outputs (HTTP responses, CLI output, produced files, UI render results)
* stable contract-level properties (status codes, key fields, artifacts created)

Avoid:

* internal call graphs
* incidental logs unless logs are declared part of the contract (that’s observability testing)

### 3.3 Determinism and isolation

* Use controlled environments (ephemeral ports, temp dirs, isolated containers).
* Avoid arbitrary sleeps; use readiness probes, polling with timeouts, or explicit hooks.

## 4. Writing procedure

1. **Select a critical flow** and define its pass/fail criteria.
2. **Bring up the app** as a black box (process/container).
3. **Drive inputs** as a user would (HTTP client, CLI invocation).
4. **Assert outcomes** at the boundary.
5. If the test is a **smoke test**, minimize setup and assertions to what’s necessary for a fast, reliable gate.

## 5. Evaluating an existing system/smoke test

A good system/smoke test:

* covers a top critical path with minimal steps,
* fails with actionable signals (clear boundary symptom + context),
* is stable across environments (no port collisions, timing flake, hidden state).

Red flags:

* broad end-to-end suites duplicating lower-level checks (slow and brittle)
* heavy reliance on sleeps or fixed timing
* assertions on volatile UI/serialized details without need (consider targeted assertions or selective snapshots)

## 6. Evaluating the system/smoke suite

Check:

* **Smoke set size**: small enough to run frequently.
* **Flow selection**: aligned to business-critical journeys.
* **Runtime and flake rate**: if flaky/slow, reduce scope, improve harnessing, or push to nightly.
* **Redundancy**: ensure system tests are not doing the job of unit/component.

Outputs:

* curated smoke list
* list of system tests to split (move logic checks down a level)
* harness improvements (readiness, isolation, deterministic data)

### 7. Scope adjustment guidance (downscope / upscope)

* If system tests are duplicating logic checks, push those checks down to **unit/component/integration**.
* If system tests are flaky due to environment complexity, reduce scope to a smaller smoke set and move heavier scenarios to scheduled runs with a stronger harness.

