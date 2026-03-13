---
aliases:
  - Best Practices - Automated Testing
linter-yaml-title-alias: Best Practices - Automated Testing
status: beta
tags: []
title: Best Practices - Automated Testing
---

# Best Practices - Automated Testing
> [!definition] Definition: Automated Testing
> [[Automated Testing]] is the use of software tools to execute predefined tests automatically, verifying that the target system works as intended and meets specified requirements.

## Core Principles
When writing and using tests, follow these principles:
- **Isolation**: A test's outcome must not depend on other tests or global state.
- **Efficiency**: Fast feedback sustains developer flow; slow tests are skipped and forgotten.
- **Clarity**: Test code must stay easy to read and diagnose.
- **Purpose**: Tests should signal whether the code has the right behavior.
- **Maintainability**: Tests should evolve with minimal churn not be brittle or overly high-level.
- **Diligence**: Failures, flakiness, and low metrics should prompt investigation.
- **Practicality**: Automate first where impact × likelihood of failure is highest.

## Project Lifecycle
- **Always**
    - Run **static analysis** on all code: formatters, linters, type checkers
    - Run **security tests**: secret scanners, dependency scans, and supply-chain verification
    - **Exploration** - clarify goals, reduce uncertainty
    - Given a fuzzy goal, build a prototype
    - Iterate, evaluate, and analyze the prototype to formalize requirements as **acceptance tests**
    - If fitting models, begin **data validation**, **metric tracking**, or **baseline capture**.
- **Development** - implement functionality
    - Discard prototype; scaffold production code.
    - For each feature, iterate until acceptance test passes
    - Build bottom-up with test-driven development:
        - Write **unit tests** and **component tests**, implement unit, repeat
        - Add **contract tests** for service boundaries
    - Refactor while keeping tests passing
    - Add **snapshot tests** once interface stabilizes
    - If applicable
        - add appropriate metrics
        - implement **data freshness**, **referential integrity**, **aggregation accuracy**, **anomaly detection**, **backfill**,
        - add hooks for observability, monitoring schema evolution, and/or data lineage
    - Implement test result and metric history tracking
- **Polishing** - improve behavior, code, and UX quality
    - Add **integration tests** and **system tests**
    - Add **usability tests**
    - Add **performance tests**
    - Optimize test suite with **smoke tests**
- **Hardening** - ensure robustness, security, and compliance
    - Implement **regression testing** and **rollback testing**
    - Add **compatibility testing**, **mutation testing**, **fuzzing**, and **chaos testing**
    - Add **privacy-impact tests**
- **Maintenance** - monitor, adapt, and refactor
    - Implement **synthetic monitoring**, **chaos testing**, and **model drift detection**
    - monitor project health; when it worsens, repair and refactor
    - If applicable, monitor **model accuracy drift**, **dataset shift**, and retrain when thresholds are breached
    - Track **flake rate**, **defect escape**, **test latency**, and **performance drift**.
    - When new requirements or threats emerge, return to **Development**
    - When fixing bugs, add **sanity tests**

## Testing Definitions
### Level
Tests can be categorized according their structural scope.
- **Static Analysis** evaluates code without executing it. It typically uses methods like pattern matching to identify potential problems.
- **Unit tests** confirm that a single function, method, or object is performing as expected, in isolation. They tend to involve isolating the unit, and mocking any external entities so that the unit can be treated as a pure function. They typically include evaluations of input-output pairs, confirmations that exceptions are raised under the correct conditions, and property-based testing. Unit tests should be fast (< 100 ms) so that they can be run often, possibly on every save, during development. They are typically structured according to the Arrange-Act-Assert pattern. They should utilize mocking of external dependencies and must not read or modify persistent state.
- **Component tests** evaluate the interactions between multiple units in a bounded context like a module. They should use only the public interfaces of the components and should only mock elements outside of the specified component.
- **System tests** evaluate the high-level, user-facing behavior, treating it as a black box. They are typically slow and resource-heavy as they involve simulating user interaction.
- **Integration tests** evaluate the interactions between units or components of two separate systems. They are used to evaluate APIs, authorization and authentication, communication disruption handling, schema validation, version contracts, etc. They often make use of containerized services to allow their state to be reset for every test.

