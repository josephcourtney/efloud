from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    _test_reporting = importlib.import_module("pytest_test_categories.services.test_reporting")
except ModuleNotFoundError:  # pragma: no cover - optional plugin import during bootstrap
    _test_reporting = None

if TYPE_CHECKING:
    from pytest_test_categories.distribution.stats import DistributionStats
    from pytest_test_categories.services.test_reporting import TestReportingService
    from pytest_test_categories.types import OutputWriterPort


def _suppress_distribution_summary(
    self: TestReportingService,
    stats: DistributionStats,
    writer: OutputWriterPort,
) -> None:
    del self, stats, writer


def pytest_configure() -> None:
    if _test_reporting is not None:
        # The repo uses the plugin for explicit size markers/enforcement,
        # but not for Google-style mix reporting.
        reporting_service_class = cast(
            "Any",
            _test_reporting.TestReportingService,
        )
        reporting_service_class.write_distribution_summary = _suppress_distribution_summary
