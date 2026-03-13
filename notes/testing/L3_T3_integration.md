
# L3-T3 — Integration Test: Design, Writing, Evaluation

## 1. Purpose

Validate behavior **across real integration boundaries** (DB engine, HTTP service, broker, etc.), focusing on correctness of interactions, schemas, authn/z, error handling, and operational failure modes.

## 2. Applicability

Use when:

* correctness depends on real external semantics (SQL dialect, transaction behavior, auth, serialization, retries)
* you need confidence that contracts hold under real infrastructure
* component tests’ fakes are insufficient to model risk

Avoid using integration tests to:

* exhaustively test internal business logic (unit/component do that)
* simulate full user workflows (system tests do that)

### 2.1 When not to use this test type

Avoid integration tests when:

* the behavior is fully local/pure (prefer **L3-T1**),
* a fake models the risk adequately and keeps feedback faster (prefer **L3-T2**),
* you are primarily validating the shape of an interface (prefer **L3-T7**).

## 3. Design rules

### 3.1 Real dependencies, controlled environment

Integration tests should:

* run against **dedicated, resettable** test resources (prefer containerized services)
* be repeatable and isolated (clean state per test or per suite)
* avoid shared mutable state across tests unless explicitly managed

### 3.2 What to assert

Assert:

* request/response structure and codes (for APIs)
* schema validity and migrations (for DB)
* authorization behaviors
* handling of common disruptions (timeouts, retries, partial failure) where feasible

Avoid:

* asserting fine-grained internal behavior (logs, call sequences) unless the test is explicitly observability-focused
* broad “end-to-end” expectations spanning many systems unless intentionally a system test

### 3.3 Keep count low, value high

Integration tests are slower; prioritize high-risk boundaries and “unknown unknowns.” The goal is confidence per test, not volume.

## 4. Writing procedure

1. **Select the boundary** (DB, service, queue) and the specific risk.
2. **Provision real dependency** in a known state:

   * migrations applied
   * seed minimal data
3. **Exercise interaction** through the production client/repository layer (not mocks).
4. **Assert boundary-observable outcomes**:

   * persisted data correctness
   * API response semantics
   * contract conformance
5. **Add one negative case** per boundary where it meaningfully increases confidence (e.g., constraint violation, auth failure, timeout path).

## 5. Evaluating an existing integration test

A test is **good** if:

* it validates something that would be easy to get wrong with a fake
* it is repeatable and cleans up after itself
* failures are diagnosable (clear setup, clear assertions)
* it avoids brittle timing and arbitrary sleeps

Red flags:

* nondeterminism/flakiness (race conditions, sleeps, shared state)
* tests that are effectively system tests but lack proper harnessing
* excessive mocking inside an integration test (dilutes the point)

## 6. Evaluating the integration test suite

Check:

* **Boundary coverage**: each critical external dependency has at least one high-value test.
* **Runtime budget**: suite remains feasible in CI; push heavy tests to nightly where needed (per cadence guidance).
* **State management**: consistent reset strategy.
* **Failure localization**: failures should implicate a specific boundary or contract.

Outputs:

* inventory: boundary → tests → risks covered
* list of flaky tests and root causes
* recommendations: move tests (unit↔component↔integration↔system), add contract tests, improve harness

### 7. Scope adjustment guidance (downscope / upscope)

* If a test does not rely on real external semantics, downscope to **component (L3-T2)**.
* If a test spans multiple systems and is asserting user-visible workflows, upscope intentionally to **system (L3-T4)** and harden the harness accordingly.