### Purpose
Tests can be categorized according to their purpose or the aspect they are intended to evaluate.
- **Acceptance tests**: satisfy requirements the code was written to address.
- **Regression tests**: prevent unintended degradation over time.
  - **Sanity tests**: confirm that a specific bug fix or feature implementation behaves as expected.
  - **Rollback tests**: verify that a system or database can revert cleanly to a prior state after a deployment or migration. It typically involves applying a migration, running validation, executing the rollback, and re-verifying state consistency.
  - **Performance Regression tests**: confirm that latency, throughput, and resource use do not degrade significantly compared to typical values.
- **Smoke tests**: verify that the most critical system features are functioning and stable enough to proceed with more detailed testing.
- **Compatibility tests**: check that functionality works across different operating systems, browsers, or devices to ensure consistent behavior and presentation. Typically they are executed using grid-execution platforms.
- **Data quality tests**: validate incoming or transformed datasets against expectations for null values, statistical norms, freshness, referential integrity, and uniqueness.
- **Database tests**: validate the correctness, integrity, and performance of database operations. It checks CRUD logic, constraint enforcement, transaction behavior, indexing, stored procedures, and triggers.
  - **Queries & schema tests**: evaluate the correctness and stability of database queries and schema definitions. They verify that expected indexes, constraints, and table structures are present and that SQL queries return correct and performant results.
- **Performance tests**: confirm that latency, throughput, and resource use targets are met.
- **Security tests**: encompass static code analysis, dependency scanning, fuzzing of authentication flows, and penetration testing to uncover vulnerabilities.
  - **Vulnerability scans**: detect known security issues in source code, dependencies, and deployed systems using databases like CVE/NVD or custom signatures.
  - **Secret scans**: prevent leaking of credentials, API keys, and other sensitive values in source code and build artifacts.
  - **Privacy-impact tests**: verify conformance to privacy regulations such as GDPR or CPRA by analyzing data flows and enforcing constraints like differential privacy budgets.
  - **Supply-chain verifications**: evaluate dependencies for verified provenance, approved licensing, and absence of known vulnerabilities, failing builds when criteria are not met. This is performed at static and integration stages.
- **Service/API tests**: validate the functionality, reliability, and contract compliance of a service's public interface (typically HTTP or RPC). They test response structure, status codes, authorization handling, edge cases, and error conditions.
  - **Contract tests**: verify that the interaction between a service source and consumer adheres to a shared schema or expectation, without requiring end-to-end environments.
  - **Schema validation tests**: ensure that data structures (e.g., JSON, Avro, database schemas) conform to a defined specification, catching mismatches or invalid formats before processing.
- **Usability tests**: attempt to evaluate the user experience. In general, UX is impossible to evaluate with full automation. Automated usability tests typically cover accessibility, internationalization, and heuristics like conforming to UI style guides and avoiding antipatterns.
  - **Accessibility and internationalization tests**: verify that systems comply with standards like WCAG and behave correctly across locales, languages, and encodings.
- **Continuous Behavior**
  - **Synthetic monitoring**: simulate real user interactions with a production system on a recurring schedule to detect regressions, latency increases, or downtime. It operates continuously and externally, typically testing user-critical flows like login, checkout, or API endpoints.
  - **Model drift detection**: monitor deployed machine learning models for input distribution shifts or degraded predictive performance due to data drift.
- **Linting**: identifies stylistic and programming errors by analyzing source code against a set of predefined rules. It enforces code quality standards and detects issues like unused variables, unreachable code, or dangerous patterns.
- **Formatting**: enforces a consistent code layout (e.g. indentation, spacing, line length) according to a predefined style guide. It is typically automated and does not affect program behavior.
- **Type Checking**: validates that variables, function arguments, and return values conform to declared or inferred types. It can be static (at compile time) or dynamic (at runtime) and prevents type errors before or during execution.
- **Dataflow Analysis**: traces the flow of data through variables and control structures to detect issues like uninitialized variables, tainted input propagation, or dead code. It supports optimization and security auditing.
- **Abstract Interpretation**: approximates program behavior by interpreting code over abstract domains instead of concrete values, enabling sound detection of properties like possible null dereferences, integer overflows, or unreachable code.
- **Formal Verification**: uses mathematical proofs to verify that a system adheres to its specification under all possible conditions. It is applied to critical systems where exhaustive correctness is required.

