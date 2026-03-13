# L3-T6 — Property-Based Testing: Design, Writing, Evaluation

## 1. Purpose

Use generated inputs to validate that a unit/component upholds **invariants** over a broad input space (e.g., idempotence, round-trips, bounds, monotonicity), improving defect detection beyond enumerated examples.

## 2. Applicability

Best fit when:

* functions are pure or mostly pure (normalizers, parsers/formatters, comparators, transformations)
* correctness can be expressed as clear properties
* edge cases are numerous or non-obvious

Avoid when:

* behavior is heavily stateful, timing-dependent, or requires expensive external systems (use other test types)
* properties are ambiguous or would encode implementation instead of intent

### 2.1 When not to use this test type

Avoid property-based testing when:

* the subject is heavily stateful or requires complex external setup (prefer **L3-T2/L3-T3/L3-T4**),
* you cannot state 1–3 clear invariants without restating implementation,




* candidates to convert to example-based tests (if property adds little value)

## 3. Design rules

### 3.1 Properties must be simple and legible

Prefer properties like:

* **Idempotence**: `f(f(x)) == f(x)`
* **Round-trip**: `decode(encode(x)) == x` (within normalization rules)
* **Bounds**: output length/value within constraints
* **Symmetry**: `cmp(a,b) == -cmp(b,a)` (if relevant)
* **Stability**: sorting/normalization preserves some order/structure guarantees

Avoid:

* “properties” that restate the code (tautologies)
* overly complex invariants that are hard to debug

### 3.2 Control input domains

* Use generators that match **valid and near-valid** domains; include invalid inputs only if behavior is specified.
* Constrain sizes to keep runtime predictable.
* Explicitly handle or exclude pathological inputs when they are not in scope.

### 3.3 Determinism and diagnostics

* Ensure failing examples shrink to minimal counterexamples (default in Hypothesis-like tools).
* Record counterexamples in regression tests where appropriate (see L3-T5).

## 4. Writing procedure

1. Identify the **subject function/component** and its domain.
2. Write down 1–3 core **invariants** in plain language.
3. Implement generators for the domain (start narrow).
4. Encode properties as assertions.
5. If a counterexample is found:

   * fix the code or clarify the spec,
   * optionally add a targeted example-based regression test for the found case.

## 5. Evaluating an existing property-based test

A good property-based test:

* asserts a meaningful invariant tied to business/format semantics,
* uses well-scoped generators (not “any bytes” unless intended),
* runs within predictable time,
* produces actionable minimal counterexamples.

Red flags:

* frequent flaky failures due to timeouts or overly broad generators
* properties that are unclear or inconsistent with requirements
* tests that over-constrain inputs to the point that no meaningful exploration occurs

## 6. Evaluating the property-based suite

Check:

* coverage of critical invariants for transformation-heavy code
* runtime budget and placement (unit vs separate property suite)
* whether discovered counterexamples are being captured as regressions when appropriate
* whether the suite complements example-based tests rather than duplicating them

Outputs:

* list of missing invariants
* list of generators to refine (too broad/slow or too narrow)
* candidates to convert to example-based tests (if property adds little value)

### 7. Scope adjustment guidance (downscope / upscope)

* If a property test is effectively checking a few enumerated cases, replace with clearer example-based **unit tests (L3-T1)**.
* If failures reveal boundary/serialization semantics, consider adding **contract (L3-T7)** coverage and capture counterexamples as **regressions (L3-T5)**.

