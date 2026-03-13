# L3-T8 — Non-Functional Tests (Risk-Driven): Design, Writing, Evaluation

## 1. Purpose

Validate properties other than functional correctness, selected based on **risk profile**:

* **Performance** (latency/throughput/resource)
* **Security** (vulnerability/abuse resistance)
* **Data quality** (freshness/integrity/anomaly)
* **Observability** (logs/metrics/traces as contract)

These tests are typically gating in release/hardening phases for relevant systems.

## 2. Applicability

Use when:

* non-functional failure would cause material harm (SLA breach, data corruption, incident response failure),
* the system is customer-facing or compliance-constrained,
* the risk profile explicitly requires it (L2-P4).

### 2.1 When not to use this test type

Avoid non-functional tests that:

* have no explicit measurable contract (threshold, invariant, required signal),
* are too noisy to be actionable (uncontrolled variance),
* are run at an inappropriate cadence (e.g., heavy perf gates on every save).

## 3. Design rules (common)

* Define the **measurable contract** (threshold, invariant, required signal).
* Prefer repeatable harnesses; isolate environmental noise where feasible.
* Keep assertions robust to small variance; avoid brittle micro-benchmarks.
* Separate “diagnostic measurement” from “gating thresholds” where necessary.

## 4. Sub-procedures by category

### 4.1 Performance tests

**Design**

* Identify critical endpoints/operations and the metric (p50/p95 latency, throughput, memory).
* Establish a baseline and acceptable band (e.g., ±5–10% where appropriate).
* Control data sizes and warmup; avoid conflating functional and perf assertions.

**Evaluate a test**

* Does it measure something stable and meaningful?
* Is variance controlled (warmup, fixed dataset, pinned environment)?
* Are thresholds justified and not arbitrary?

**Evaluate the suite**

* Coverage of top critical paths.
* Trend tracking and regression detection strategy.
* Runtime placement (PR vs nightly) aligned to cost.

---

### 4.2 Security tests

**Design**

* Include static security scanning and dependency checks as baseline.
* Add targeted dynamic tests where abuse cases are known (authZ, injection boundaries, unsafe deserialization).
* Prefer boundary-focused tests over deep internal mocking.

**Evaluate a test**

* Does it reflect a realistic threat model?
* Does it fail closed with actionable diagnostics?
* Is it maintained as dependencies and attack surface evolve?

**Evaluate the suite**

* Coverage of authentication/authorization and data-handling boundaries.
* Handling of known CVEs and secret scanning hygiene.
* Regular cadence and gating rules.

---

### 4.3 Data quality tests

**Design**

* Define invariants: referential integrity, uniqueness, null bounds, freshness windows, distribution constraints.
* Place checks near ingestion/transformation boundaries.
* Include backfill and aggregation accuracy checks when relevant.

**Evaluate a test**

* Does it detect the failure mode early (before consumers are harmed)?
* Are thresholds justified (not overly sensitive)?
* Does it localize which dataset/transform broke?

**Evaluate the suite**

* Coverage across critical datasets and transforms.
* Handling of drift/anomaly over time (alerting vs gating).
* Runtime strategy (CI vs scheduled validation).

---

### 4.4 Observability tests

**Design**

* Treat key logs/metrics/traces as a contract for critical flows.
* Assert on presence/shape of signals (event emitted, fields included), not full text unless explicitly contractual.

**Evaluate a test**

* Does it test what operators need (IDs, error codes, key metrics)?
* Is it robust to log phrasing changes (prefer structured fields)?

**Evaluate the suite**

* Coverage of critical flows and error paths.
* Signals are sufficient to diagnose failures without guesswork.

---

## 5. Assessment outputs

For each non-functional category in scope:

* coverage map (critical path → test coverage)
* thresholds/baselines and justification
* flakiness/noise analysis
* recommendation: PR gating vs nightly vs pre-release

### 6. Scope adjustment guidance (downscope / upscope)

* If non-functional checks are stable and low-cost, move them earlier (PR gating).
* If checks are expensive or noisy, move them to scheduled runs while improving harness fidelity and observability.

