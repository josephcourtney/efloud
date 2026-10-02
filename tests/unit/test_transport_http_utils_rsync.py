from __future__ import annotations

import asyncio
import io
import json
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from efloud.transport import rsync as rsync_mod
from efloud.transport.http_utils import (
    cache_group_name,
    dest_for_http_source,
    fetch_json_to_file,
    human_name_from_url,
    rel_dest_name,
    sha256_hex,
    slugify,
)
from efloud.transport.rsync import (
    OpResult,
    RsyncMirror,
    RsyncMirrorConfig,
    RsyncMirrorMeta,
    read_rsync_mirror_meta,
)

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.json_types import JsonValue

pytestmark = [pytest.mark.unit]


class FakeResponse:
    def __init__(self, *, status_code=200, content=b"{}", json_data=None, headers=None, request=None):
        self.status_code = status_code
        self.content = content
        self._json_data = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.request = request or httpx.Request("GET", "https://example.test")

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            msg = "boom"
            response = httpx.Response(self.status_code, request=self.request)
            raise httpx.HTTPStatusError(msg, request=self.request, response=response)


class FakeClient:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    async def get(self, url: str, *, headers: dict[str, str] | None = None):
        self.calls.append((url, headers))
        return self.response


@pytest.mark.asyncio
@pytest.mark.medium
async def test_http_utils_helpers_and_json_fetch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("efloud.transport.http_utils.time.time", lambda: 123.0)

    assert len(sha256_hex("abc")) == 64
    assert human_name_from_url("https://host.example/a/b.json") == "host.example:b.json"
    assert slugify(" Hello, World! ") == "hello_world"
    assert cache_group_name("https://host.example/a", None) == "host_example"
    assert cache_group_name("https://host.example/a", "custom") == "custom"
    assert rel_dest_name("Example Data", "https://host.example/a/b", "REST").endswith(".json")

    dest = dest_for_http_source(tmp_path, url="https://host.example/a/b", description="Example Data", kind="REST")
    assert dest.parent.name == "host_example"

    json_client = FakeClient(
        FakeResponse(
            content=b'{"ok": true}',
            json_data={"ok": True},
            request=httpx.Request("GET", "https://host.example/json"),
        )
    )
    payload, json_result = await fetch_json_to_file(
        cast("Any", json_client),
        "https://host.example/json",
        tmp_path / "payload.json",
    )
    assert payload == {"ok": True}
    assert json.loads((tmp_path / "payload.json").read_text(encoding="utf-8")) == {"ok": True}
    assert json_result.size_bytes > 0


