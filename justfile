# ======================================================================
# Global shell + environment
# ======================================================================

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := true
set export := true

# ----------------------------------------------------------------------
# Config (overridable via env/.env)
# ----------------------------------------------------------------------

MODE          := env("MODE", "dev")  # dev | debug | ci
ROOT_DIR       := justfile_directory()
PACKAGE        := file_stem(ROOT_DIR)
PYTHON_PACKAGE := env("PYTHON_PACKAGE", "efloud")
VERBOSE        := env("VERBOSE", "0")
REPO_CACHE_DIR := ROOT_DIR + "/.cache"
UV_CACHE_DIR   := REPO_CACHE_DIR + "/uv"
RUFF_CACHE_DIR := REPO_CACHE_DIR + "/ruff"

PY_TESTPATH    := "tests "
PY_SRC         := "src"
PYTHONPATH     := if env("PYTHONPATH", "") == "" { ROOT_DIR } else { ROOT_DIR + ":" + env("PYTHONPATH", "") }

# ----------------------------------------------------------------------
# Tool wrappers
# ----------------------------------------------------------------------

UV                  := "uv --cache-dir " + UV_CACHE_DIR
PYTHON              := ROOT_DIR + "/.venv/bin/python"
RUFF                := ROOT_DIR + "/.venv/bin/ruff"
PYTEST              := ROOT_DIR + "/.venv/bin/pytest"
TY                  := ROOT_DIR + "/.venv/bin/ty"
SHOWCOV             := ROOT_DIR + "/.venv/bin/showcov"
MUTMUT              := ROOT_DIR + "/.venv/bin/mutmut"
MKDOCS              := ROOT_DIR + "/.venv/bin/mkdocs"
WILY                := ROOT_DIR + "/.venv/bin/wily"
WILY_CACHE          := ROOT_DIR + "/.wily"
WILY_CONFIG         := ROOT_DIR + "/wily.cfg"
VULTURE             := ROOT_DIR + "/.venv/bin/vulture"
RADON               := ROOT_DIR + "/.venv/bin/radon"
JSCPD               := "npx --yes jscpd@4.0"
DIFF_COVER          := ROOT_DIR + "/.venv/bin/diff-cover"
IMPORTLINTER        := ROOT_DIR + "/.venv/bin/lint-imports"
IMPORTLINTER_CONFIG := ROOT_DIR + "/import-linter.toml"

# ======================================================================
# Meta / Defaults
# ======================================================================

[private]
default: help

# List available recipes; also the default entry point
help:
  @just _log_start help
  @just --list --unsorted --list-prefix "  "
  @just _log_end help


# Print runtime configuration (paths + tool binaries)
env:
  @just _log_start env
  @echo "MODE={{MODE}}"
  @echo "PACKAGE={{PACKAGE}}"
  @echo "PYTHON_PACKAGE={{PYTHON_PACKAGE}}"
  @echo "PY_TESTPATH={{PY_TESTPATH}}"
  @echo "PY_SRC={{PY_SRC}}"
  @echo "UV={{UV}}"
  @echo "RUFF={{RUFF}}"
  @echo "PYTEST={{PYTEST}}"
  @echo "TY={{TY}}"
  @echo "SHOWCOV={{SHOWCOV}}"
  @echo "MUTMUT={{MUTMUT}}"
  @echo "MKDOCS={{MKDOCS}}"
  @{{UV}} --version || true
  @{{PYTEST}} --version || true
  @{{RUFF}} --version || true
  @echo "WILY={{WILY}}"
  @echo "WILY_CACHE={{WILY_CACHE}}"
  @echo "WILY_CONFIG={{WILY_CONFIG}}"
  @echo "VULTURE={{VULTURE}}"
  @echo "RADON={{RADON}}"
  @echo "JSCPD={{JSCPD}}"
  @echo "DIFF_COVER={{DIFF_COVER}}"
  @just _log_end env

# ----------------------------------------------------------------------
# Logging helpers
# ----------------------------------------------------------------------

_log_start NAME:
  @bash -euo pipefail -c 'if [ "{{VERBOSE}}" != "0" ]; then printf "\n=== START: %s ===\n" "{{NAME}}"; fi'

_log_end NAME:
  @bash -euo pipefail -c 'if [ "{{VERBOSE}}" != "0" ]; then printf "=== END: %s ===\n\n" "{{NAME}}"; fi'

