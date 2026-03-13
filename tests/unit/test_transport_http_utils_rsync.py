from __future__ import annotations

import asyncio
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

pytestmark = [pytest.mark.unit, pytest.mark.medium]


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
async def test_http_utils_helpers_and_fetchers(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("efloud.transport.http_utils.time.time", lambda: 123.0)

    assert len(sha256_hex("abc")) == 64
    assert human_name_from_url("https://host.example/a/b.json") == "host.example:b.json"
    assert slugify(" Hello, World! ") == "hello_world"
    assert cache_group_name("https://host.example/a", None) == "host_example"
    assert cache_group_name("https://host.example/a", "custom") == "custom"
    assert rel_dest_name("Example Data", "https://host.example/a/b", "REST").endswith(".json")

    dest = dest_for_http_source(
        tmp_path, url="https://host.example/a/b", description="Example Data", kind="REST"
    )
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


def test_rsync_helper_functions_build_expected_values(tmp_path: Path):
    cfg = RsyncMirrorConfig(
        name="mirror",
        remote="host::module",
        local=tmp_path,
        include=("*.json",),
        exclude=("*.tmp",),
        delete=True,
        verbose=True,
        progress=True,
        dry_run=True,
    )

    cmd = rsync_mod._build_rsync_cmd(cfg, remote=cfg.remote, local=cfg.local)
    assert cmd[0] == "rsync"
    assert "--contimeout=1200" in cmd
    assert "--timeout=1200" in cmd
    assert "--include" in cmd
    assert "--exclude" in cmd
    assert "--dry-run" in cmd
    assert rsync_mod._timeout_args("host::module", timeout_seconds=30) == ["--contimeout=30", "--timeout=30"]
    assert rsync_mod._timeout_args("ssh://host/path", timeout_seconds=30) == ["--timeout=30"]
    assert rsync_mod._pattern_args("--include", ("a", "b")) == ["--include", "a", "--include", "b"]
    assert rsync_mod._parse_itemize_changes(">f+++++++++ foo.txt\ncd+++++++++ dir") == ["foo.txt", "dir"]
    assert rsync_mod._join_remote_path("rsync://host/base/", "/child") == "rsync://host/base/child"
    assert rsync_mod._looks_like_file_path("dir/file.txt") is True
    assert rsync_mod._looks_like_file_path("dir/subdir") is False
    assert rsync_mod._updated_paths(["a", 1, "b"]) == ["a", "b"]


@pytest.mark.asyncio
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

    def fake_run(cfg, *, cmd):
        return OpResult(
            status="success", detail="ok", returncode=0, stdout=">f++++ file.txt", updated=["file.txt"]
        )

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
