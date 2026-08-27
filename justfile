# ======================================================================
# Global shell + environment
# ======================================================================

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := true
set export := true


# ======================================================================
# Configuration
# ======================================================================

MODE           := env("MODE", "dev")  # dev | debug | ci
ROOT_DIR       := justfile_directory()
PACKAGE        := file_stem(ROOT_DIR)
PYTHON_PACKAGE := env("PYTHON_PACKAGE", "efloud")
VERBOSE        := env("VERBOSE", "0")

REPO_CACHE_DIR := ROOT_DIR + "/.cache"
UV_CACHE_DIR   := REPO_CACHE_DIR + "/uv"
RUFF_CACHE_DIR := REPO_CACHE_DIR + "/ruff"

PY_SRC      := "src"
PY_TESTPATH := "tests"


# ======================================================================
# Tool wrappers
# ======================================================================

UV                  := "uv --cache-dir " + UV_CACHE_DIR
RUFF                := ROOT_DIR + "/.venv/bin/ruff"
PYTEST              := ROOT_DIR + "/.venv/bin/pytest"
TY                  := ROOT_DIR + "/.venv/bin/ty"
SHOWCOV             := ROOT_DIR + "/.venv/bin/showcov"
MKDOCS              := ROOT_DIR + "/.venv/bin/mkdocs"
VULTURE             := ROOT_DIR + "/.venv/bin/vulture"
RADON                := ROOT_DIR + "/.venv/bin/radon"
IMPORTLINTER        := ROOT_DIR + "/.venv/bin/lint-imports"
IMPORTLINTER_CONFIG := ROOT_DIR + "/import-linter.toml"

JSCPD := "npx --yes jscpd@4.0"


# ======================================================================
# pytest options
# ======================================================================

PYTEST_DEV_WORKERS := env("PYTEST_DEV_WORKERS", "auto")
PYTEST_DEV_DIST    := env("PYTEST_DEV_DIST", "loadscope")
PYTEST_DEV_THRESHOLD := env("PYTEST_DEV_THRESHOLD", "80")

PYTEST_TIMEOUT := env("PYTEST_TIMEOUT", "300")

PYTEST_BASE_OPTS := "--timeout=" + PYTEST_TIMEOUT + " --cov=" + PYTHON_PACKAGE

PYTEST_QUIET_OPTS := "-q --tb=short -r fE --show-capture=no -o log_cli=false"

PYTEST_DEBUG_OPTS := "-vv --tb=long -l --show-capture=all -o log_cli=true"

PYTEST_LOG_OPTS := "-q --tb=short -r fE --show-capture=no -o log_cli=true --log-cli-level=INFO"

PYTEST_FAST_OPTS := "-m 'not slow' --durations=25 --durations-min=0.1 --timeout=30"

PYTEST_FAILING_OPTS := "--lf"

# testmon is useful for development iteration but incompatible with useful
# whole-suite coverage, so development mode explicitly disables coverage.
PYTEST_DEV_BASE_OPTS := "--testmon --no-cov"

PYTEST_DEV_XDIST_OPTS := "-n '" + PYTEST_DEV_WORKERS + "' --dist '" + PYTEST_DEV_DIST + "'"


# ======================================================================
# Meta / defaults
# ======================================================================

[private]
default: help


# List available recipes; also the default entry point.
help:
  @just _log_start help
  @just --list --unsorted --list-prefix "  "
  @just _log_end help


# Print resolved runtime configuration.
env:
  @just _log_start env
  @echo "MODE={{MODE}}"
  @echo "PACKAGE={{PACKAGE}}"
  @echo "PYTHON_PACKAGE={{PYTHON_PACKAGE}}"
  @echo "PY_SRC={{PY_SRC}}"
  @echo "PY_TESTPATH={{PY_TESTPATH}}"
  @echo "UV={{UV}}"
  @echo "RUFF={{RUFF}}"
  @echo "PYTEST={{PYTEST}}"
  @echo "TY={{TY}}"
  @echo "SHOWCOV={{SHOWCOV}}"
  @echo "MKDOCS={{MKDOCS}}"
  @echo "VULTURE={{VULTURE}}"
  @echo "RADON={{RADON}}"
  @echo "IMPORTLINTER={{IMPORTLINTER}}"
  @echo "JSCPD={{JSCPD}}"
  @{{UV}} --version || true
  @{{PYTEST}} --version || true
  @{{RUFF}} --version || true
  @just _log_end env


