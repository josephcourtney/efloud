
# L3-T2 — Component Test: Design, Writing, Evaluation

## 1. Purpose

Validate a **coherent subsystem** (module/package/component) through its **public API**, exercising real collaboration among units while controlling dependencies outside the component boundary.

## 2. Applicability

Use when:

* multiple units must work together to deliver a behavior
* correctness depends on interactions (e.g., orchestration, internal adapters)
* you want confidence beyond unit tests without full integration/system cost

Do not use component tests as a substitute for:

* contract tests at external boundaries
* integration tests with real external systems when boundary behavior is the risk

### 2.1 When not to use this test type

Avoid component tests when the risk is primarily:

* contract drift for published interfaces (prefer **L3-T7**),
* real infra semantics (prefer **L3-T3**),
* full user journey correctness (prefer **L3-T4**).

## 3. Design rules

### 3.1 Define the component boundary

* Identify the “inside”: modules/classes you are validating together.
* Identify the “outside”: DB, HTTP services, filesystem, clock, message bus, env/config.

Component tests:

* must not mock *inside* the boundary
* may fake/mock *outside* dependencies only

### 3.2 Prefer in-process fakes

Prefer:

* in-memory repositories, fake clients, stub servers in-process
* lightweight real deps only when they are stable and low-friction (e.g., SQLite for a persistence adapter)

Avoid:

* extensive mocking frameworks that reproduce the component’s internal structure

### 3.3 Assertions

Assert:

* public API outputs and side effects observable at the boundary (returned objects, persisted records in a fake store, emitted events captured in-memory)
* error handling behaviors that the caller can observe

Avoid:

* verifying internal method call graphs
* asserting implementation-specific logging unless logs are declared part of the contract (that’s observability testing)

## 4. Writing procedure

1. **Pick a public API entrypoint** for the component.
2. **Set up external dependencies** as fakes/in-memory implementations.
3. **Execute a representative workflow**:

   * happy path
   * key edge path(s)
   * critical error path(s)
4. **Assert externally visible outcomes**:

   * returned values
   * state changes in fakes
   * events collected in-memory
5. **Only after the interface stabilizes**, consider snapshot tests for large serialized outputs (optional; keep targeted assertions preferred).

## 5. Evaluating an existing component test

A component test is **good** if:

* It uses only public APIs of the component.
* It mocks/fakes only *outside* dependencies.
* It is stable and deterministic.
* It provides confidence that unit tests alone cannot.

Red flags:

* component tests that look like unit tests (too narrow) or system tests (too broad)
* fragile fixtures (“god fixtures”)
* tests that pass while allowing incorrect behavior because fakes are unrealistic (fix fake fidelity or add integration/contract coverage)

## 6. Evaluating the component test suite

Check:

* **Boundary coverage**: key component entrypoints and workflows are covered.
* **Duplication**: not re-testing every unit path (leave that to unit tests).
* **Execution time**: should remain comfortable in PR pipelines (avoid “mini system suite” drift).
* **Confidence gaps**: where real boundary semantics matter, queue those for integration/contract tests.

Outputs:

* map of component workflows → existing tests
* list of missing workflows / boundary behaviors
* list of tests to downgrade to unit or upgrade to integration/system

### 7. Scope adjustment guidance (downscope / upscope)

* If a component test is narrow and tests a single pure function, downscope to **unit (L3-T1)**.
* If correctness depends on real DB/HTTP/broker semantics, upscope to **integration (L3-T3)**.
* If the failure only manifests end-to-end in realistic wiring, upscope to **system/smoke (L3-T4)**.

