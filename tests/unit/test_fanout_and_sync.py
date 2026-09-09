from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from efloud.derived import ExtensionContext
from efloud.engine import Engine
from efloud.models import EngineConfig
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.sync import sync
from efloud.transport.rsync import OpResult, RsyncMirrorConfig

fanout_mod = importlib.import_module("efloud.fanout")


pytestmark = [pytest.mark.unit]


class FakeFanoutResponse:
    def __init__(
        self, status_code: int, *, payload=None, content: bytes = b"{}", url: str = "https://api.example.test"
    ):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.request = httpx.Request("GET", url)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            msg = "boom"
            response = httpx.Response(self.status_code, request=self.request)
            raise httpx.HTTPStatusError(msg, request=self.request, response=response)


class FakeFanoutCache:
    def __init__(self, responses):
        self.responses = responses
        self.calls: list[tuple[str, bool]] = []
        self.closed = False

    async def get(self, url: str, *, refresh: bool):
        self.calls.append((url, refresh))
        return self.responses[url]

    async def aclose(self):
        await asyncio.sleep(0)
        self.closed = True


class DummyDerivedTask:
    def __init__(self, name: str, payload: dict[str, object]):
        self.name = name
        self.payload = payload

    async def run(self, *, context):
        await asyncio.sleep(0)
        return dict(self.payload)


class DummyCache:
    def __init__(self, name):
        self._name = name
        self.closed = False

    async def aclose(self):
        await asyncio.sleep(0)
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.medium
async def test_materialize_fanout_and_rest_base_task(tmp_path: Path, monkeypatch):
    assert fanout_mod.two_char_bucket("ABC123") == Path("bc") / "abc123.json"
    assert fanout_mod.two_char_bucket("x") == Path("xx") / "x.json"

    base_url = "https://api.example.test/items"
    cache = FakeFanoutCache({
        f"{base_url}/alpha": FakeFanoutResponse(200, payload={"id": "alpha"}, url=f"{base_url}/alpha"),
        f"{base_url}/missing": FakeFanoutResponse(404, url=f"{base_url}/missing"),
        f"{base_url}/boom": FakeFanoutResponse(500, url=f"{base_url}/boom"),
    })
    statuses = await fanout_mod._materialize_fanout(
        cache=cast("Any", cache),
        base_url=base_url,
        items=[
            fanout_mod.FanoutItem("alpha"),
            fanout_mod.FanoutItem("missing"),
            fanout_mod.FanoutItem("boom", metadata={"kind": "test"}),
        ],
        dest_root=tmp_path,
        response_mode="json",
        bucket=fanout_mod.two_char_bucket,
        refresh=True,
        concurrency=2,
    )

    assert statuses["alpha"]["status"] == "ok"
    assert json.loads((tmp_path / "lp" / "alpha.json").read_text(encoding="utf-8")) == {"id": "alpha"}
    assert statuses["missing"]["error"] == "404"
    assert statuses["boom"]["status"] == "error"
    assert statuses["boom"]["metadata"] == {"kind": "test"}

    class FakeHttpCache(FakeFanoutCache):
        def __init__(self, cfg):
            super().__init__({
                f"{base_url}/alpha": FakeFanoutResponse(
                    200,
                    payload={"id": "alpha"},
                    url=f"{base_url}/alpha",
                )
            })
            self.cfg = cfg

    monkeypatch.setattr(fanout_mod, "HttpCache", FakeHttpCache)

    async def enumerator(*, context):
        assert context.workspace == tmp_path
        await asyncio.sleep(0)
        return [fanout_mod.FanoutItem("alpha")]

    source = SourceDefinition("fanout-id", "Fanout", "https://api.example.test", SourceKind.REST_BASE)
    task = fanout_mod.RestBaseFanoutTask(
        name="fanout",
        source_id="fanout-id",
        base_url=base_url,
        enumerator=enumerator,
        dest_subdir="fanout",
        request_headers={"X-Test": "1"},
    )
    with Repository(tmp_path) as repository:
        result = await task.run(context=ExtensionContext(repository, tmp_path, (source,)))
    payload = result.details
    assert payload["source_id"] == "fanout-id"
    assert payload["ok"] == 1
    assert payload["err"] == 0


@pytest.mark.asyncio
@pytest.mark.medium
async def test_sync_orchestration_delegates_to_engine(tmp_path: Path, monkeypatch):
    cfg = EngineConfig(root=tmp_path, sources=[])
    with Engine.from_config(cfg) as engine:
        expected = await engine.sync()
    calls = []

    async def fake_sync(self, request=None):
        await asyncio.sleep(0)
        calls.append((self.config, request))
        return expected

    monkeypatch.setattr(Engine, "sync", fake_sync)
    with pytest.warns(DeprecationWarning, match="Engine"):
        result = await sync(cfg)
    assert result.ok == expected.ok
    assert result.root == expected.root
    assert calls == [(cfg, None)]
    with Repository(tmp_path):
        pass