# ======================================================================
# Logging / command runners
# ======================================================================

[private]
_log_start NAME:
  @bash -euo pipefail -c '\
    if [ "{{VERBOSE}}" != "0" ]; then \
      printf "\n=== START: %s ===\n" "{{NAME}}"; \
    fi \
  '


[private]
_log_end NAME:
  @bash -euo pipefail -c '\
    if [ "{{VERBOSE}}" != "0" ]; then \
      printf "=== END: %s ===\n\n" "{{NAME}}"; \
    fi \
  '


[private]
_cache_dirs:
  @mkdir -p {{REPO_CACHE_DIR}} {{UV_CACHE_DIR}} {{RUFF_CACHE_DIR}}


# Run a command quietly on success and print its captured output on failure.
[private]
_run NAME CMD:
  @bash -euo pipefail -c '\
    name="$1"; \
    cmd="$2"; \
    set +e; \
    out="$(bash -c "$cmd" 2>&1)"; \
    status=$?; \
    set -e; \
    if [ "$status" -eq 0 ]; then \
      printf "\033[1;32m✓ %s\033[0m\n" "$name"; \
    else \
      printf "\033[1;31m✗ %s\033[0m\n" "$name"; \
      printf "%s\n" "$out"; \
      exit "$status"; \
    fi \
  ' -- "{{NAME}}" {{quote(CMD)}}


# Like `_run`, but continue after a failure.
# Intended for best-effort fixing workflows, never validation gates.
[private]
_run_soft NAME CMD:
  @bash -euo pipefail -c '\
    name="$1"; \
    cmd="$2"; \
    set +e; \
    out="$(bash -c "$cmd" 2>&1)"; \
    status=$?; \
    set -e; \
    if [ "$status" -eq 0 ]; then \
      printf "\033[1;32m✓ %s\033[0m\n" "$name"; \
    else \
      printf "\033[1;31m✗ %s\033[0m\n" "$name"; \
      printf "%s\n" "$out"; \
      printf "\033[1;33m[warn]\033[0m continuing after failure in %s\n" "$name" >&2; \
    fi \
  ' -- "{{NAME}}" {{quote(CMD)}}


# ======================================================================
# Bootstrap
# ======================================================================

[group('bootstrap')]
setup:
  @just _log_start setup
  @just _cache_dirs
  {{UV}} sync
  @just _log_end setup


# ======================================================================
# Code quality
# ======================================================================

# Lint with Ruff. By default fixes safe violations; use --no-fix for validation.
[group('code quality')]
[arg("no-fix", long, value="true")]
lint no-fix="false":
  @just _log_start lint
  @just _cache_dirs
  @bash -euo pipefail -c '\
    args=("{{RUFF}}" check --cache-dir "{{RUFF_CACHE_DIR}}"); \
    if [ "{{no-fix}}" = "true" ]; then \
      args+=(--no-fix); \
    else \
      args+=(--fix); \
    fi; \
    args+=("{{PY_SRC}}" "{{PY_TESTPATH}}"); \
    "${args[@]}" \
  '
  @just _log_end lint


# Format with Ruff. Use --check for non-mutating validation.
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
    args+=("{{PY_SRC}}" "{{PY_TESTPATH}}"); \
    "${args[@]}" \
  '
  @just _log_end format


# Validate import architecture.
[group('code quality')]
lint-imports:
  @just _log_start lint-imports
  @bash -euo pipefail -c '\
    if [ ! -x "{{IMPORTLINTER}}" ]; then \
      echo "[lint-imports] ERROR: lint-imports not found at {{IMPORTLINTER}}" >&2; \
      echo "[lint-imports] run: just setup" >&2; \
      exit 1; \
    fi; \
    "{{IMPORTLINTER}}" --verbose --config "{{IMPORTLINTER_CONFIG}}" \
  '
  @just _log_end lint-imports


