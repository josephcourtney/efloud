---
aliases:
  - L3-T10 — Health and Metrics
linter-yaml-title-alias: L3-T10 — Health and Metrics
tags: []
title: L3-T10 — Health and Metrics
---

# L3-T10 — Health and Metrics

## 1. Purpose

Provide a consistent method to assess **test suite health** and decide when test issues should block progression/release versus be tracked as follow-ups.

This procedure evaluates the suite as a socio-technical system: speed, determinism, signal quality, and maintainability.

## 2. Applicability

Apply:

* during L2 assessments (especially L2-P3, L2-P4, L2-P5),
* when flakiness or runtime creep is observed,
* when large refactors change test structure.

## 3. Health dimensions (what to measure)

### 3.1 Speed / feedback latency

Assess:

* unit suite runtime (developer loop viability),
* PR gating runtime (review latency),
* nightly runtime (coverage depth without blocking flow).

### 3.2 Flakiness / determinism

Assess:

* intermittent failures without code change,
* reliance on sleeps, timing races, shared state,
* environment sensitivity (ports, locale, filesystem paths).

### 3.3 Failure localization and clarity

Assess:

* whether failures point to a single behavior/boundary,
* whether assertions are legible and minimal,
* whether diagnostics (logs, captured artifacts) are sufficient.

### 3.4 Maintainability / brittleness

Assess:

* frequency of test churn for refactors that preserve behavior,
* tests coupled to internals (private attributes, call graphs),
* overbroad snapshots / noisy diffs.

### 3.5 Coverage of critical risk (qualitative)

Assess:

* coverage of core responsibilities/invariants,
* coverage of critical boundaries and contracts,
* presence of a minimal smoke set for end-to-end sanity.

## 4. Compliance classification

Classify health as:

* **Healthy**: suites run within expected budgets; failures localize; flake rate is low and actively managed.
* **Degraded**: issues exist but are bounded, tracked, and do not undermine trust in results.
* **Unhealthy**: tests are unreliable or slow enough that engineers stop running them, or failures do not localize.

## 5. Assessment procedure

1. **Collect evidence**
   * recent CI histories (failures and reruns),
   * local runtimes for unit/component selections,
   * top offenders (slowest tests, most-flaky tests).
2. **Diagnose root causes**
   * timing/async flake,
   * shared state,
   * expensive fixtures,
   * overbroad tests at too-high scope,
   * excessive mocking or unrealistic fakes.
3. **Recommend interventions**
   * downscope/upscope tests appropriately (L3-T1..T4),
   * improve harness (readiness probes, deterministic data),
   * split “smoke” vs “system” suites,
   * tighten snapshot canonicalization or replace snapshots (L3-T9),
   * add contract tests to reduce noisy integration failures (L3-T7).
4. **Record status and actions**
   * status (healthy/degraded/unhealthy),
   * concrete actions, owners, and deadlines.

## 6. Gating guidance (when to block)

### 6.1 Block (fail) when

* flakiness makes results untrustworthy for gating (retries become the norm),
* runtime exceeds the phase’s intended cadence such that developers/CI skip suites,
* failures do not localize and routinely require deep archaeology.

### 6.2 Conditional pass (with follow-up) when

* issues are bounded and mitigated (quarantine + ticket + expiration),
* runtime creep is modest and has a concrete remediation plan,
* a limited number of brittle tests exist but do not affect critical paths.

### 6.3 Pass when

* suite health supports intended workflows and risk profile.

## 7. Outputs

* health classification and rationale,
* list of top issues (flake, slow, brittle),
* prioritized remediation plan (what, owner, deadline),
* recommended scope shifts (downscope/upscope).

