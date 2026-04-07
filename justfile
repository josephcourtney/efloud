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
# pytest options
# ======================================================================
PYTEST_DEV_WORKERS := env("PYTEST_DEV_WORKERS", "auto")
PYTEST_DEV_DIST    := env("PYTEST_DEV_DIST", "loadscope")

# Shared option bundles
PYTEST_QUIET_OPTS    := "-q --tb=short -r fE --show-capture=no -o log_cli=false"
PYTEST_DEBUG_OPTS    := "-vv --tb=long -l --show-capture=all -o log_cli=true"
PYTEST_LOG_OPTS      := "-q --tb=short -r fE --show-capture=no -o log_cli=true --log-cli-level=INFO"
PYTEST_FAST_EXPR     := "-m 'not slow'"
PYTEST_FAILING_OPTS  := "--lf"

PYTEST_DEV_THRESHOLD := env("PYTEST_DEV_THRESHOLD", "80")
PYTEST_DEV_BASE_OPTS := "--testmon --no-cov"
PYTEST_DEV_XDIST_OPTS := "-n '" + PYTEST_DEV_WORKERS + "' --dist '" + PYTEST_DEV_DIST + "'"


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
# Runner (brief on success, verbose on failure)
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

# "soft" runner: brief on success, verbose on failure, does not crash if a recipe returns non-zero
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

# refresh .venv via `uv sync`
setup:
  @just _log_start setup
  @just _cache_dirs
  @bash -euo pipefail -c '\
    {{UV}} sync; \
  '
  @just _log_end setup


# ======================================================================
# lint / format / type-check
# ======================================================================

# Lint with `ruff check` and auto-fix where possible; use --no-fix to check only.
[group('code quality')]
[arg("no_fix", long, value="true")]
lint no_fix="false":
  @just _log_start lint
  @just _cache_dirs
  @bash -euo pipefail -c '\
    args=("{{RUFF}}" check --cache-dir "{{RUFF_CACHE_DIR}}"); \
    if [ "{{no_fix}}" = "true" ]; then \
      args+=(--no-fix); \
    else \
      args+=(--fix); \
    fi; \
    args+=({{PY_SRC}} {{PY_TESTPATH}}); \
    "${args[@]}" \
  '
  @just _log_end lint

# Lint import architecture (Import Linter)
[group('code quality')]
lint-imports:
  @just _log_start lint-imports
  @bash -euo pipefail -c 'if [ ! -x {{IMPORTLINTER}} ]; then echo "[lint-imports] ERROR: lint-imports not found ({{IMPORTLINTER}}); install import-linter dev dep and run '\''just setup'\''"; exit 1; fi; set +e; output="$({{IMPORTLINTER}} --verbose --config {{IMPORTLINTER_CONFIG}} 2>&1)"; status=$?; set -e; if [ "$status" -ne 0 ]; then echo "[lint-imports] FAILED"; echo; echo "$output"; exit "$status"; else echo "[lint-imports] no import-linter contract violations detected."; fi'
  @just _log_end lint-imports

# Format with `ruff format` and auto-fix where possible; use --check to verify formatting only.
[group('code quality')]
[arg("check", long, value="true")]
format check="false":
  @just _log_start format
  @just _cache_dirs
  @bash -euo pipefail -c '\
    args=("{{RUFF}}" format --cache-dir "{{RUFF_CACHE_DIR}}"); \
    if [ "{{check}}" = "true" ]; then \
      args+=(--check); \
    fi; \
    args+=({{PY_SRC}} {{PY_TESTPATH}}); \
    "${args[@]}" \
  '
  @just _log_end format

# Typecheck with `ty`
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

# dead-code scan
[group('code quality')]
dead-code:
  @just _log_start dead-code
  {{VULTURE}} --min-confidence 61 {{PY_SRC}} {{PY_TESTPATH}} 
  @just _log_end dead-code

# Generate complexity report; use --raw for raw metrics or --strict to fail above threshold.
[group('code quality')]
[arg("raw", long, value="true")]
[arg("strict", long, value="true")]
complexity raw="false" strict="false" MIN_COMPLEXITY="11":
  @just _log_start complexity
  @bash -euo pipefail -c '\
    if [ "{{raw}}" = "true" ] && [ "{{strict}}" = "true" ]; then \
      echo "[complexity] ERROR: choose at most one of --raw or --strict" >&2; \
      exit 2; \
    fi; \
    if [ "{{raw}}" = "true" ]; then \
      "{{RADON}}" raw {{PY_SRC}}; \
    elif [ "{{strict}}" = "true" ]; then \
      echo "[complexity] Failing if any block has cyclomatic complexity >= {{MIN_COMPLEXITY}}"; \
      output="$("{{RADON}}" cc -s -n {{MIN_COMPLEXITY}} {{PY_SRC}} || true)"; \
      if [ -n "$output" ]; then \
        echo "[complexity] Found blocks with complexity >= {{MIN_COMPLEXITY}}:"; \
        echo "$output"; \
        exit 1; \
      fi; \
      echo "[complexity] All blocks are below complexity {{MIN_COMPLEXITY}}."; \
    else \
      "{{RADON}}" cc -s -a {{PY_SRC}}; \
    fi \
  '
  @just _log_end complexity