# Static type checking.
#
# Outside CI this remains tolerant of an absent `ty` executable so the recipe
# can still be used in partially bootstrapped environments. `just check`
# explicitly runs it with MODE=ci and therefore treats absence as a failure.
[group('code quality')]
typecheck:
  @just _log_start typecheck
  @bash -euo pipefail -c '\
    if [ -x "{{TY}}" ]; then \
      "{{TY}}" check "{{PY_SRC}}" "{{PY_TESTPATH}}"; \
      exit 0; \
    fi; \
    if [ "{{MODE}}" = "ci" ]; then \
      echo "[typecheck] ERROR: ty not found at {{TY}}" >&2; \
      echo "[typecheck] run: just setup" >&2; \
      exit 1; \
    fi; \
    echo "[typecheck] skipping: ty not found (MODE={{MODE}})" \
  '
  @just _log_end typecheck


# Scan for likely dead code.
[group('code quality')]
dead-code:
  @just _log_start dead-code
  {{VULTURE}} --min-confidence 61 {{PY_SRC}} {{PY_TESTPATH}}
  @just _log_end dead-code


# Report complexity; use --raw for raw metrics or --strict to enforce a ceiling.
[group('code quality')]
[arg("raw", long, value="true")]
[arg("strict", long, value="true")]
complexity raw="false" strict="false" min_complexity="11":
  @just _log_start complexity
  @bash -euo pipefail -c '\
    if [ "{{raw}}" = "true" ] && [ "{{strict}}" = "true" ]; then \
      echo "[complexity] ERROR: choose at most one of --raw or --strict" >&2; \
      exit 2; \
    fi; \
    if [ "{{raw}}" = "true" ]; then \
      "{{RADON}}" raw "{{PY_SRC}}"; \
    elif [ "{{strict}}" = "true" ]; then \
      echo "[complexity] failing if any block has complexity >= {{min_complexity}}"; \
      output="$("{{RADON}}" cc -s -n "{{min_complexity}}" "{{PY_SRC}}" || true)"; \
      if [ -n "$output" ]; then \
        echo "$output"; \
        exit 1; \
      fi; \
      echo "[complexity] all blocks are below {{min_complexity}}"; \
    else \
      "{{RADON}}" cc -s -a "{{PY_SRC}}"; \
    fi \
  '
  @just _log_end complexity


# Detect duplicated source/test code.
[group('code quality')]
dup:
  @just _log_start dup
  {{JSCPD}} \
    --pattern "{{PY_SRC}}/*/*.py" \
    --pattern "{{PY_SRC}}/*/*/*.py" \
    --pattern "{{PY_SRC}}/*/*/*/*.py" \
    --pattern "{{PY_TESTPATH}}/*.py" \
    --pattern "{{PY_TESTPATH}}/*/*.py" \
    --pattern "{{PY_TESTPATH}}/*/*/*.py" \
    --pattern "{{PY_TESTPATH}}/*/*/*/*.py" \
    --reporters console
  @just _log_end dup


# ======================================================================
# Security / supply chain
# ======================================================================

# Secret scan. Report-only when TruffleHog is not installed.
[group('security')]
sec-secrets:
  @just _log_start sec-secrets
  @bash -euo pipefail -c '\
    if command -v trufflehog >/dev/null 2>&1; then \
      tmp_file="$(mktemp)"; \
      trap '\''rm -f "$tmp_file"'\'' EXIT; \
      printf ".venv\n.cache\nbuild\ndist\n" > "$tmp_file"; \
      trufflehog filesystem . --exclude-paths "$tmp_file"; \
    else \
      echo "[sec-secrets] skipping: trufflehog not found on PATH"; \
    fi \
  '
  @just _log_end sec-secrets


# Audit installed dependencies.
[group('security')]
sec-deps:
  @just _log_start sec-deps
  @bash -euo pipefail -c '\
    if [ ! -x "{{ROOT_DIR}}/.venv/bin/pip-audit" ]; then \
      echo "[sec-deps] ERROR: pip-audit not found" >&2; \
      exit 1; \
    fi; \
    PIP_NO_CACHE_DIR=1 "{{ROOT_DIR}}/.venv/bin/pip-audit" \
  '
  @just _log_end sec-deps


# ======================================================================
# Testing
# ======================================================================

