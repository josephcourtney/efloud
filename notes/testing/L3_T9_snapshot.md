# L3-T9 — Snapshot Test: Design, Writing, Evaluation

## 1. Purpose

Capture and compare a **serialized representation** of an output (e.g., JSON, HTML, rendered text, structured objects) to detect unintended changes when outputs are **large but structurally stable**. Snapshotting is a convenience technique, not a primary correctness strategy.

Snapshot tests should be the last resort when clearer semantic assertions are impractical.

## 2. Applicability

Use when:

* the output is too large/verbose for hand-written assertions,
* the output shape is stable and reviewable,
* diffs are meaningful and actionable (not noisy).

Avoid when:

* targeted behavioral assertions are feasible and clearer,
* output contains high-churn or environment-dependent data (timestamps, UUIDs, ordering),
* snapshots would mask what behavior is actually intended.

### 2.1 When not to use this test type

Avoid snapshot tests when:

* reviewers cannot realistically validate diffs (snapshots too large or too frequent),
* snapshots include unstable fields (timestamps/UUIDs/order) without canonicalization,
* snapshots are being used instead of a small set of semantic assertions.

## 3. Design rules

### 3.1 Snapshot only stable, meaningful views

* Snapshot **the minimal stable view** of the output:

  * normalized ordering
  * redacted nondeterministic fields
  * canonical formatting
* Prefer snapshotting an **explicit “presentation model”** rather than raw internal structures.

### 3.2 Treat snapshots as reviewed artifacts

* Snapshots should be readable and diff-friendly.
* Changes to snapshots should be reviewed like code changes (because they redefine expected behavior).

### 3.3 Do not substitute for intent

* When the behavior can be expressed via a small number of assertions, do that instead.
* If you keep snapshots, add at least a few **targeted assertions** for the most critical semantic properties.

## 4. Writing procedure

1. Identify output(s) that are large but stable (responses, generated files, render trees).
2. Define a **canonicalization step**:

   * stable sorting
   * redaction of volatile fields
   * normalization of whitespace/formatting
3. Produce the snapshot from the canonical form.
4. Add targeted assertions for key semantics (e.g., required fields exist, critical values match).
5. Establish a workflow for updating snapshots:

   * update only when behavior change is intended,
   * review diffs for unintended broadenings/narrowings.

## 5. Evaluating an existing snapshot test

A snapshot test is good if:

* diffs are small, interpretable, and tied to intended changes,
* it snapshots a canonical representation (not raw, noisy output),
* it complements (does not replace) semantic assertions,
* it fails only on meaningful behavioral/interface changes.

Red flags:

* frequent churn with no semantic relevance (ordering/timestamps/unrelated fields)
* snapshots used as a “one-test-to-cover-everything” escape hatch
* very large snapshots that reviewers cannot realistically validate
* snapshots coupled to internal implementation details rather than public interface

## 6. Evaluating the snapshot suite

Check:

* **Necessity**: are snapshots used only where they materially reduce test friction?
* **Noise**: are snapshot diffs actionable or routinely ignored?
* **Coverage balance**: are critical behaviors still covered by non-snapshot assertions?
* **Maintenance**: snapshot updates are infrequent and intentional (not routine busywork).

Outputs:

* list of snapshots to replace with targeted assertions
* canonicalization improvements (redactions, ordering, formatting)
* pruning plan for snapshots that add more churn than confidence

### 7. Scope adjustment guidance (downscope / upscope)

* If a snapshot is stable but semantically unclear, replace with targeted assertions (often **unit/component** scope).
* If snapshot instability is due to boundary drift, consider adding **contract (L3-T7)** coverage and reducing snapshot breadth.

