from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

Routes = Mapping[str, tuple[int, bytes] | tuple[int, bytes, Mapping[str, str]]]
ResolvedRoutes = dict[str, tuple[int, dict[str, str], bytes]]

_COMMON_MARKERS: tuple[str, ...] = (
    "unit: Fast, isolated tests of individual functions/classes. No real I/O or global state.",
    "component: Tests of a bounded context via public APIs with in-process fakes.",
    "integration: Tests involving real external dependencies (DB, queues, containers, external services).",
    "system: Full system / end-to-end tests treating the app as a black box.",
    "contract: Service/API or data/schema contract tests.",
    "acceptance: Requirement-driven system tests tied to user stories or acceptance criteria.",
    "regression: Prevent re-introduction of known bugs or failures.",
    "sanity: Narrow checks verifying specific bugfixes or features.",
    "smoke: Fast, critical-path tests run before larger suites.",
    "performance: Performance tests (latency, throughput, resource usage).",
    "performance_regression: Tests comparing runtime metrics to stored baselines.",
    "security: Security-focused tests.",
    "fuzz: Fuzzing-style tests feeding malformed/randomized inputs.",
    "chaos: Chaos/resilience tests injecting faults or disruptions.",
    "privacy: Privacy-impact tests ensuring correct PII/data handling.",
    "data_quality: Tests of data integrity, freshness, referential integrity, etc.",
    "drift: Model/data drift detection tests (PSI, KS, etc.).",
    "usability: Automated usability tests (accessibility, i18n).",
    "synthetic_monitoring: Synthetic production probes.",
    "snapshot: Snapshot-based tests.",
    "property_based: Property-based tests (Hypothesis).",
    "mutation: Mutation-testing related.",
    "observability: Tests asserting presence/shape of logs/metrics/traces.",
    "slow: Known slow tests.",
    "small: Fast unit test (<1s, no network/filesystem/subprocess/database/sleep).",
    "medium: Integration test (<5min, localhost network, filesystem allowed).",
    "large: System test (<15min, full network and resource access).",
    "xlarge: Extended test (<15min, full network and resource access).",
    "flaky: Known flaky tests under triage.",
    "legacy: Legacy tests awaiting refactor/removal.",
    "experimental: Experimental tests or tooling not yet mandatory.",
    "external_data: Tests requiring external vendor data (skip if vendor fixtures are absent).",
    "db: Database behavior tests.",
    "api: API-centric tests (HTTP/RPC).",
    "ml: ML-related tests.",
    "ui: UI-layer tests (web, CLI).",
)


def register_common_marks(config: pytest.Config) -> None:
    for marker in _COMMON_MARKERS:
        config.addinivalue_line("markers", marker)


class _RouteHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], routes: ResolvedRoutes):
        self.routes = routes
        self.request_counts: dict[str, int] = {}
        super().__init__(server_address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    # BaseHTTPRequestHandler passes printf-style args with mixed runtime types here.
    def log_message(self, format: str, *args: Any) -> None:  # ruff: ignore[builtin-argument-shadowing, no-self-use]
        del format, args

    def do_HEAD(self) -> None:
        self._respond(send_body=False)

    def do_GET(self) -> None:
        self._respond(send_body=True)

    def _respond(self, *, send_body: bool) -> None:
        routes: ResolvedRoutes = getattr(self.server, "routes", {})
        counts: dict[str, int] | None = getattr(self.server, "request_counts", None)
        if isinstance(counts, dict):
            counts[self.path] = counts.get(self.path, 0) + 1
        status, headers, body = routes.get(
            self.path,
            (404, {"Content-Type": "text/plain"}, b"not found"),
        )

        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)


@dataclass
class TestHTTPServer:
    __test__ = False

    host: str = "127.0.0.1"
    routes: ResolvedRoutes = field(default_factory=dict)

    _server: _RouteHTTPServer | None = field(default=None, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)

    def add(
        self,
        path: str,
        body: bytes,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not path.startswith("/"):
            path = "/" + path
        self.routes[path] = (int(status), dict(headers) if headers else {}, bytes(body))

    def start(self) -> None:
        self._server = _RouteHTTPServer((self.host, 0), self.routes)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def url_for(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    @property
    def port(self) -> int:
        if self._server is None:
            msg = "Server not started; call start() first."
            raise RuntimeError(msg)
        return self._server.server_port

    def request_count(self, path: str) -> int:
        if not path.startswith("/"):
            path = "/" + path
        if self._server is None:
            return 0
        return int(self._server.request_counts.get(path, 0))


@contextmanager
def serve(responses: Routes) -> Iterator[str]:
    server = TestHTTPServer()
    for raw_path, spec in responses.items():
        path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
        match spec:
            case (status, body):
                headers: dict[str, str] = {}
            case (status, body, headers_in):
                headers = dict(headers_in)
            case _:
                msg = f"Invalid route spec for {raw_path!r}: {spec!r}"
                raise ValueError(msg)
        server.add(path, body, status=int(status), headers=headers)

    server.start()
    try:
        yield server.base_url
    finally:
        server.stop()