[group('testing')]
[arg("strict", long, value="true")]
[arg("fast", long, value="true")]
[arg("failing", long, value="true")]
[arg("dev", long, value="true")]
[arg("quiet", long, value="quiet")]
[arg("logs", long, value="logs")]
[arg("debug", long, value="debug")]
[doc("""
Run the test suite.

  --strict    propagate pytest failure (default)
  --fast      skip tests marked slow, report slow tests, and use a 30s timeout
  --failing   rerun only previously failing tests
  --dev       enable testmon and conditionally xdist for larger selections
  --quiet     compact output
  --logs      compact output with live INFO logs
  --debug     verbose output and full captured diagnostics

Use --strict=false only for explicitly best-effort development runs.
""")]
test strict="true" fast="false" dev="false" quiet="" logs="" debug="" failing="false":
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
  if [ -n "{{logs}}" ];  then mode="logs";  fi
  if [ -n "{{debug}}" ]; then mode="debug"; fi

  case "$mode" in
    default) mode_flags="" ;;
    quiet)   mode_flags='{{PYTEST_QUIET_OPTS}}' ;;
    logs)    mode_flags='{{PYTEST_LOG_OPTS}}' ;;
    debug)   mode_flags='{{PYTEST_DEBUG_OPTS}}' ;;
  esac

  extra_flags=()

  if [ "{{fast}}" = "true" ]; then
    eval "extra_flags+=({{PYTEST_FAST_OPTS}})"
  fi

  if [ "{{failing}}" = "true" ]; then
    eval "extra_flags+=({{PYTEST_FAILING_OPTS}})"
  fi

  args=("{{PYTEST}}")

  eval "args+=({{PYTEST_BASE_OPTS}})"

  if [ -n "$mode_flags" ]; then
    eval "args+=($mode_flags)"
  fi

  args+=("${extra_flags[@]}")

  test_paths=("{{ROOT_DIR}}/{{PY_TESTPATH}}")

  if [ "{{dev}}" = "true" ]; then
    # testmon disables coverage for rapid local iteration.
    eval "args+=({{PYTEST_DEV_BASE_OPTS}})"

    # Determine whether this selection is large enough for xdist to help.
    # Explicitly disable coverage during collection to avoid paying for it
    # merely to count tests.
    collect_args=(
      "{{PYTEST}}"
      "--collect-only"
      "-q"
      "--no-cov"
    )

    collect_args+=("${extra_flags[@]}")
    collect_args+=("${test_paths[@]}")

    set +e
    collect_out="$("${collect_args[@]}" 2>&1)"
    collect_status=$?
    set -e

    # pytest exit code 5 means the selection collected no tests.
    if [ "$collect_status" -ne 0 ] && [ "$collect_status" -ne 5 ]; then
      echo "[test] collection failed while deciding whether to use xdist" >&2
      echo "$collect_out" >&2
      exit "$collect_status"
    fi

    test_count="$(printf '%s\n' "$collect_out" | grep -c '::' || true)"
    threshold="{{PYTEST_DEV_THRESHOLD}}"

    if [ "${test_count:-0}" -ge "$threshold" ]; then
      eval "args+=({{PYTEST_DEV_XDIST_OPTS}})"
    fi
  fi

  args+=("${test_paths[@]}")

  printf '[test]'
  printf ' %q' "${args[@]}"
  printf '\n'

  set +e
  "${args[@]}"
  status=$?
  set -e

  if [ "{{strict}}" = "true" ]; then
    exit "$status"
  fi

  if [ "$status" -ne 0 ]; then
    echo "[test] WARNING: pytest exited with status $status (--strict=false)" >&2
  fi

  exit 0


# ======================================================================
# Test quality
# ======================================================================

# Report coverage from the most recent coverage-producing test run.
[group('test quality')]
[arg("lines", long, value="true")]
cov lines="false":
  @just _log_start cov
  @bash -euo pipefail -c '\
    if [ ! -x "{{SHOWCOV}}" ]; then \
      echo "[cov] ERROR: showcov not found at {{SHOWCOV}}" >&2; \
      echo "[cov] run: just setup" >&2; \
      exit 1; \
    fi; \
    if [ "{{lines}}" = "true" ]; then \
      "{{SHOWCOV}}" report --lines --code --context 2; \
    else \
      "{{SHOWCOV}}" report --summary --no-lines --no-branches; \
    fi \
  '
  @just _log_end cov


# ======================================================================
# Documentation
# ======================================================================