_cache_dirs:
  @mkdir -p {{REPO_CACHE_DIR}} {{UV_CACHE_DIR}} {{RUFF_CACHE_DIR}}

# ----------------------------------------------------------------------
# Quiet runners (brief on success, verbose on failure)
# ----------------------------------------------------------------------

_run NAME CMD:
  @bash -euo pipefail -c '\
    name="$1"; cmd="$2"; \
    set +e; out="$(bash -c "$cmd" 2>&1)"; status=$?; set -e; \
    if [ $status -eq 0 ]; then \
      echo "[1;32m✓ $name[0m"; \
    else \
      echo "[1;31m✗ $name[0m"; \
      echo "$out"; \
      exit $status; \
    fi' -- "{{NAME}}" {{quote(CMD)}}

_run_soft NAME CMD:
  @bash -euo pipefail -c '\
    name="$1"; cmd="$2"; \
    set +e; out="$(bash -c "$cmd" 2>&1)"; status=$?; set -e; \
    if [ $status -eq 0 ]; then \
      echo "[1;32m✓ $name[0m"; \
    else \
      echo "[1;31m✗ $name[0m"; \
      echo "$out"; \
      echo "[1;33m[warn][0m continuing after failure in $name" 1>&2; \
    fi' -- "{{NAME}}" {{quote(CMD)}}




# ======================================================================
# Bootstrap
# ======================================================================

# Bootstrap: refresh .venv via `uv sync`
setup:
  @just _log_start setup
  @just _cache_dirs
  {{UV}} sync
  @just _log_end setup


# ======================================================================
# Code quality: lint / format / type-check
# ======================================================================

# Code Quality: Lint with `ruff check` and auto-fix where possible
[group('code quality')]
lint:
  @just _log_start lint
  @just _cache_dirs
  {{RUFF}} check --cache-dir {{RUFF_CACHE_DIR}} --fix {{PY_SRC}} {{PY_TESTPATH}} 
  @just _log_end lint

# Code Quality: Check for linting violations with `ruff check` without modifying files
[group('code quality')]
lint-no-fix:
  @just _log_start lint-no-fix
  @just _cache_dirs
  {{RUFF}} check --cache-dir {{RUFF_CACHE_DIR}} --no-fix {{PY_SRC}} {{PY_TESTPATH}}
  @just _log_end lint-no-fix

# Code Quality: Lint import architecture (Import Linter)
[group('code quality')]
lint-imports:
  @just _log_start lint-imports
  @bash -euo pipefail -c 'if [ ! -x {{IMPORTLINTER}} ]; then echo "[lint-imports] ERROR: lint-imports not found ({{IMPORTLINTER}}); install import-linter dev dep and run '\''just setup'\''"; exit 1; fi; set +e; output="$({{IMPORTLINTER}} --verbose --config {{IMPORTLINTER_CONFIG}} 2>&1)"; status=$?; set -e; if [ "$status" -ne 0 ]; then echo "[lint-imports] FAILED"; echo; echo "$output"; exit "$status"; else echo "[lint-imports] no import-linter contract violations detected."; fi'
  @just _log_end lint-imports

# Code Quality: Format with `ruff format` and auto-fix where possible
[group('code quality')]
format:
  @just _log_start format
  @just _cache_dirs
  {{RUFF}} format --cache-dir {{RUFF_CACHE_DIR}} {{PY_SRC}} {{PY_TESTPATH}} 
  @just _log_end format

# Code Quality: Check for formatting violations with `ruff format` without modifying files
[group('code quality')]
format-no-fix:
  @just _log_start format-no-fix
  @just _cache_dirs
  {{RUFF}} format --cache-dir {{RUFF_CACHE_DIR}} --check {{PY_SRC}} {{PY_TESTPATH}}
  @just _log_end format-no-fix

# Code Quality: Typecheck with `ty` (if available)
[group('code quality')]
typecheck:
  @just _log_start typecheck
  @bash -euo pipefail -c '\
    if [ -x {{TY}} ]; then \
      {{TY}} check {{PY_SRC}} {{PY_TESTPATH}}; \
      exit 0; \
    fi; \
    if [ "{{MODE}}" = "ci" ]; then \
      echo "[typecheck] ERROR: ty not found ({{TY}}) and MODE=ci requires typechecking"; \
      exit 1; \
    fi; \
    echo "[typecheck] skipping: ty not found ({{TY}}) (MODE={{MODE}})"; \
  '
  @just _log_end typecheck

