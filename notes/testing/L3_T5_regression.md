# L3-T5 — Regression / Sanity Test: Design, Writing, Evaluation

## 1. Purpose

Prevent recurrence of a **previously observed defect** (regression), or confirm a **specific fix/feature** works as intended (sanity). These tests exist to “lock in” a learned failure mode.

## 2. Applicability

Use when:

* a bug is fixed (especially one that escaped to later phases or production),
* a failure mode is subtle or likely to recur,
* a change has high blast radius and warrants a targeted guardrail.

A regression test can be unit/component/integration/system in scope; the key attribute is **purpose**.

### 2.1 When not to use this test type

Avoid adding regression tests that:

* merely duplicate existing coverage without encoding a distinct prior failure mode,
* require broad end-to-end harness when the defect can be localized to a lower scope,
* are so brittle/noisy that they will be ignored in practice (fix harness or choose a different scope).

## 3. Design rules

### 3.1 Reproduce the bug minimally

* Construct the smallest input/state that triggers the prior failure.
* Prefer the **lowest scope** that can reproduce it:

  * unit if the bug is pure logic,
  * component if orchestration is required,
  * integration if real boundary semantics caused it,
  * system only if it genuinely manifests only end-to-end.

### 3.2 Assert the previous wrong outcome cannot occur

Assert:

* correct output/state, or
* absence of the failure (exception, corrupt record, incorrect response), or
* a specific invariant now holds.

Avoid:

* asserting incidental internals “because that’s where it broke”
* overly broad end-to-end tests if the issue can be localized

### 3.3 Tie test to incident context

Regression tests should encode:

* what broke,
* the minimal reproduction,
* the expected behavior now.

This can be done via test names, docstrings, or a short comment referencing an issue/incident ID.

## 4. Writing procedure

1. Identify: **trigger**, **symptom**, **root cause** (as known).
2. Choose the **lowest feasible scope** that reproduces the symptom.
3. Add test that:

   * fails on the pre-fix code,
   * passes on the fix,
   * remains stable under refactors that preserve behavior.
4. If the bug involved boundary semantics, consider also adding/strengthening a contract or integration test.

## 5. Evaluating an existing regression/sanity test

A good regression test:

* would fail if the bug reappears in any plausible form,
* is minimal and stable,
* localizes failure quickly.

Red flags:

* reproductions that require large fixtures or long sequences when a smaller trigger exists
* tests that overfit to the fix’s implementation details
* tests that are flaky (often indicates timing/concurrency issues that need a better harness)

## 6. Evaluating the regression suite

Check:

* coverage of high-severity incidents and historically frequent defect classes
* redundancy (multiple tests for the same failure mode without added value)
* whether regressions are placed at the right scope (too many at system level is a common smell)

Outputs:

* list of missing regressions for notable incidents
* candidates to downscope (system→integration→component→unit)
* candidates to remove/merge

### 7. Scope adjustment guidance (downscope / upscope)

* Prefer the lowest scope that can reproduce the prior symptom.
* If root cause was a contract drift or boundary mismatch, add or strengthen **contract (L3-T7)** and/or **integration (L3-T3)** alongside the regression.

