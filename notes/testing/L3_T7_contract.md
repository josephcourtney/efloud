# L3-T7 — Contract Test: Design, Writing, Evaluation

## 1. Purpose

Validate **interfaces other systems rely on**: API schemas, DB schemas, event payloads, versioned contracts. Contract tests reduce “silent breakage” across boundaries.

## 2. Applicability

Use when:

* you publish or consume an interface used by another component/team/system,
* backward compatibility matters,
* you need early detection of schema/contract drift.

Contract tests complement (not replace) integration/system tests:

* **Contract**: shape/semantics of the boundary
* **Integration**: behavior with real external systems
* **System**: user-visible workflows across wiring

### 2.1 When not to use this test type

Avoid contract tests when:

* you are trying to validate internal business logic (use **L3-T1/L3-T2**),
* you need confidence in runtime behavior with real infrastructure (use **L3-T3**),
* the interface is not stable enough to define a meaningful contract yet (defer to L2-P1/L2-P2 and revisit in L2-P3).

## 3. Design rules

### 3.1 Define the contract artifact

Contracts should reference an explicit artifact where possible:

* OpenAPI / JSON Schema / Pydantic model
* DB migration expectations (columns, types, constraints)
* Event schema/version rules

### 3.2 Assert stable semantics, not incidental fields

Assert:

* required fields and types
* allowed value constraints
* compatibility rules (e.g., additive changes OK; breaking removals not)
* error response structure (where part of the contract)

Avoid:

* asserting entire payload equality when only part is contractual (unless truly required)

### 3.3 Fast, local, and deterministic

Many contract tests can run without full end-to-end harness:

* schema validation against recorded exemplars
* DB schema inspection against expectations
* consumer/source contract frameworks where appropriate

## 4. Writing procedure

1. **Identify the consumer-facing boundary** and who depends on it.
2. **Enumerate contract obligations**:

   * required fields
   * types/formats
   * constraints
   * versioning/compat rules
3. **Encode the contract**:

   * validate real responses/records/events against schema, or
   * assert schema structure directly (DB inspector, OpenAPI validator, etc.)
4. Add **one negative case** where valuable (e.g., missing required field yields expected error structure).

## 5. Evaluating an existing contract test

A good contract test:

* fails only when a dependency-relevant change occurs,
* clearly identifies what contract clause broke,
* is resilient to non-contractual changes.

Red flags:

* overly broad snapshots that create noisy diffs
* tests that duplicate unit/component logic rather than boundary semantics
* missing versioning/compatibility intent (test exists but doesn’t express “what is allowed to change”)

## 6. Evaluating the contract suite

Check:

* **Boundary inventory**: every published interface has at least one contract test.
* **Change detection**: likely breaking changes trigger failures early (PR time).
* **Noise level**: tests should rarely fail due to non-contractual changes.
* **Alignment**: contract tests match real consumers’ expectations (update contract artifact as needed).

Outputs:

* boundary → contract coverage map
* list of brittle/noisy contract tests to narrow
* list of uncovered or ambiguous contracts to formalize

### 7. Scope adjustment guidance (downscope / upscope)

* If a contract test is validating full behavior rather than interface obligations, downscope to **unit/component** tests.
* If a contract test frequently fails due to environment or live dependency quirks, split: keep the contract test local, and add a focused **integration test (L3-T3)** for the infra semantics.