@pytest.mark.small
def test_rsync_transport_retries_transient_failures(monkeypatch, tmp_path: Path):
    transport_mod = importlib.import_module("efloud.transport.rsync")
    cfg = RsyncMirrorConfig(
        name="Retry Test",
        remote="rsync.example.test::module",
        local=tmp_path / "mirror",
    )
    attempts: list[int] = []
    sleeps: list[float] = []
    messages: list[str] = []

    def fake_once(_cfg, *, cmd, remote, local, attempt, max_attempts):
        del _cfg, cmd, local, attempt, max_attempts
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            return OpResult(
                status="failed",
                detail="rsync failed",
                returncode=10,
                stderr="failed to connect to rsync.example.test: Operation timed out (60)",
            )
        return OpResult(status="success", detail="ok", returncode=0, updated=["file.txt"])

    monkeypatch.setattr(transport_mod, "_run_rsync_process_once", fake_once)
    monkeypatch.setattr(transport_mod, "_preflight_connectivity", lambda _cfg, *, remote: messages.append(remote))
    monkeypatch.setattr(transport_mod, "_emit_runtime_message", lambda _cfg, text: messages.append(text))
    monkeypatch.setattr(transport_mod.time, "sleep", sleeps.append)

    result = transport_mod._run_rsync_process(
        cfg,
        cmd=["rsync"],
        remote="rsync.example.test::module/path",
        local=tmp_path / "mirror",
    )

    assert result.status == "success"
    assert result.phase == "completed"
    assert result.attempt_count == 3
    assert result.max_attempts == 3
    assert result.attempt_errors == [
        "failed to connect to rsync.example.test: Operation timed out (60)",
        "failed to connect to rsync.example.test: Operation timed out (60)",
    ]
    assert sleeps == [1.0] * 17
    assert any("rsync.example.test::module/path" in message for message in messages)
    assert any("retry 2/3 starts in 5s" in message for message in messages)


@pytest.mark.small
def test_rsync_transport_does_not_retry_non_transient_failures(monkeypatch, tmp_path: Path):
    transport_mod = importlib.import_module("efloud.transport.rsync")
    cfg = RsyncMirrorConfig(
        name="Retry Test",
        remote="rsync.example.test::module",
        local=tmp_path / "mirror",
    )
    attempts: list[int] = []

    def fake_once(_cfg, *, cmd, remote, local, attempt, max_attempts):
        del _cfg, cmd, remote, local, attempt, max_attempts
        attempts.append(1)
        return OpResult(
            status="failed",
            detail="rsync failed",
            returncode=5,
            stderr="@ERROR: Unknown module 'badpath'",
        )

    monkeypatch.setattr(transport_mod, "_run_rsync_process_once", fake_once)
    monkeypatch.setattr(transport_mod, "_preflight_connectivity", lambda _cfg, *, remote: None)
    monkeypatch.setattr(transport_mod.time, "sleep", lambda _seconds: None)

    result = transport_mod._run_rsync_process(
        cfg,
        cmd=["rsync"],
        remote="rsync.example.test::module",
        local=tmp_path / "mirror",
    )

    assert result.status == "failed"
    assert result.phase == "checking remote state"
    assert result.attempt_count == 1
    assert result.max_attempts == 3
    assert len(attempts) == 1


@pytest.mark.small
def test_rsync_transport_does_not_retry_host_key_or_path_failures(monkeypatch, tmp_path: Path):
    transport_mod = importlib.import_module("efloud.transport.rsync")
    cfg = RsyncMirrorConfig(
        name="Retry Test",
        remote="rsync.example.test::module",
        local=tmp_path / "mirror",
    )
    attempts: list[int] = []

    failures = [
        OpResult(
            status="failed",
            detail="rsync failed",
            returncode=255,
            stderr="Host key verification failed.",
        ),
        OpResult(
            status="failed",
            detail="rsync failed",
            returncode=23,
            stderr=(
                'rsync: [sender] change_dir "data/structures/all/mmcif" (in ftp) failed: No such file or directory (2)'
            ),
        ),
    ]

    def fake_once(_cfg, *, cmd, remote, local, attempt, max_attempts):
        del _cfg, cmd, remote, local, attempt, max_attempts
        attempts.append(1)
        return failures[len(attempts) - 1]

    monkeypatch.setattr(transport_mod, "_run_rsync_process_once", fake_once)
    monkeypatch.setattr(transport_mod, "_preflight_connectivity", lambda _cfg, *, remote: None)
    monkeypatch.setattr(transport_mod.time, "sleep", lambda _seconds: None)

    first = transport_mod._run_rsync_process(
        cfg,
        cmd=["rsync"],
        remote="rsync.example.test::module",
        local=tmp_path / "mirror",
    )
    second = transport_mod._run_rsync_process(
        cfg,
        cmd=["rsync"],
        remote="rsync.example.test::module",
        local=tmp_path / "mirror",
    )

    assert first.attempt_count == 1
    assert second.attempt_count == 1
    assert len(attempts) == 2


@pytest.mark.small
def test_remote_display_target_uses_rsync_daemon_module_syntax() -> None:
    transport_mod = importlib.import_module("efloud.transport.rsync")

    assert transport_mod._remote_display_target("rsync.rcsb.org::ftp_data/structures/all/") == "rsync.rcsb.org:873"
    assert (
        transport_mod._remote_display_target(
            "rsync.rcsb.org::ftp_data/structures/all/",
            configured_port=8873,
        )
        == "rsync.rcsb.org:8873"
    )
    assert (
        transport_mod._remote_display_target("rsync://rsync.rcsb.org:9900/ftp_data/structures/all/")
        == "rsync.rcsb.org:9900"
    )