# Build docs by default; use --serve for a local development server.
# Documentation remains optional: repositories without MkDocs installed can
# still use the rest of this shared justfile.
[group('documentation')]
[arg("serve", long, value="true")]
docs serve="false":
  @just _log_start docs
  @bash -euo pipefail -c '\
    if [ ! -x "{{MKDOCS}}" ]; then \
      echo "[docs] skipping: mkdocs not installed"; \
      exit 0; \
    fi; \
    if [ "{{serve}}" = "true" ]; then \
      python3 -m webbrowser http://127.0.0.1:8000; \
      "{{MKDOCS}}" serve --livereload; \
    else \
      "{{MKDOCS}}" build; \
    fi \
  '
  @just _log_end docs


# ======================================================================
# Build / packaging / publishing
# ======================================================================

# Build source and wheel distributions.
[group('production')]
build:
  @just _log_start build
  {{UV}} build
  @just _log_end build


# Build without applying local [tool.uv.sources] overrides.
# This is the appropriate artifact build for release validation.
[group('production')]
build-release:
  @just _log_start build-release
  {{UV}} build --no-sources
  @just _log_end build-release


# Publish artifacts in dist/.
# Publishing is intentionally separate from validation so it is never an
# accidental consequence of another recipe.
[group('production')]
publish:
  @just _log_start publish
  {{UV}} publish
  @just _log_end publish


# ======================================================================
# Cleaning / maintenance
# ======================================================================

# Remove generated repository state while preserving the virtual environment.
[group('cleaning')]
clean:
  @just _log_start clean

  # Avoid traversing .venv when deleting Python bytecode caches.
  find . \
    -path './.venv' -prune -o \
    -name '__pycache__' -type d -prune -exec rm -rf '{}' +

  rm -rf \
    .cache \
    .ruff_cache \
    .pytest_cache \
    .mypy_cache \
    .pytype \
    .import_linter_cache \
    .coverage \
    .coverage.* \
    coverage.xml \
    htmlcov \
    .hypothesis \
    .ropefolder \
    .ropeproject \
    .wily \
    mutants \
    dist \
    build \
    logs

  @just _log_end clean


# Stash only untracked, non-ignored files before destructive `git clean`.
[group('cleaning')]
stash-untracked:
  @just _log_start stash-untracked
  @bash -euo pipefail -c '\
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
      echo "[stash-untracked] not a git repository; skipping"; \
      exit 0; \
    fi; \
    mapfile -d "" files < <(git ls-files --others --exclude-standard -z); \
    if [ "${#files[@]}" -eq 0 ]; then \
      echo "No untracked non-ignored files to stash."; \
      exit 0; \
    fi; \
    msg="scour:untracked:$(date -u +%Y%m%dT%H%M%SZ)"; \
    git stash push -m "$msg" -- "${files[@]}" >/dev/null; \
    echo "Stashed untracked non-ignored files as: $msg" \
  '
  @just _log_end stash-untracked


# Remove ignored repository files while retaining .venv.
[group('cleaning')]
scour:
  @just _log_start scour
  @just clean
  @just stash-untracked
  @bash -euo pipefail -c '\
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
      git clean -fXd -e .venv/; \
    else \
      echo "[scour] not a git repository; skipping"; \
    fi \
  '
  @just _log_end scour


# ======================================================================
# Composite workflows
# ======================================================================

# Best-effort local repair loop.
#
# setup and tests remain strict. Mutating/static repair steps continue after
# individual failures so one problem does not hide unrelated fixable problems.
[group('convenience')]
fix:
  @just _log_start fix
  @just _run setup "just setup"
  @just _run_soft lint "just lint"
  @just _run_soft format "just format"
  @just _run_soft typecheck "just typecheck"
  @just _run_soft lint-imports "just lint-imports"
  @just test --fast
  @just cov
  @just _log_end fix


# Canonical repository validation gate.
#
# Every validation step is strict. A failing lint, format, typing,
# architecture, or test check causes this recipe to fail.
[group('convenience')]
check:
  @just _log_start check
  @just _run lint "just lint --no-fix"
  @just _run format "just format --check"
  @just _run typecheck "MODE=ci just typecheck"
  @just _run lint-imports "just lint-imports"
  @just _run test "just test"
  @just _run coverage "just cov"
  @just _log_end check


# Release preflight: validate the repository and prove that a distribution can
# be built without local uv source overrides.
[group('production')]
release-check:
  @just _log_start release-check
  @just _run check "just check"
  @just _run build-release "just build-release"
  @just _log_end release-check