# duplication detection
[group('code quality')]
dup:
  @just _log_start dup
  {{JSCPD}} --pattern "{{PY_SRC}}/*/*.py" --pattern "{{PY_SRC}}/*/*/*.py" --pattern "{{PY_SRC}}/*/*/*/*.py" --pattern "{{PY_TESTPATH}}/*/*.py" --pattern "{{PY_TESTPATH}}/*/*/*.py" --pattern "{{PY_TESTPATH}}/*/*/*/*.py" --reporters console
  @just _log_end dup


# ======================================================================
# Security / supply chain
# ======================================================================

# Secret scan with trufflehog (report-only; does not fail if tool missing)
[group('security')]
sec-secrets:
  @just _log_start sec-secrets
  @bash -euo pipefail -c 'if command -v trufflehog >/dev/null 2>&1; then tmp_file=$(mktemp); printf ".venv\nbuild\ndist\n" > "$tmp_file"; trufflehog filesystem . --exclude-paths "$tmp_file"; rm -f "$tmp_file"; else echo "[sec-secrets] skipping: trufflehog not found on PATH"; fi'
  @just _log_end sec-secrets

# Dependency scan with pip-audit
[group('security')]
sec-deps:
  @just _log_start sec-deps
  @bash -euo pipefail -c 'if [ -x .venv/bin/pip-audit ]; then PIP_NO_CACHE_DIR=1 .venv/bin/pip-audit; else echo "[sec-deps] ERROR: .venv/bin/pip-audit not found; run '\''just setup'\'' to install dev deps"; exit 1; fi'
  @just _log_end sec-deps


# ======================================================================
# Testing
# ======================================================================

# Run tests
[group('testing')]
[arg("strict", long, value="true")]
[arg("fast",   long, value="true")]
[arg("failing",   long, value="true")]
[arg("dev",    long, value="true")]
[arg("quiet",  long, value="quiet")]
[arg("logs",   long, value="logs")]
[arg("debug",  long, value="debug")]
[doc("""
Run test suite
  *selection  which tests to run. can be any of the package suffixes ('cli, cs, ...') or omitted to run all test suites.
  --strict    stop just execution if there are test failures
  --fast      skip tests marked slow
  --failing   only run tests that failed last time it ran
  --dev       enable xdist + testmon for faster iteration
  --quiet     produce minimal output
  --logs      show live logs with otherwise compact output
  --debug     enable verbose output

""")]
test strict="true" fast="false" dev="false" quiet="" logs="" debug="" failing="false" *selection:
  #!/usr/bin/env bash
  set -euo pipefail

  mode_count=0
  [ -n "{{quiet}}" ] && mode_count=$((mode_count + 1))
  [ -n "{{logs}}" ]  && mode_count=$((mode_count + 1))
  [ -n "{{debug}}" ] && mode_count=$((mode_count + 1))

  if [ "$mode_count" -gt 1 ]; then
    echo "[test] ERROR: choose at most one of --quiet, --logs, or --debug" >&2
    exit 2
  fi

  mode="default"
  if [ -n "{{quiet}}" ]; then mode="quiet"; fi
  if [ -n "{{logs}}"  ]; then mode="logs"; fi
  if [ -n "{{debug}}" ]; then mode="debug"; fi

  case "$mode" in
    default) mode_flags="" ;;
    quiet)   mode_flags='{{PYTEST_QUIET_OPTS}}' ;;
    logs)    mode_flags='{{PYTEST_LOG_OPTS}}' ;;
    debug)   mode_flags='{{PYTEST_DEBUG_OPTS}}' ;;
  esac

  extra_flags=()
  if [ "{{fast}}" = "true" ]; then
    extra_flags+=({{PYTEST_FAST_EXPR}})
  fi
  if [ "{{failing}}" = "true" ]; then
    extra_flags+=({{PYTEST_FAILING_OPTS}})
  fi

  args=("{{PYTEST}}")
  if [ -n "$mode_flags" ]; then
    eval "args+=($mode_flags)"
  fi
  args+=("${extra_flags[@]}")

  test_paths=("{{ROOT_DIR}}/tests")

  args=("{{PYTEST}}")
  if [ -n "$mode_flags" ]; then
    eval "args+=($mode_flags)"
  fi
  args+=("${extra_flags[@]}")

  if [ "{{dev}}" = "true" ]; then
    # Always use the non-xdist dev flags.
    eval "args+=({{PYTEST_DEV_BASE_OPTS}})"

    # Count the tests that this exact selection would collect.
    collect_args=("{{PYTEST}}" "--collect-only" "-q")
    collect_args+=("${extra_flags[@]}")
    collect_args+=("${test_paths[@]}")

    set +e
    collect_out="$("${collect_args[@]}" 2>&1)"
    collect_status=$?
    set -e

    # If collection itself failed, surface that failure and stop.
    if [ "$collect_status" -ne 0 ] && [ "$collect_status" -ne 5 ]; then
      echo "[test] collection failed while deciding whether to use xdist" >&2
      echo "$collect_out" >&2
      exit "$collect_status"
    fi

    # Count nodeids from -q --collect-only output.
    test_count="$(printf '%s\n' "$collect_out" | grep -c '::' || true)"
    threshold="{{PYTEST_DEV_THRESHOLD}}"

    if [ "${test_count:-0}" -ge "$threshold" ]; then
      eval "args+=({{PYTEST_DEV_XDIST_OPTS}})"
    fi
  fi

  args+=("${test_paths[@]}")

  set +e
  echo "${args[@]}"
  "${args[@]}"
  status=$?
  set -e

  if [ "{{strict}}" = "true" ]; then
    exit "$status"
  fi



