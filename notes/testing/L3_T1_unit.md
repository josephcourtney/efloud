# L3-T1 — Unit Test (Pure Logic): Design, Writing, Evaluation

## 1. Purpose

Validate correctness of a **single unit** (function/method/class) in **isolation** with fast, deterministic feedback. Unit tests should predominantly assert **input→output**, raised exceptions, and invariants.

## 2. Applicability

Use when the behavior is primarily:

* calculation, transformation, parsing/formatting, decision logic
* state transitions local to a unit (without real I/O)
* invariants (“this can never happen”)

Do **not** use unit tests to validate third-party systems, framework behavior, or network/db/filesystem interactions.

### 2.1 When not to use this test type

Avoid unit tests when correctness depends on real external semantics (SQL dialects, auth flows, wire formats, retries). Use **L3-T3** (integration) and/or **L3-T7** (contract) instead.

## 3. Design rules

### 3.1 What a unit test may depend on

Allowed:

* pure inputs (scalars, small dicts, dataclasses)
* in-memory fixtures and deterministic fakes
* dependency injection (pass collaborators in)

Disallowed:

* real network, real DB, persistent filesystem
* real time, sleeps, non-deterministic randomness (unless seeded and bounded)
* reliance on global state or test order

### 3.2 What to assert

Prefer:

* explicit expected outputs
* explicit exceptions and error messages only if message text is part of the contract
* invariants and idempotence (consider property-based in L3-T6 if broad)

Avoid:

* private attributes, internal call sequences, incidental intermediate values
* asserting “this helper was called” unless it is the *observable contract* (rare)

### 3.3 Structuring tests

* Arrange–Act–Assert is the default structure.
* One conceptual behavior per test; split cases rather than building long scenario tests.

## 4. Writing procedure

1. **Name the behavior** (not the implementation): `test_<behavior>_<condition>()`.
2. **Select representative cases**:

   * nominal
   * boundary/edge
   * invalid input / error path (if specified)
3. **Assert the contract**:

   * returned value(s), raised exception type, or emitted domain event (if your unit returns them)
4. **Refactor for purity if friction is high**:

   * extract pure function
   * introduce explicit dependencies
   * move I/O behind wrappers (tested elsewhere)

## 5. Evaluating an existing unit test (single-test review)

A unit test is **good** if:

* It fails for the right reason and localizes to a small code region.
* It is deterministic and isolated (no hidden dependencies).
* It asserts behavior, not implementation details.
* It is readable in under ~30 seconds.

Red flags:

* mocks stacked deep into internals (indicates missing boundary/wrapper)
* assertions that mirror the implementation line-by-line
* time-based waiting or reliance on ordering
* broad snapshots used to avoid thinking (prefer targeted assertions)

## 6. Evaluating the unit test suite (suite review)

Check:

* **Coverage of responsibilities**: each core business rule and invariant has at least one test.
* **Speed**: unit suite supports rapid iteration (avoid slow creep).
* **Signal quality**: failures point to one unit/behavior with minimal noise.
* **Maintenance load**: refactors should not break many unit tests unless behavior changed.

Outputs:

* list of missing behaviors/invariants
* list of brittle tests to rewrite (implementation-coupled)
* list of refactors to increase purity / injection

### 7. Scope adjustment guidance (downscope / upscope)

* If a unit test requires deep mocks of internals, refactor for clearer boundaries or promote to a **component test (L3-T2)** with faked externals.
---