### Techniques
These techniques can be used to create or structure tests.
- **Arrange-Act-Assert**: A unit test structure where setup is performed (*Arrange*), the behavior is invoked (*Act*), and outcomes are verified (*Assert*).
- **AI-assisted test generation** leverages large language models to generate, deduplicate, and automatically repair tests based on source code and runtime data. These tools span unit to system level and include platforms like Diffblue, Copilot-tests, and TestGPT.
- **Canary (chaos canary)**: A pre-identified workload or subsystem monitored during chaos experiments to detect early signs of systemic degradation or failure.
- **Chaos engineering** intentionally injects faults into a running system to validate resilience, recovery mechanisms, and observability. It targets integration and system levels using tools such as Gremlin and ChaosMesh.
- **Fuzzing** supplies malformed, unexpected, or semi-random inputs to a system to uncover crashes, memory issues, or unhandled exceptions. It applies from unit to system level, with tools like AFL, libFuzzer, and OSS-Fuzz supporting coverage-guided input generation.
- **In-process fakes**: Test doubles (e.g., fake databases or services) that run in the same process as the system under test, offering deterministic, fast substitutes for external dependencies.
- **Instrumentation and tracing** embed hooks into a system to record metrics, logs, or spans during test execution, supporting runtime analysis and debugging. These techniques apply at the integration and system level and are often powered by OpenTelemetry.
- **Mocking and faking** involve substituting real dependencies with controlled test doubles to isolate behavior under test. This practice is common in unit and component testing, supported by frameworks such as Mockito and `pytest-mock`.
- **Mutation testing** introduces small changes (mutations) into code and verifies that existing tests fail in response, thereby measuring test suite effectiveness. This is typically applied at the unit level using tools such as Pitest or Stryker.
- **Observability hooks in tests** export structured logs, metrics, and traces from the test environment to help diagnose failures. These hooks are used during integration and system tests, often integrated with observability stacks via OpenTelemetry collectors.
- **Parallelization** divide test suites into shards and use test-impact analysis to prioritize only the most relevant tests, reducing feedback time. This approach is applied across large-scale unit to system testing environments.
- **Property-based testing** generates randomized inputs to verify that a system upholds defined invariants across a wide input space. It is most effective at the unit or component level and is implemented using libraries like Hypothesis or QuickCheck.
- **Runtime chaos**: Fault injection during live system execution to test resilience—such as killing services, injecting latency, or corrupting network traffic—performed in controlled environments.
- **Snapshotting** captures and stores outputs (visual, structural, or serialized) and compares them against future test runs to detect unintended changes. This technique is used in unit, component, and UI testing contexts, with tools like Jest and Syrupy.

### Test Input
data required to run tests
- **Feature-store contracts**: Schemas and data quality expectations attached to ML feature definitions in a feature store, ensuring that feature generation remains consistent across training and inference contexts.
- **Version contracts**: Explicit agreements that define how services or data consumers interact with specific versions of APIs or schemas, preventing breaking changes in evolving systems.
- **Service-contract**: A formal specification of a service's input-output behavior (e.g., API spec), including required fields, error codes, and data formats, enabling safe integration and validation.
- **Snapshot**:
- **Differential-privacy budgets**: Constraints on the cumulative privacy loss allowed in queries to sensitive datasets, quantified by parameters (e.g., ε) to manage re-identification risk under differential privacy.
- **Anonymization**:
- **Data Synthesis**:

## Guidelines
### Testing Cadence

| Trigger              | Tests to run                                                          | Rationale                                           |
| -------------------- | --------------------------------------------------------------------- | --------------------------------------------------- |
| Every save           | Static, quick Unit                                                    | Keep feedback less than a few seconds.              |
| Every commit         | Static, Unit, tiny Component                                          | Keep feedback ≤ 2 min                               |
| Pull request         | Component, Contract, Smoke Performance                                | Block regressions before merge                      |
| Nightly              | Full Integration, Mutation, Extended Performance, Fuzz, Flake tracker | Deep safety net without slowing daytime work        |
| Pre-release          | End-to-End, Compliance, Chaos, Full-load Performance                  | Validate system health and standards compliance     |
| Post-deploy (24 × 7) | Synthetic Monitoring, Light Chaos                                     | Detect production issues and resilience regressions |

### Metrics

- **Compatibility Matrix**: test results stratified by platform, device, or browser configurations.
    - **Target**: test success on hardware where code is used most