# ======================================================================
# Test Quality
# ======================================================================

# Show coverage results; use --lines for uncovered-line detail.
[group('test quality')]
[arg("lines", long, value="true")]
cov lines="false":
  @just _log_start cov
  @bash -euo pipefail -c '\
    if [ -x {{SHOWCOV}} ]; then \
      if [ "{{lines}}" = "true" ]; then \
        {{SHOWCOV}} report --lines --code --context 2; \
      else \
        {{SHOWCOV}} report --summary --no-lines --no-branches; \
      fi; \
    else \
      echo "[cov] skipping: showcov ({{SHOWCOV}}) not found"; \
    fi \
  '
  @just _log_end cov


# ======================================================================
# Documentation
# ======================================================================

# Build docs; use --serve to launch the local server.
[group('documentation')]
[arg("serve", long, value="true")]
docs serve="false":
  @just _log_start docs
  @bash -euo pipefail -c '\
    if [ -x {{MKDOCS}} ]; then \
      if [ "{{serve}}" = "true" ]; then \
        python3 -m webbrowser http://127.0.0.1:8000; \
        {{MKDOCS}} serve --livereload; \
      else \
        {{MKDOCS}} build; \
      fi; \
    else \
      echo "[docs] skipping: mkdocs not found ({{MKDOCS}} or on PATH)"; \
    fi \
  '
  @just _log_end docs


# ======================================================================
# Build, packaging, publishing
# ======================================================================

# Build Python artifacts with `uv build`
[group('production')]
build:
  @just _log_start build
  {{UV}} build
  @just _log_end build

# Publish to PyPI using `uv publish`
[group('production')]
publish:
  @just _log_start publish
  {{UV}} publish
  @just _log_end publish


# ======================================================================
# Cleaning / maintenance
# ======================================================================

# Remove caches/build artifacts
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

# Stash untracked (non-ignored) files (used by `scour`)
[group('cleaning')]
stash-untracked:
  @just _log_start stash-untracked
  @bash -euo pipefail -c '\
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
      msg="scour:untracked:$(date -u +%Y%m%dT%H%M%SZ)"; \
      if git ls-files --others --exclude-standard --directory --no-empty-directory | grep -q .; then \
        git ls-files --others --exclude-standard -z | xargs -0 git stash push -m "$msg" -- >/dev/null; \
        echo "Stashed untracked (non-ignored) files as: $msg"; \
      else \
        echo "No untracked (non-ignored) paths to stash."; \
      fi; \
    else \
      echo "[stash-untracked] not a git repository; skipping"; \
    fi
  '
  @just _log_end stash-untracked

# Remove git-ignored files/dirs while keeping .venv
[group('cleaning')]
scour:
  @just _log_start scour
  @just clean
  @just stash-untracked
  @bash -euo pipefail -c '\
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
      git clean -fXd -e .venv; \
    else \
      echo "[scour] not a git repository; skipping git clean"; \
    fi
  '
  @just _log_end scour


# ======================================================================
# Composite flows
# ======================================================================

# Run setup, lint, format, typecheck, imports, fast tests, and coverage.
[group('convenience')]
fix:
  @just _log_start fix
  @just _run_soft setup "just setup"
  @just _run_soft lint "just lint"
  @just _run_soft format "just format"
  @just _run_soft typecheck 'just typecheck'
  @just _run_soft lint-imports 'just lint-imports'
  # @just _run_soft docs "just docs"
  @just test --fast
  @just cov
  @just _log_end fix

# Run checks: lint, format, typecheck, imports, tests, and coverage.
check:
  @just _log_start check
  @just _run_soft lint "just lint --no-fix"
  @just _run_soft format "just format --check"
  @just _run_soft typecheck 'just typecheck'
  @just _run_soft lint-imports 'just lint-imports'
  @just test
  # @just _run metrics-gate 'just metrics-gate'
  @just cov
  # @just _run sec-deps 'just sec-deps'
  @just _log_end check