@pytest.mark.small
def test_rsync_helper_functions_build_expected_values(tmp_path: Path):
    cfg = RsyncMirrorConfig(
        name="mirror",
        remote="host::module",
        local=tmp_path,
        port=8873,
        include=("*.json",),
        exclude=("*.tmp",),
        delete=True,
        verbose=True,
        progress=True,
        dry_run=True,
    )

    cmd = rsync_mod._build_rsync_cmd(cfg, remote=cfg.remote, local=cfg.local)
    assert cmd[0] == "rsync"
    assert "--port=8873" in cmd
    assert "--contimeout=1200" in cmd
    assert "--timeout=1200" in cmd
    assert "--include" in cmd
    assert "--exclude" in cmd
    assert "--dry-run" in cmd
    assert "--prune-empty-dirs" not in cmd
    assert rsync_mod._timeout_args("host::module", timeout_seconds=30) == ["--contimeout=30", "--timeout=30"]
    assert rsync_mod._timeout_args("ssh://host/path", timeout_seconds=30) == ["--timeout=30"]
    assert rsync_mod._port_args("host::module", port=8873) == ["--port=8873"]
    assert rsync_mod._port_args("rsync://host/module", port=8873) == ["--port=8873"]
    assert rsync_mod._port_args("ssh://host/path", port=8873) == []
    assert rsync_mod._pattern_args("--include", ("a", "b")) == ["--include", "a", "--include", "b"]
    assert rsync_mod._parse_itemize_changes(">f+++++++++ foo.txt\ncd+++++++++ dir") == ["foo.txt", "dir"]
    assert rsync_mod._join_remote_path("rsync://host/base/", "/child") == "rsync://host/base/child"
    assert rsync_mod._looks_like_file_path("dir/file.txt") is True
    assert rsync_mod._looks_like_file_path("dir/subdir") is False
    assert rsync_mod._updated_paths(["a", 1, "b"]) == ["a", "b"]
    assert rsync_mod._remote_host_and_port("host::module", configured_port=8873) == ("host", 8873)
    assert rsync_mod._remote_host_and_port("rsync://host:9900/module", configured_port=8873) == ("host", 9900)
    assert rsync_mod._format_clock_duration(83.9) == "01:23"
    assert rsync_mod._format_clock_duration(1200.0) == "20:00"
    assert rsync_mod._format_clock_duration(3723.0) == "01:02:03"
    assert rsync_mod._parse_file_list_count("receiving file list ...\n67200 files...\n") == 67_200
    assert rsync_mod._parse_file_list_count("receiving file list ...\n67,200 files...\n") == 67_200
    assert rsync_mod._parse_transfer_progress(
        "169,440,614   0%   34.85MB/s    0:00:04 (xfr#634, to-chk=204090/251423)\n"
    ) == {
        "transfer_total_files": 251_423,
        "transfer_remaining_files": 204_090,
        "transfer_transferred_files": 634,
        "transfer_handled_files": 47_333,
        "transfer_bytes": 169_440_614,
        "transfer_rate": "34.85MB/s",
    }
    assert rsync_mod._render_shell_arg("rsync://host/module") == "'rsync://host/module'"
    assert rsync_mod._render_shell_arg("dir/file.txt") == "'dir/file.txt'"
    assert rsync_mod._render_shell_arg("**/.DS_Store") == "'**/.DS_Store'"
    assert rsync_mod._render_shell_arg("--archive") == "--archive"
    assert (
        rsync_mod._render_shell_command([
            "rsync",
            "--exclude",
            "**/.DS_Store",
            "rsync://host/module",
            "dest",
        ])
        == "rsync --exclude '**/.DS_Store' 'rsync://host/module' dest"
    )
    progress_bar = rsync_mod._ProgressBarState(current_phase="receiving file list", file_list_count=67_200)
    assert (
        rsync_mod._connect_progress_label(
            remote="rsync://host/module",
            attempt=1,
            max_attempts=3,
            cfg=cfg,
            progress_bar=progress_bar,
            elapsed_seconds=83.0,
        )
        == "rsync attempt 1/3: receiving file list host:8873 (67,200 files) 18:37 remaining (20:00 timeout)"
    )

    transfer_progress_bar = rsync_mod._ProgressBarState(
        current_phase="transferring files",
        transfer_total_files=251_423,
        transfer_handled_files=47_333,
        transfer_transferred_files=634,
        transfer_bytes=169_440_614,
        transfer_rate="34.85MB/s",
    )
    assert (
        rsync_mod._connect_progress_label(
            remote="rsync://host/module",
            attempt=1,
            max_attempts=3,
            cfg=cfg,
            progress_bar=transfer_progress_bar,
            elapsed_seconds=83.0,
        )
        == "rsync attempt 1/3: transferring files host:8873 (47,333/251,423 handled; 634 transferred; 169.4 MB; 34.85MB/s) 18:37 remaining (20:00 timeout)"
    )


@pytest.mark.asyncio
@pytest.mark.medium
async def test_rsync_mirror_sync_and_metadata(tmp_path: Path, monkeypatch):
    local = tmp_path / "mirror"
    cfg = RsyncMirrorConfig(name="mirror", remote="host::module", local=local)
    mirror = RsyncMirror(cfg)

    calls: list[list[str]] = []

    async def fake_run(cmd, *, timeout=None, progress=False, progress_context=None):
        calls.append(list(cmd))
        return OpResult(0, "ok", "")

    monkeypatch.setattr(rsync_mod, "_run", fake_run)
    result = await mirror.sync()
    assert result.returncode == 0
    assert calls

    meta = RsyncMirrorMeta(remote="host::module", last_sync_at=123.0, last_status="ok")
    rsync_mod._write_rsync_mirror_meta(local, meta)
    assert read_rsync_mirror_meta(local) == meta


@pytest.mark.small
def test_json_type_cast_is_available() -> None:
    value = cast("JsonValue", {"ok": True})
    assert value == {"ok": True}