# Compatibility alias for callers that use `typechecking`
[group('code quality')]
typechecking:
  @just typecheck

# Code Quality: dead-code scan
[group('code quality')]
dead-code:
  @just _log_start dead-code
  {{VULTURE}} {{PY_SRC}} {{PY_TESTPATH}} 
  @just _log_end dead-code

# Code Quality: complexity report
[group('code quality')]
complexity:
  @just _log_start complexity
  {{RADON}} cc -s -a {{PY_SRC}}
  @just _log_end complexity

# Code Quality: raw metrics (optional)
[group('code quality')]
complexity-raw:
  @just _log_start complexity-raw
  {{RADON}} raw {{PY_SRC}}
  @just _log_end complexity-raw

# Code Quality: strict complexity check (fail on high-complexity blocks)
[group('code quality')]
complexity-strict MIN_COMPLEXITY="11":
  @just _log_start complexity-strict
  @bash -euo pipefail -c 'echo "[complexity-strict] Failing if any block has cyclomatic complexity >= ${MIN_COMPLEXITY}"; output="$({{RADON}} cc -s -n {{MIN_COMPLEXITY}} {{PY_SRC}} || true)"; if [ -n "$output" ]; then echo "[complexity-strict] Found blocks with complexity >= ${MIN_COMPLEXITY}:"; echo "$output"; exit 1; fi; echo "[complexity-strict] All blocks are below complexity ${MIN_COMPLEXITY}."'
  @just _log_end complexity-strict

# Code Quality: duplication detection
[group('code quality')]
dup:
  @just _log_start dup
  {{JSCPD}} --pattern "{{PY_SRC}}/*/*.py" --pattern "{{PY_SRC}}/*/*/*.py" --pattern "{{PY_SRC}}/*/*/*/*.py" --pattern "{{PY_TESTPATH}}/*/*.py" --pattern "{{PY_TESTPATH}}/*/*/*.py" --pattern "{{PY_TESTPATH}}/*/*/*/*.py" --reporters console
  @just _log_end dup


# ======================================================================
# Security / supply chain
# ======================================================================

# Security: Secret scan with trufflehog (report-only; does not fail if tool missing)
[group('security')]
sec-secrets:
  @just _log_start sec-secrets
  @bash -euo pipefail -c 'if command -v trufflehog >/dev/null 2>&1; then tmp_file=$(mktemp); printf ".venv\nbuild\ndist\n" > "$tmp_file"; trufflehog filesystem . --exclude-paths "$tmp_file"; rm -f "$tmp_file"; else echo "[sec-secrets] skipping: trufflehog not found on PATH"; fi'
  @just _log_end sec-secrets

# Security: Dependency scan with pip-audit
[group('security')]
sec-deps:
  @just _log_start sec-deps
  @bash -euo pipefail -c 'if [ -x .venv/bin/pip-audit ]; then PIP_NO_CACHE_DIR=1 .venv/bin/pip-audit; else echo "[sec-deps] ERROR: .venv/bin/pip-audit not found; run '\''just setup'\'' to install dev deps"; exit 1; fi'
  @just _log_end sec-deps


# ======================================================================
# Testing
# ======================================================================


_test-strict:
  {{PYTEST}} "{{ROOT_DIR}}/tests"

# Testing: Run tests and fail if any test fails
[group('testing')]
test-strict *parts:
  @just _log_start test-strict
  @just _test-strict {{parts}}
  @just _log_end test-strict

# Testing: Run tests but do not fail on test failure
[group('testing')]
test *parts:
  @just _log_start test-strict
  @just _test-strict {{parts}} || true
  @just _log_end test-strict


# ======================================================================
# Test Quality
# ======================================================================

# Test Quality: Summarize coverage results from last test execution
[group('test quality')]
cov:
  @just _log_start cov
  @bash -euo pipefail -c 'if [ -x {{SHOWCOV}} ]; then {{SHOWCOV}} report --summary --no-lines --no-branches; else echo "[cov-lines] skipping: showcov ({{SHOWCOV}}) not found"; fi'
  @just _log_end cov

