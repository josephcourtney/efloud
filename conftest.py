from __future__ import annotations

from collections import defaultdict

import pytest

FAST_CALL_BUDGET_DEFAULT = 0.25
FAST_TOTAL_BUDGET_DEFAULT = 0.50

_ENFORCE_FAST_BUDGET = False
_FAST_CALL_BUDGET = FAST_CALL_BUDGET_DEFAULT
_FAST_TOTAL_BUDGET = FAST_TOTAL_BUDGET_DEFAULT
_FAST_CALL_OFFENDERS: list[tuple[float, str]] = []
_FAST_TOTAL_OFFENDERS: list[tuple[float, str]] = []
_FAST_PHASE_DURATIONS: defaultdict[str, float] = defaultdict(float)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("fast-suite")
    group.addoption(
        "--enforce-fast-budget",
        action="store_true",
        help="Enable runtime budget checks for tests not marked slow.",
    )
    group.addoption(
        "--fast-call-budget",
        action="store",
        type=float,
        default=None,
        help="Fail if the call phase of a non-slow test exceeds this many seconds.",
    )
    group.addoption(
        "--fast-total-budget",
        action="store",
        type=float,
        default=None,
        help="Fail if total setup+call+teardown time of a non-slow test exceeds this many seconds.",
    )


def pytest_configure(config: pytest.Config) -> None:
    global _ENFORCE_FAST_BUDGET
    global _FAST_CALL_BUDGET
    global _FAST_TOTAL_BUDGET
    global _FAST_CALL_OFFENDERS
    global _FAST_TOTAL_OFFENDERS
    global _FAST_PHASE_DURATIONS

    _ENFORCE_FAST_BUDGET = bool(config.getoption("--enforce-fast-budget"))
    _FAST_CALL_BUDGET = config.getoption("--fast-call-budget") or FAST_CALL_BUDGET_DEFAULT
    _FAST_TOTAL_BUDGET = config.getoption("--fast-total-budget") or FAST_TOTAL_BUDGET_DEFAULT

    _FAST_CALL_OFFENDERS = []
    _FAST_TOTAL_OFFENDERS = []
    _FAST_PHASE_DURATIONS = defaultdict(float)


@pytest.hookimpl
def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not _ENFORCE_FAST_BUDGET:
        return

    if "slow" in report.keywords:
        return

    _FAST_PHASE_DURATIONS[report.nodeid] += report.duration

    if report.when == "call" and report.duration > _FAST_CALL_BUDGET:
        _FAST_CALL_OFFENDERS.append((report.duration, report.nodeid))

    if report.when == "teardown":
        total = _FAST_PHASE_DURATIONS.pop(report.nodeid, 0.0)
        if total > _FAST_TOTAL_BUDGET:
            _FAST_TOTAL_OFFENDERS.append((total, report.nodeid))


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    call_offenders = sorted(_FAST_CALL_OFFENDERS, reverse=True)
    total_offenders = sorted(_FAST_TOTAL_OFFENDERS, reverse=True)

    if call_offenders:
        terminalreporter.section("fast-suite call-budget offenders", sep="=")
        for duration, nodeid in call_offenders:
            terminalreporter.line(f"{duration:7.3f}s  {nodeid}")

    if total_offenders:
        terminalreporter.section("fast-suite total-budget offenders", sep="=")
        for duration, nodeid in total_offenders:
            terminalreporter.line(f"{duration:7.3f}s  {nodeid}")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if (_FAST_CALL_OFFENDERS or _FAST_TOTAL_OFFENDERS) and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
