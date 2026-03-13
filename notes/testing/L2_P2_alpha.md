### Procedure L2-P2: Feature Development Testing Phase

#### 1. Phase intent

**Goal:**
Establish correctness of newly introduced or modified behavior while enabling rapid iteration.

**Primary risks addressed:**
Incorrect core logic, poor isolation, tests that impede refactoring.

**Deferred risks:**
Full integration coverage, system-level behavior, non-functional properties unless risk dictates otherwise.

(See *automated_testing.md* for definitions of test levels and purposes.)

---

#### 2. Applicability

This phase applies when:

* implementing new features or workflows,
* modifying core business logic,
* performing significant refactors prior to stabilization.

This phase assumes interfaces are still evolving; contract tests written here may be provisional.

---

#### 3. Required test classes

##### Mandatory

* **Unit tests** for all core logic and invariants.
* **Component tests** for non-trivial subsystems.

##### Conditional

* **Regression tests** for non-trivial bug fixes.

##### Advisory

* Contract, integration, observability, or snapshot tests where interfaces stabilize early or risk is elevated.

(Definitions and boundaries per *automated_testing.md*.)

#### 4. Explicit non-requirements

Not required by default in this phase:

* System / end-to-end tests
* Performance, security, chaos testing

#### 5. Compliance criteria

The phase is compliant if:

1. All new or changed responsibilities have executable tests.
2. Tests assert observable behavior and localize failures.
3. Code structure supports isolation and dependency injection.
4. No unacknowledged high-risk gaps remain.

#### 5.1 Conditional decision rule (risk acceptance)

When a conditional or advisory test class is omitted, the omission must be explicitly recorded with:

* the risk and failure mode being accepted,
* rationale for omission (cost, phase appropriateness, mitigations),
* owner,
* revisit trigger (typically L2-P3 or before release).

#### 6. Assessment

1. Identify changed responsibilities.
2. Verify required test classes exist.
3. For each **mandatory** test class, apply the corresponding **L3 procedure** in full and record deviations.
4. For conditional/advisory test classes selected, apply the corresponding **L3 procedure** in full and record deviations.
4. Record outcome: pass / conditional pass / fail.

#### 7. Forward rules

* Tests written here persist as regression assets.
* Documented gaps must be revisited in later phases.
* Short-term testing shortcuts must be explicit.

#### 8. Delegation

Invoke as needed:

* **L3-T1:** Unit Test (Pure Logic)
* **L3-T2:** Component Test
* **L3-T5:** Regression / Sanity
* **L3-T6:** Property-Based Testing

Also consider (risk-driven):

* **L3-T7:** Contract Test
* **L3-T9:** Snapshot Test
* **L3-T10:** Health and Metrics (suite-level)