- **Coverage**
  - **Line Coverage**: Percentage of executed lines of code during test execution.
    - **Target**: > 80% (back-end), > 70% (front-end)
  - **Branch Coverage**: Percentage of executed code branches (e.g., if/else, switch cases) during tests.
    - **Target**: > 70% (back-end), > 60% (front-end)
  - **Case Coverage**: Proportion of defined logical or business-critical cases that are exercized by tests.
    - **Target**: 100% for critical paths
  - **Path Coverage**: Percentage of all possible execution paths through the code that are tested.
    - **Target**: > 50% general; > 80% for safety-critical or regulated domains
- **Mutation Score**: Percentage of artificial defects (mutants) introduced into code that are detected (i.e., killed) by the test suite.
  - **Target**: > 85% (safety-critical systems), > 70% (general purpose)
- **Flake Rate**: Percentage of tests that intermittently fail without code changes (i.e., nondeterministic failures).
  - **Target**: < 1%; alert if 2 out of 20 recent failures are flaky
- **Defect-Escape Rate**: Number of defects discovered in production per 1,000 lines of code.
  - **Target**: < 0.5 defects per 1 KLOC
- **Performance Regression**: Degree to which a new version of the system is slower or more resource-intensive than a baseline version, measured via latency, throughput, or memory/cpu usage.
  - **Target**: Must remain within defined thresholds; typically ±5-10% from baselines unless justified
- **Population Stability Index (PSI)**: A statistical measure of distributional shift in input or output data between two samples (e.g., training vs. production).
    - **Target**: depend. Typical ranges: low: < 0.1; 0.1 ≤ medium < 0.25; high ≥ 0.25
- **Kolmogorov-Smirnov Statistic**: Measures the maximum distance between two cumulative distribution functions. Often used to evaluate binary classifiers and data drift.
  - **Target**:
    - For classifier separation (e.g., fraud vs. legit): KS > 0.2 is considered acceptable; KS > 0.4 is strong
    - For drift detection: significant change if KS ≥ 0.1 depending on context
- **Cyclomatic Complexity**: Definition
  - **Target**: Target
- **Code Duplication**: Definition
  - **Target**: Target
- **Coupling**: Definition
  - **Target**: Target
- **Comment Density**: Definition
  - **Target**: Target

## Bad Habits
- Violation of Isolation
  - Unit tests that read or write real files, hit the network, or change global state without cleanup.
- Violation of Efficiency
  - Arbitrary sleeps or waits in asynchronous tests that hide race conditions and slow feedback.
  - Oversized end-to-end suites duplicating lower-level checks and extending CI cycle time.
- Violation of Clarity
  - Snapshots that capture incidental UI or data details, producing noisy diffs and masking true regressions.
  - Over-mocking external dependencies, concealing breaking API changes and weakening behavioral checks.
- Violation of Purpose
  - Chasing 100 % line-coverage targets with trivial assertions that add little defect-detection value.
  - Tests that depend on internal implementation details become change-detectors rather than proper tests.
- Violation of Maintainability
  - Mocking external faults instead of using a containerized replica, giving false confidence.
  - Accumulating overlapping test frameworks or tools that increase cognitive load and maintenance effort.
- Violation of Diligence
  - Suppressing or ignoring secret-scanner or vulnerability-scan warnings.
  - Using metrics solely as pass/fail gates without probing underlying causes or suite gaps.

## References

- **Kent Beck:** *Test-Driven Development by Example*
- **Martin Fowler:** Test Pyramid; "Mocks Aren't Stubs"
- **Roy Osherove:** *The Art of Unit Testing*
- **Michael Feathers:** *Working Effectively with Legacy Code*
- **Lisa Crispin & Janet Gregory:** Agile Testing Quadrants
- **Mike Cohn:** *Succeeding with Agile*
- **John Hughes:** QuickCheck and property-based testing
- **Hypothesis:** Python property-based testing
- **Pact:** Contract testing for APIs
- **Pitest / Stryker:** Mutation testing
- **Gremlin:** Chaos engineering
- **AFL / libFuzzer:** Coverage-guided fuzzers
- **Buildkite Flaky Test Reporter:** Flake tracking
- **ISTQB:** Risk-based and compliance testing standards
- **Modern observability vendors:** Synthetic monitoring (Datadog, Splunk)
- [kiwicom/pytest-recording](https://github.com/kiwicom/pytest-recording) - record/replay HTTP traffic
- [syrupy-project/syrupy](https://github.com/syrupy-project/syrupy) - snapshot testing plugin for pytest
