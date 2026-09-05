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
    fetch_to_file,
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


class FakeCache:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[tuple[str, bool]] = []

    async def get(self, url: str, *, refresh: bool):
        self.calls.append((url, refresh))
        return self.response


@pytest.mark.asyncio
@pytest.mark.medium
async def test_http_utils_helpers_and_fetchers(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("efloud.transport.http_utils.time.time", lambda: 123.0)

    assert len(sha256_hex("abc")) == 64
    assert human_name_from_url("https://host.example/a/b.json") == "host.example:b.json"
    assert slugify(" Hello, World! ") == "hello_world"
    assert cache_group_name("https://host.example/a", None) == "host_example"
    assert cache_group_name("https://host.example/a", "custom") == "custom"
    assert rel_dest_name("Example Data", "https://host.example/a/b", "REST").endswith(".json")

    dest = dest_for_http_source(tmp_path, url="https://host.example/a/b", description="Example Data", kind="REST")
    assert dest.parent.name == "host_example"

    response = FakeResponse(
        content=b"payload",
        headers={"etag": "abc"},
        request=httpx.Request("GET", "https://host.example/a", headers={"X-Test": "1"}),
    )
    cache = FakeCache(response)
    result = await fetch_to_file(
        cast("Any", cache),
        "https://host.example/a",
        tmp_path / "payload.bin",
        refresh=True,
    )
    assert result.status_code == 200
    assert (tmp_path / "payload.bin").read_bytes() == b"payload"
    assert result.request_headers == {"host": "host.example", "x-test": "1"}

    json_cache = FakeCache(
        FakeResponse(
            content=b'{"ok": true}',
            json_data={"ok": True},
            request=httpx.Request("GET", "https://host.example/json"),
        )
    )
    payload, json_result = await fetch_json_to_file(
        cast("Any", json_cache),
        "https://host.example/json",
        tmp_path / "payload.json",
        refresh=False,
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
        idle_seconds=4.0,
    )
    assert rsync_mod._connect_progress_label(
        remote="rsync://host/module",
        attempt=1,
        max_attempts=3,
        cfg=cfg,
        progress_bar=transfer_progress_bar,
        elapsed_seconds=83.0,
    ) == (
        "rsync attempt 1/3: transferring files host:8873 "
        "[47,333/251,423 files handled (18.8%); 634 transferred; 161.6 MB; 34.85MB/s] "
        "18:37 remaining (20:00 timeout; last output 00:04 ago)"
    )


@pytest.mark.small
def test_build_rsync_cmd_logs_exact_argv_and_shell_rendering(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    cfg = RsyncMirrorConfig(
        name="mirror",
        remote="rsync://host/module",
        local=tmp_path / "target dir",
        exclude=("**/.DS_Store",),
        cmd=rsync_mod.RsyncCommandConfig(prune_empty_dirs=True),
    )

    with caplog.at_level("DEBUG", logger="efloud.transport.rsync"):
        cmd = rsync_mod._build_rsync_cmd(cfg, remote=cfg.remote, local=cfg.local)

    prepared = next(message for message in caplog.messages if message.startswith("Prepared rsync command"))
    assert cmd[-2:] == ["rsync://host/module", str(tmp_path / "target dir")]
    assert "argv=['rsync'" in prepared
    assert "rsync://host/module" in prepared
    assert "'rsync://host/module'" in prepared
    assert "shell=rsync" in prepared
    assert "--prune-empty-dirs" in prepared
    assert "'**/.DS_Store'" in prepared
    assert f"'{tmp_path / 'target dir'}'" in prepared


@pytest.mark.small
def test_build_rsync_cmd_includes_prune_empty_dirs_when_enabled(tmp_path: Path):
    cfg = RsyncMirrorConfig(
        name="mirror",
        remote="rsync://host/module",
        local=tmp_path,
        cmd=rsync_mod.RsyncCommandConfig(prune_empty_dirs=True),
    )

    cmd = rsync_mod._build_rsync_cmd(cfg, remote=cfg.remote, local=cfg.local)

    assert "--prune-empty-dirs" in cmd


@pytest.mark.small
def test_file_list_stall_warning_emits_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = RsyncMirrorConfig(
        name="mirror",
        remote="rsync://host/module",
        local=tmp_path,
        progress=True,
    )
    messages: list[str] = []
    phase_state: dict[str, str | float | bool] = {
        "phase": "receiving file list",
        "last_output_at": 100.0,
        "file_list_count": 67_200,
    }

    monkeypatch.setattr(rsync_mod.time, "perf_counter", lambda: 400.0)
    monkeypatch.setattr(rsync_mod, "_emit_runtime_message", lambda _cfg, text: messages.append(text))

    rsync_mod._maybe_emit_file_list_stall_warning(
        cfg,
        attempt=1,
        max_attempts=3,
        elapsed_seconds=301.0,
        phase_state=phase_state,
    )
    rsync_mod._maybe_emit_file_list_stall_warning(
        cfg,
        attempt=1,
        max_attempts=3,
        elapsed_seconds=302.0,
        phase_state=phase_state,
    )

    assert messages == [
        (
            "rsync attempt 1/3: still receiving file list after 05:01 "
            "(20:00 timeout); discovered 67,200 files; last rsync output 05:00 ago"
        )
    ]
    assert phase_state["file_list_warning_emitted"] is True


@pytest.mark.small
def test_observe_runtime_phase_captures_file_list_count(monkeypatch: pytest.MonkeyPatch):
    phase_state: dict[str, str | float | bool | int] = {"phase": "connecting"}
    monkeypatch.setattr(rsync_mod.time, "perf_counter", lambda: 123.0)

    rsync_mod._observe_runtime_phase("receiving file list ...\n67200 files...\n", phase_state)

    assert phase_state["phase"] == "receiving file list"
    assert phase_state["last_output_at"] == pytest.approx(123.0, rel=0.0, abs=1e-12)
    assert phase_state["file_list_count"] == 67_200


@pytest.mark.small
def test_observe_runtime_phase_captures_transfer_stats(monkeypatch: pytest.MonkeyPatch):
    phase_state: dict[str, str | float | bool | int] = {"phase": "connecting"}
    monkeypatch.setattr(rsync_mod.time, "perf_counter", lambda: 456.0)

    rsync_mod._observe_runtime_phase(
        "169,440,614   0%   34.85MB/s    0:00:04 (xfr#634, to-chk=204090/251423)\n",
        phase_state,
    )

    assert phase_state["phase"] == "transferring files"
    assert phase_state["transfer_total_files"] == 251_423
    assert phase_state["transfer_remaining_files"] == 204_090
    assert phase_state["transfer_handled_files"] == 47_333
    assert phase_state["transfer_transferred_files"] == 634
    assert phase_state["transfer_bytes"] == 169_440_614
    assert phase_state["transfer_rate"] == "34.85MB/s"


@pytest.mark.small
def test_result_phase_prefers_transfer_markers_over_file_list_text() -> None:
    result = OpResult(
        status="failed",
        detail="rsync failed after 3 attempts",
        returncode=10,
        stdout=(
            "receiving file list ...\n"
            "251423 files to consider\n"
            ">f.st....... 2ogr.cif.gz\n"
            "169,440,614   0%   34.85MB/s    0:00:04 (xfr#634, to-chk=204090/251423)\n"
        ),
        stderr="rsync: [receiver] read error: Connection reset by peer (54)\n",
    )

    assert rsync_mod._result_phase(result) == "transferring files"


@pytest.mark.asyncio
@pytest.mark.medium
async def test_rsync_mirror_skips_fresh_and_updates_paths(tmp_path: Path, monkeypatch):
    mirror_root = tmp_path / "mirror"
    mirror_root.mkdir()
    meta_path = mirror_root / ".mirror_meta.json"
    meta_path.write_text(
        json.dumps({"version": 1, "paths": {".": {"updated_at_unix": 100, "updated": ["old.txt"]}}}),
        encoding="utf-8",
    )

    monkeypatch.setattr("efloud.transport.rsync.time.time", lambda: 105.0)
    mirror = RsyncMirror(
        RsyncMirrorConfig(
            name="mirror",
            remote="host::module",
            local=mirror_root,
            update_interval_seconds=10,
        )
    )

    skipped = await mirror.update()
    assert skipped.status == "skipped_fresh"
    assert skipped.updated == ["old.txt"]

    recorded_cmds: list[list[str]] = []

    def fake_build(cfg, *, remote, local):
        recorded_cmds.append([remote, str(local)])
        return ["rsync", remote, str(local)]

    def fake_run(cfg, *, cmd, remote, local):
        del cfg, cmd, remote, local
        return OpResult(status="success", detail="ok", returncode=0, stdout=">f++++ file.txt", updated=["file.txt"])

    monkeypatch.setattr("efloud.transport.rsync.time.time", lambda: 200.0)
    monkeypatch.setattr("efloud.transport.rsync._build_rsync_cmd", fake_build)
    monkeypatch.setattr("efloud.transport.rsync._run_rsync_process", fake_run)
    await asyncio.sleep(0)

    result = await mirror.update_paths(["nested/file.txt"], force=True)
    assert result["nested/file.txt"].status == "success"
    assert recorded_cmds == [["host::module/nested/file.txt", str(mirror_root / "nested")]]

    meta = read_rsync_mirror_meta(mirror_root)
    assert meta is not None
    assert meta.paths is not None
    assert meta.paths["nested/file.txt"]["updated"] == ["file.txt"]


@pytest.mark.medium
def test_rsync_meta_round_trip_and_invalid_read(tmp_path: Path):
    payload = {"version": 2, "paths": {"a": {"updated_at_unix": 1, "updated": ["x"]}}}
    meta = RsyncMirrorMeta.from_json(payload)
    assert meta.to_json() == payload

    meta_path = tmp_path / ".mirror_meta.json"
    meta_path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = read_rsync_mirror_meta(tmp_path)
    assert loaded is not None
    assert loaded.to_json() == payload

    meta_path.write_text("{", encoding="utf-8")
    assert read_rsync_mirror_meta(tmp_path) is None


@pytest.mark.small
def test_rsync_process_once_does_not_set_start_new_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    captured_kwargs: dict[str, object] = {}

    class FakeProc:
        def __init__(self, _cmd: list[str], **kwargs: object):
            captured_kwargs.update(kwargs)
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.returncode = 0

        def wait(self) -> int:
            self.returncode = 0
            return 0

    monkeypatch.setattr(rsync_mod.subprocess, "Popen", FakeProc)

    cfg = RsyncMirrorConfig(
        name="mirror",
        remote="host::module",
        local=tmp_path / "mirror",
        progress=False,
        verbose=False,
    )

    result = rsync_mod._run_rsync_process_once(
        cfg,
        cmd=["rsync", "host::module", str(tmp_path / "mirror")],
        remote="host::module",
        local=tmp_path / "mirror",
        attempt=1,
        max_attempts=3,
    )

    assert result.status == "success"
    assert "start_new_session" not in captured_kwargs