# Test Quality: List lines not covered by last test execution
[group('test quality')]
cov-lines:
  @just _log_start cov-lines
  @bash -euo pipefail -c 'if [ -x {{SHOWCOV}} ]; then {{SHOWCOV}} report --lines --code --context 2 ; else echo "[cov-lines] skipping: showcov ({{SHOWCOV}}) not found"; fi'
  @just _log_end cov-lines


# ======================================================================
# Documentation
# ======================================================================

# Documentation: Build documentation using `mkdocs`
[group('documentation')]
build-docs:
  @just _log_start build-docs
  @bash -euo pipefail -c 'if [ -x {{MKDOCS}} ]; then {{MKDOCS}} build; else echo "[build-docs] skipping: mkdocs not found ({{MKDOCS}} or on PATH)"; fi'
  @just _log_end build-docs

# Documentation: Serve the documentation site locally
[group('documentation')]
docs:
  @just _log_start docs
  @just build-docs
  @bash -euo pipefail -c 'if [ -x {{MKDOCS}} ]; then python3 -m webbrowser http://127.0.0.1:8000; {{MKDOCS}} serve --livereload; else echo "[docs] skipping: mkdocs not found ({{MKDOCS}} or on PATH)"; fi'
  @just _log_end docs


# ======================================================================
# Build, packaging, publishing
# ======================================================================

# Production: Build Python artifacts with `uv build`
[group('production')]
build:
  @just _log_start build
  {{UV}} build
  @just _log_end build

# Production: Publish to PyPI using `uv publish`
[group('production')]
publish:
  @just _log_start publish
  {{UV}} publish
  @just _log_end publish


# ======================================================================
# Cleaning / maintenance
# ======================================================================

# Cleaning: Remove caches/build artifacts and prune uv cache
[group('cleaning')]
clean:
  @just _log_start clean
  find . -name '__pycache__' -type d -prune -exec rm -rf '{}' +
  rm -rf .ruff_cache .pytest_cache .mypy_cache .pytype
  rm -rf .coverage .coverage.* coverage.xml htmlcov
  rm -rf dist build
  rm -rf logs
  rm -rf .hypothesis .ropeproject .wily mutants
  {{UV}} cache prune
  @just _log_end clean

# Cleaning: Stash untracked (non-ignored) files (used by `scour`)
[group('cleaning')]
stash-untracked:
  @just _log_start stash-untracked
  @bash -euo pipefail -c 'if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then msg="scour:untracked:$(date -u +%Y%m%dT%H%M%SZ)"; if git ls-files --others --exclude-standard --directory --no-empty-directory | grep -q .; then git ls-files --others --exclude-standard -z | xargs -0 git stash push -m "$msg" -- >/dev/null; echo "Stashed untracked (non-ignored) files as: $msg"; else echo "No untracked (non-ignored) paths to stash."; fi; else echo "[stash-untracked] not a git repository; skipping"; fi'
  @just _log_end stash-untracked

# Cleaning: Remove git-ignored files/dirs while keeping .venv
[group('cleaning')]
scour:
  @just _log_start scour
  @just clean
  @just stash-untracked
  @bash -euo pipefail -c 'if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then git clean -fXd -e .venv; else echo "[scour] not a git repository; skipping git clean"; fi'
  @just _log_end scour


# ======================================================================
# Composite flows
# ======================================================================

# Convenience: setup, lint, format, typecheck, build-docs, test, cov
[group('convenience')]
fix:
  @just _log_start fix
  @just _run_soft setup "just setup"
  @just _run_soft lint "just lint"
  @just _run_soft format "just format"
  @just _run_soft typecheck 'just typecheck'
  @just _run_soft lint-imports 'just lint-imports'
  # @just _run_soft build-docs "just build-docs"
  @just test
  @just cov
  @just _log_end fix

# Convenience: lint-no-fx, format-no-fix, typecheck, lint-imports, test, cov
check:
  @just _log_start check
  @just _run_soft lint-no-fix "just lint-no-fix"
  @just _run_soft format-no-fix "just format-no-fix"
  @just _run_soft typecheck 'just typecheck'
  @just _run_soft lint-imports 'just lint-imports'
  @just test
  # @just _run metrics-gate 'just metrics-gate'
  @just cov
  # @just _run sec-deps 'just sec-deps'
  @just _log_end check
