from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from efloud.models import EngineConfig
from efloud.registry import MirrorMode, SourceDefinition, SourceKind
from efloud.sync import (
    ManifestRecorder,
    build_http_caches,
    prepare_paths,
    run_http_phase,
    run_rsync_phase,
    sync,
)
from efloud.transport.http_utils import HttpFetchResult
from efloud.transport.rsync import OpResult, RsyncMirror, RsyncMirrorConfig

fanout_mod = importlib.import_module("efloud.fanout")
sync_mod = importlib.import_module("efloud.sync")

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

    async def run(self, *, sync_root, manifest, sources):
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

    async def enumerator(*, sync_root, manifest, sources):
        assert sync_root == tmp_path
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
    payload = await task.run(
        sync_root=tmp_path,
        manifest={
            "results": {"http": {}, "rsync": {}, "derived": {}},
            "errors": [],
            "root": str(tmp_path),
            "version": 1,
        },
        sources=(source,),
    )
    assert payload["source_id"] == "fanout-id"
    assert payload["ok"] == 1
    assert payload["err"] == 0


@pytest.mark.asyncio
@pytest.mark.medium
async def test_manifest_recorder_and_sync_helpers(tmp_path: Path, monkeypatch):
    cfg = EngineConfig(
        root=tmp_path,
        sources=[
            SourceDefinition("http-id", "HTTP", "https://example.test/data.json", SourceKind.HTTP),
            SourceDefinition(
                "rsync-id",
                "Mirror",
                "rsync.example.test::module",
                SourceKind.RSYNC,
                local_subpath="mirror/source",
                mirror_mode=MirrorMode.PATHS,
                mirror_paths=("subset",),
            ),
        ],
        derived_tasks=(DummyDerivedTask("derived-task", {"ok": True}),),
    )
    monkeypatch.setattr(sync_mod.time, "time", lambda: 100.0)
    recorder = ManifestRecorder(root=tmp_path, cfg=cfg)
    recorder.record_http(manifest_key="http-id", entry={"ok": True})
    recorder.record_rsync(manifest_key="rsync-id", entry={"ok": False})
    recorder.record_derived(name="derived-task", payload={"ok": True})
    recorder.error(phase="http", error="boom", source_id="http-id")
    recorder.finish()

    assert recorder.manifest["finished_at_unix"] == 100
    out_path = await recorder.write_if_requested(tmp_path / "log" / "manifest.json")
    assert out_path == (tmp_path / "log" / "manifest.json").resolve()

    paths = prepare_paths(tmp_path, cfg)
    stamped = sync_mod._timestamped_manifest_path(paths.log, cfg.manifest_filename, when=0)
    assert stamped.name.startswith("sync-manifest-19700101T000000Z")
    assert sync_mod._mirror_source_info(cfg) == [("rsync-id", "mirror/source")]

    previous_state_path = tmp_path / cfg.state_filename
    previous_state_path.write_text(
        json.dumps({
            "version": 1,
            "generated_at_unix": 50.0,
            "cache_root": str(tmp_path),
            "mirrors_root": str(paths.mirrors.resolve()),
            "hash_algo": "sha256",
            "manifest_path": None,
            "tree": {
                "type": "dir",
                "hash": "root",
                "children": {"mirror": {"type": "dir", "hash": "child"}},
            },
            "sources": [{"source_id": "old", "local_subdir": "old", "hash": "old-hash"}],
        }),
        encoding="utf-8",
    )

    previous_state = json.loads(previous_state_path.read_text(encoding="utf-8"))
    from efloud.state import MirrorState

    prev = MirrorState.from_dict(previous_state)
    assert prev is not None
    tree = prev.tree
    source_states = sync_mod._build_source_states(prev, tree, [("rsync-id", "mirror/source")])
    assert any(state.source_id == "rsync-id" for state in source_states)

    monkeypatch.setattr(sync_mod.time, "time", lambda: 200.0)
    incremental = sync_mod._build_incremental_state(
        cfg=cfg,
        paths=paths,
        manifest_path=tmp_path / "log" / "x.json",
        previous_state=prev,
    )
    assert incremental.generated_at_unix == pytest.approx(200.0)

    recorder = ManifestRecorder(root=tmp_path, cfg=cfg)
    recorder.record_http(manifest_key="http-id", entry={"ok": True})
    recorder.finish()
    manifest_path = await sync_mod._write_manifest_outputs(cfg=cfg, paths=paths, recorder=recorder)
    assert manifest_path is not None
    assert manifest_path.exists()
    sync_mod._update_canonical_manifest(cfg=cfg, paths=paths, recorder=recorder)
    assert (paths.log / cfg.manifest_filename).exists()


@pytest.mark.asyncio
@pytest.mark.medium
async def test_run_phases_with_fake_transports(tmp_path: Path, monkeypatch):
    sources = [
        SourceDefinition("http-id", "HTTP", "https://example.test/data.bin", SourceKind.HTTP),
        SourceDefinition("rest-id", "REST", "https://example.test/data.json", SourceKind.REST),
        SourceDefinition(
            "rsync-id",
            "Mirror",
            "rsync.example.test::module",
            SourceKind.RSYNC,
            local_subpath="mirror/source",
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("subset",),
        ),
    ]
    cfg = EngineConfig(root=tmp_path, sources=sources)
    paths = prepare_paths(tmp_path, cfg)
    recorder = ManifestRecorder(root=tmp_path, cfg=cfg)

    made_caches = []

    class FakeCacheCtor(DummyCache):
        def __init__(self, cfg):
            super().__init__(cfg.name)
            made_caches.append(cfg.name)

    monkeypatch.setattr(sync_mod, "HttpCache", FakeCacheCtor)
    caches = build_http_caches(sources=sources, cache_root=paths.http_cache, rate_root=paths.rate)
    assert sorted(caches) == sorted(set(made_caches))

    async def fake_fetch_to_file(cache, url, dest, *, refresh):
        del cache, url, refresh
        await asyncio.sleep(0)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"bin")
        return HttpFetchResult(200, {"etag": "a"}, "sum", 3, 100.0, {"X-Test": "1"})

    async def fake_fetch_json_to_file(cache, url, dest, *, refresh):
        del cache, url, refresh
        await asyncio.sleep(0)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('{"ok": true}', encoding="utf-8")
        return {"ok": True}, HttpFetchResult(201, {"last-modified": "y"}, "sum2", 12, 101.0, {})

    monkeypatch.setattr(sync_mod, "fetch_to_file", fake_fetch_to_file)
    monkeypatch.setattr(sync_mod, "fetch_json_to_file", fake_fetch_json_to_file)
    await run_http_phase(cfg=cfg, paths=paths, http_caches=caches, recorder=recorder)
    assert recorder.manifest["results"]["http"]["http-id"]["status_code"] == 200
    assert recorder.manifest["results"]["http"]["rest-id"]["status_code"] == 201

    class FakeMirror:
        def __init__(self, cfg):
            self.cfg = cfg

        async def update(self, *, force=False):
            del force
            assert self.cfg.local.name == "source"
            await asyncio.sleep(0)
            return OpResult(status="success", detail="ok", returncode=0, updated=["root.txt"])

        async def update_paths(self, paths, *, force=False):
            del force
            assert self.cfg.local.name == "source"
            await asyncio.sleep(0)
            return {
                paths[0]: OpResult(
                    status="success",
                    detail="ok",
                    returncode=0,
                    updated=["subset/file.txt"],
                )
            }

        async def prune_local_empty_dirs(self):
            assert self.cfg.local.name == "source"
            await asyncio.sleep(0)

    monkeypatch.setattr(sync_mod, "RsyncMirror", FakeMirror)
    expected_dirs = await run_rsync_phase(cfg=cfg, paths=paths, recorder=recorder)
    assert paths.mirrors / "mirror/source" in expected_dirs
    assert recorder.manifest["results"]["rsync"]["rsync-id"]["mode"] == "update_paths"

    await sync_mod._close_http_caches(caches)
    assert all(cast("Any", cache).closed for cache in caches.values())


@pytest.mark.asyncio
@pytest.mark.medium
async def test_run_rsync_phase_passes_source_port_to_rsync_config(tmp_path: Path, monkeypatch):
    source = SourceDefinition(
        "rsync-id",
        "Mirror",
        "rsync.example.test::module",
        SourceKind.RSYNC,
        local_subpath="mirror/source",
        mirror_mode=MirrorMode.PATHS,
        mirror_paths=("subset",),
        port=33444,
    )
    cfg = EngineConfig(root=tmp_path, sources=[source])
    paths = prepare_paths(tmp_path, cfg)
    recorder = ManifestRecorder(root=tmp_path, cfg=cfg)

    captured_ports: list[int | None] = []

    class FakeMirror:
        def __init__(self, cfg):
            captured_ports.append(cfg.port)
            self.cfg = cfg

        async def update(self, *, force=False):
            del force
            assert self.cfg.port == 33444
            await asyncio.sleep(0)
            return OpResult(status="success", detail="ok", returncode=0, updated=["root.txt"])

        async def update_paths(self, paths, *, force=False):
            del force
            assert self.cfg.port == 33444
            await asyncio.sleep(0)
            return {
                paths[0]: OpResult(
                    status="success",
                    detail="ok",
                    returncode=0,
                    updated=["subset/file.txt"],
                )
            }

        async def prune_local_empty_dirs(self):
            assert self.cfg.port == 33444
            await asyncio.sleep(0)

    monkeypatch.setattr(sync_mod, "RsyncMirror", FakeMirror)

    await run_rsync_phase(cfg=cfg, paths=paths, recorder=recorder)

    assert captured_ports == [33444]


@pytest.mark.asyncio
@pytest.mark.medium
async def test_run_rsync_phase_uses_less_aggressive_flags_for_pdb_mmcif(tmp_path: Path, monkeypatch):
    sources = [
        SourceDefinition(
            "pdb_mmcif",
            "PDB structures",
            "rsync.rcsb.org::ftp/data/structures/divided/",
            SourceKind.RSYNC,
            local_subpath="pdb_structures_all",
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("mmCIF/ab/",),
        ),
        SourceDefinition(
            "pdb_chemical_shifts",
            "PDB Legacy Chemical Shifts",
            "rsync.rcsb.org::ftp/data/structures/divided/",
            SourceKind.RSYNC,
            local_subpath="pdb_structures_all",
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("nmr_chemical_shifts/",),
        ),
    ]
    cfg = EngineConfig(root=tmp_path, sources=sources)
    paths = prepare_paths(tmp_path, cfg)
    recorder = ManifestRecorder(root=tmp_path, cfg=cfg)

    captured: list[tuple[str, bool, bool]] = []

    class FakeMirror:
        def __init__(self, cfg):
            captured.append((cfg.name, cfg.cmd.compress, cfg.cmd.copy_links))
            self.cfg = cfg

        async def update(self, *, force=False):
            del force
            assert self.cfg.name in {"PDB structures", "PDB Legacy Chemical Shifts"}
            await asyncio.sleep(0)
            return OpResult(status="success", detail="ok", returncode=0, updated=["root.txt"])

        async def update_paths(self, paths, *, force=False):
            del force
            assert self.cfg.name in {"PDB structures", "PDB Legacy Chemical Shifts"}
            await asyncio.sleep(0)
            return {
                paths[0]: OpResult(
                    status="success",
                    detail="ok",
                    returncode=0,
                    updated=["subset/file.txt"],
                )
            }

        async def prune_local_empty_dirs(self):
            assert self.cfg.cmd.itemize_changes is True
            await asyncio.sleep(0)

    monkeypatch.setattr(sync_mod, "RsyncMirror", FakeMirror)

    await run_rsync_phase(cfg=cfg, paths=paths, recorder=recorder)

    assert ("PDB structures", False, False) in captured
    assert ("PDB Legacy Chemical Shifts", True, True) in captured


@pytest.mark.asyncio
@pytest.mark.medium
async def test_run_rsync_phase_uses_compact_progress_for_pdb_mmcif_only(tmp_path: Path, monkeypatch):
    sources = [
        SourceDefinition(
            "pdb_mmcif",
            "PDB structures",
            "rsync.rcsb.org::ftp/data/structures/divided/",
            SourceKind.RSYNC,
            local_subpath="pdb_structures_all",
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("mmCIF/ab/",),
        ),
        SourceDefinition(
            "pdb_chemical_shifts",
            "PDB Legacy Chemical Shifts",
            "rsync.rcsb.org::ftp/data/structures/divided/",
            SourceKind.RSYNC,
            local_subpath="pdb_structures_all",
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("nmr_chemical_shifts/",),
        ),
    ]
    cfg = EngineConfig(root=tmp_path, sources=sources, runtime_progress=True)
    paths = prepare_paths(tmp_path, cfg)
    recorder = ManifestRecorder(root=tmp_path, cfg=cfg)

    captured_progress: dict[str, bool] = {}

    class FakeMirror:
        def __init__(self, cfg):
            captured_progress[cfg.name] = cfg.progress
            self.cfg = cfg

        async def update(self, *, force=False):
            del force
            assert self.cfg.name in {"PDB structures", "PDB Legacy Chemical Shifts"}
            await asyncio.sleep(0)
            return OpResult(status="success", detail="ok", returncode=0, updated=["root.txt"])

        async def update_paths(self, paths, *, force=False):
            del force
            assert self.cfg.name in {"PDB structures", "PDB Legacy Chemical Shifts"}
            await asyncio.sleep(0)
            return {
                paths[0]: OpResult(
                    status="success",
                    detail="ok",
                    returncode=0,
                    updated=["subset/file.txt"],
                )
            }

        async def prune_local_empty_dirs(self):
            assert self.cfg.name in {"PDB structures", "PDB Legacy Chemical Shifts"}
            await asyncio.sleep(0)

    monkeypatch.setattr(sync_mod, "RsyncMirror", FakeMirror)
    monkeypatch.setattr(sync_mod, "_discover_existing_pdb_mmcif_buckets", lambda _source: {"mmCIF/ab/"})
    monkeypatch.setattr(sync_mod, "_emit_sync_runtime_inline", lambda _cfg, _text, *, final=False: None)

    await run_rsync_phase(cfg=cfg, paths=paths, recorder=recorder)

    assert captured_progress == {
        "PDB structures": False,
        "PDB Legacy Chemical Shifts": True,
    }


@pytest.mark.asyncio
@pytest.mark.medium
async def test_sync_orchestration_with_stubbed_phases(tmp_path: Path, monkeypatch):
    sources = [
        SourceDefinition("http-id", "HTTP", "https://example.test/data.bin", SourceKind.HTTP),
        SourceDefinition("rest-id", "REST", "https://example.test/data.json", SourceKind.REST),
        SourceDefinition(
            "rsync-id",
            "Mirror",
            "rsync.example.test::module",
            SourceKind.RSYNC,
            local_subpath="mirror/source",
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("subset",),
        ),
    ]
    cfg = EngineConfig(root=tmp_path, sources=sources)

    async def fake_run_http_phase(*, cfg, paths, http_caches, recorder):
        await asyncio.sleep(0)
        recorder.record_http(manifest_key="http-id", entry={"ok": True})

    async def fake_run_rsync_phase(*, cfg, paths, recorder):
        await asyncio.sleep(0)
        recorder.record_rsync(
            manifest_key="rsync-id",
            entry=sync_mod._rsync_manifest_entry(
                cfg.sources[2],
                paths.mirrors / "mirror/source",
                "update_paths",
                {"subset": {"status": "success"}},
                force=False,
                paths=["subset"],
            ),
        )
        return {paths.mirrors / "mirror/source"}

    async def fake_run_derived_tasks(*, cfg, paths, recorder):
        await asyncio.sleep(0)
        recorder.record_derived(name="derived", payload={"ok": True})

    monkeypatch.setattr(sync_mod, "run_http_phase", fake_run_http_phase)
    monkeypatch.setattr(sync_mod, "run_rsync_phase", fake_run_rsync_phase)
    monkeypatch.setattr(sync_mod, "_run_derived_tasks", fake_run_derived_tasks)
    monkeypatch.setattr(sync_mod, "build_http_caches", lambda *, sources, cache_root, rate_root: {})

    async def fake_close_http_caches(http_caches):
        await asyncio.sleep(0)

    monkeypatch.setattr(sync_mod, "_close_http_caches", fake_close_http_caches)

    result = await sync(cfg)
    assert result.ok is True
    assert result.manifest["results"]["derived"]["derived"] == {"ok": True}


@pytest.mark.asyncio
@pytest.mark.medium
async def test_sync_marks_rsync_transport_failures_as_errors(tmp_path: Path, monkeypatch):
    cfg = EngineConfig(
        root=tmp_path,
        sources=[
            SourceDefinition(
                "rsync-id",
                "Mirror",
                "rsync.example.test::module",
                SourceKind.RSYNC,
                local_subpath="mirror/source",
                mirror_mode=MirrorMode.PATHS,
                mirror_paths=("subset",),
            )
        ],
    )

    async def _fake_update_paths(
        self: object, paths: list[str], *, force: bool = False
    ) -> dict[str, OpResult]:
        del self, force
        await asyncio.sleep(0)
        return {
            paths[0]: OpResult(
                status="failed",
                detail="rsync failed",
                returncode=10,
                stderr="socket IO error",
                updated=[],
            )
        }

    monkeypatch.setattr(RsyncMirror, "update_paths", _fake_update_paths)

    result = await sync(cfg)

    assert result.ok is False
    entry = result.manifest["results"]["rsync"]["rsync-id"]
    assert entry["ok"] is False
    assert entry["error"] == "subset: rsync failed"
    assert result.manifest["errors"] == [
        {
            "phase": "rsync",
            "name": "Mirror",
            "source_id": "rsync-id",
            "error": "subset: rsync failed",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.medium
async def test_run_rsync_phase_skips_missing_pdb_mmcif_bucket_dirs(tmp_path: Path, monkeypatch):
    source = SourceDefinition(
        "pdb_mmcif",
        "PDB structures",
        "rsync.rcsb.org::ftp/data/structures/divided/",
        SourceKind.RSYNC,
        local_subpath="pdb_structures_all",
        mirror_mode=MirrorMode.PATHS,
        mirror_paths=("mmCIF/0r/",),
    )
    cfg = EngineConfig(root=tmp_path, sources=[source])
    paths = prepare_paths(tmp_path, cfg)
    recorder = ManifestRecorder(root=tmp_path, cfg=cfg)

    async def _fake_update_paths(
        self: object, paths: list[str], *, force: bool = False
    ) -> dict[str, OpResult]:
        del self, force
        await asyncio.sleep(0)
        return {
            paths[0]: OpResult(
                status="failed",
                detail="rsync failed",
                returncode=23,
                stderr=(
                    'rsync: [sender] change_dir "data/structures/divided/mmCIF/0r" '
                    "(in ftp) failed: No such file or directory (2)\n"
                    "rsync error: some files/attrs were not transferred (see previous errors) "
                    "(code 23) at main.c(1872) [Receiver=3.4.1]"
                ),
                updated=[],
            )
        }

    monkeypatch.setattr(RsyncMirror, "update_paths", _fake_update_paths)

    await run_rsync_phase(cfg=cfg, paths=paths, recorder=recorder)

    entry = cast("dict[str, Any]", recorder.manifest["results"]["rsync"]["pdb_mmcif"])
    assert entry["ok"] is True
    assert recorder.manifest["errors"] == []
    per_path = cast("dict[str, Any]", entry["results"])["mmCIF/0r/"]
    assert per_path["status"] == "success"
    assert per_path["detail"] == "Skipped: remote shard not present"


@pytest.mark.asyncio
@pytest.mark.medium
async def test_run_rsync_phase_prefilters_missing_pdb_mmcif_buckets(tmp_path: Path, monkeypatch):
    source = SourceDefinition(
        "pdb_mmcif",
        "PDB structures",
        "rsync.rcsb.org::ftp/data/structures/divided/",
        SourceKind.RSYNC,
        local_subpath="pdb_structures_all",
        mirror_mode=MirrorMode.PATHS,
        mirror_paths=("mmCIF/0r/", "mmCIF/0s/"),
    )
    cfg = EngineConfig(root=tmp_path, sources=[source], runtime_progress=True)
    paths = prepare_paths(tmp_path, cfg)
    recorder = ManifestRecorder(root=tmp_path, cfg=cfg)

    monkeypatch.setattr(sync_mod, "_discover_existing_pdb_mmcif_buckets", lambda _source: {"mmCIF/0s/"})
    seen_messages: list[str] = []
    monkeypatch.setattr(sync_mod, "_emit_sync_runtime_message", lambda _cfg, text: seen_messages.append(text))

    async def _fake_update_paths(
        self: object, paths: list[str], *, force: bool = False
    ) -> dict[str, OpResult]:
        del self, force
        await asyncio.sleep(0)
        assert paths == ["mmCIF/0s/"]
        return {
            paths[0]: OpResult(
                status="success",
                detail="ok",
                returncode=0,
                updated=["0s/example.cif.gz"],
            )
        }

    monkeypatch.setattr(RsyncMirror, "update_paths", _fake_update_paths)

    await run_rsync_phase(cfg=cfg, paths=paths, recorder=recorder)

    entry = cast("dict[str, Any]", recorder.manifest["results"]["rsync"]["pdb_mmcif"])
    per_path_results = cast("dict[str, Any]", entry["results"])
    assert entry["ok"] is True
    assert cast("dict[str, Any]", per_path_results["mmCIF/0s/"])["status"] == "success"
    assert cast("dict[str, Any]", per_path_results["mmCIF/0r/"])["status"] == "success"
    assert (
        cast("dict[str, Any]", per_path_results["mmCIF/0r/"])["detail"] == "Skipped: remote shard not present"
    )
    assert any("skipping 1 missing remote buckets" in message for message in seen_messages)


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
    monkeypatch.setattr(
        transport_mod, "_preflight_connectivity", lambda _cfg, *, remote: messages.append(remote)
    )
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
def test_incremental_rsync_subdirs_uses_manifest_paths_for_shared_root(tmp_path: Path):
    cfg = EngineConfig(
        root=tmp_path,
        sources=[
            SourceDefinition(
                "pdb_chemical_shifts",
                "PDB Legacy Chemical Shifts",
                "rsync.rcsb.org::ftp/data/structures/all/",
                SourceKind.RSYNC,
                local_subpath="pdb_structures_all",
                mirror_mode=MirrorMode.PATHS,
                mirror_paths=("nmr_chemical_shifts/",),
            ),
            SourceDefinition(
                "pdb_mmcif",
                "PDB structures",
                "rsync.rcsb.org::ftp/data/structures/all/",
                SourceKind.RSYNC,
                local_subpath="pdb_structures_all",
                mirror_mode=MirrorMode.PATHS,
                mirror_paths=("mmcif/",),
            ),
        ],
    )

    manifest: dict[str, Any] = {
        "results": {
            "rsync": {
                "pdb_chemical_shifts": {
                    "ok": True,
                    "request": {
                        "paths": ["nmr_chemical_shifts/"],
                    },
                },
                "pdb_mmcif": {
                    "ok": True,
                    "request": {
                        "paths": ["mmcif/"],
                    },
                },
            }
        }
    }

    assert sync_mod._incremental_rsync_subdirs(cfg=cfg, manifest=cast("Any", manifest)) == [
        "pdb_structures_all/mmcif",
        "pdb_structures_all/nmr_chemical_shifts",
    ]


@pytest.mark.medium
def test_build_incremental_state_uses_touched_subdirs(monkeypatch, tmp_path: Path):
    cfg = EngineConfig(
        root=tmp_path,
        sources=[
            SourceDefinition(
                "pdb_chemical_shifts",
                "PDB Legacy Chemical Shifts",
                "rsync.rcsb.org::ftp/data/structures/all/",
                SourceKind.RSYNC,
                local_subpath="pdb_structures_all",
                mirror_mode=MirrorMode.PATHS,
                mirror_paths=("nmr_chemical_shifts/",),
            )
        ],
    )
    paths = prepare_paths(tmp_path, cfg)
    previous_state_path = tmp_path / cfg.state_filename
    previous_state_path.write_text(
        json.dumps({
            "version": 1,
            "generated_at_unix": 50.0,
            "cache_root": str(tmp_path),
            "mirrors_root": str(paths.mirrors.resolve()),
            "hash_algo": "sha256",
            "manifest_path": None,
            "tree": {"type": "dir", "hash": "root", "file_count": 0, "dir_count": 1},
            "sources": [],
        }),
        encoding="utf-8",
    )
    from efloud.state import MirrorState, MirrorStateNode

    previous_state = MirrorState.from_dict(json.loads(previous_state_path.read_text(encoding="utf-8")))
    assert previous_state is not None
    captured_subdirs: list[str] = []

    def fake_update_hash_tree_for_subdirs(base_tree, mirrors_root, subdirs, *, on_progress=None):
        del mirrors_root, on_progress
        captured_subdirs.extend(subdirs)
        return cast("MirrorStateNode", base_tree)

    monkeypatch.setattr(sync_mod, "update_hash_tree_for_subdirs", fake_update_hash_tree_for_subdirs)

    state = sync_mod._build_incremental_state(
        cfg=cfg,
        paths=paths,
        manifest_path=tmp_path / "log" / "x.json",
        previous_state=previous_state,
        touched_subdirs=["pdb_structures_all/nmr_chemical_shifts"],
    )

    assert state.sources[0].source_id == "pdb_chemical_shifts"
    assert captured_subdirs == ["pdb_structures_all/nmr_chemical_shifts"]


@pytest.mark.medium
def test_record_manifest_hash_state_persists_source_counts(tmp_path: Path):
    source = SourceDefinition(
        "pdb_unified_nmr",
        "PDB Unified NMR Data",
        "rsync.rcsb.org::ftp/data/structures/divided/",
        SourceKind.RSYNC,
        local_subpath="pdb_structures_all",
        mirror_mode=MirrorMode.PATHS,
        mirror_paths=("nmr_data/",),
    )
    cfg = EngineConfig(root=tmp_path, sources=[source], state_filename="mirror-state.json")
    paths = prepare_paths(tmp_path, cfg)
    star_path = paths.mirrors / "pdb_structures_all" / "nmr_data" / "ab" / "1abc_nmr-data.str.gz"
    star_path.parent.mkdir(parents=True, exist_ok=True)
    star_path.write_text("payload", encoding="utf-8")

    recorder = ManifestRecorder(root=paths.root, cfg=cfg)
    recorder.record_rsync(
        manifest_key="pdb_unified_nmr",
        entry={
            "source_id": "pdb_unified_nmr",
            "request": {"paths": ["nmr_data/"]},
        },
    )

    from efloud.state import MirrorState

    state = MirrorState.build(
        cache_root=paths.root,
        mirrors_root=paths.mirrors,
        manifest_path=paths.log / "sync-manifest.json",
        sources_info=[("pdb_unified_nmr", "pdb_structures_all")],
    )

    sync_mod._record_manifest_hash_state(cfg=cfg, paths=paths, recorder=recorder, state=state)

    manifest_payload = cast("dict[str, Any]", recorder.manifest)
    mirror_state = cast("dict[str, Any]", manifest_payload["mirror_state"])
    assert mirror_state["root"]["file_count"] == 1
    source_payload = cast(
        "dict[str, Any]", recorder.manifest["results"]["rsync"]["pdb_unified_nmr"]["integrity"]
    )
    assert source_payload["source_root"]["file_count"] == 1
    assert source_payload["subtrees"]["nmr_data"]["file_count"] == 1


@pytest.mark.asyncio
@pytest.mark.small
async def test_prepare_rsync_paths_skips_remote_discovery_for_single_pdb_mmcif_bucket(
    tmp_path: Path,
    monkeypatch,
):
    source = SourceDefinition(
        "pdb_mmcif",
        "PDB structures",
        "rsync.rcsb.org::ftp/data/structures/divided/",
        SourceKind.RSYNC,
        local_subpath="pdb_structures_all",
        mirror_mode=MirrorMode.PATHS,
        mirror_paths=("mmCIF/ab/",),
    )
    cfg = EngineConfig(root=tmp_path, sources=[source])

    called = {"discover": False}

    def fake_discover(_source: SourceDefinition) -> set[str]:
        called["discover"] = True
        return {"mmCIF/ab/"}

    monkeypatch.setattr(sync_mod, "_discover_existing_pdb_mmcif_buckets", fake_discover)

    mirror_paths, synthetic = await sync_mod._prepare_rsync_paths_for_source(
        source=source,
        mirror_paths=("mmCIF/ab/",),
        cfg=cfg,
    )

    assert mirror_paths == ("mmCIF/ab/",)
    assert synthetic == {}
    assert called["discover"] is False


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
                'rsync: [sender] change_dir "data/structures/all/mmcif" '
                "(in ftp) failed: No such file or directory (2)"
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

    assert (
        transport_mod._remote_display_target("rsync.rcsb.org::ftp_data/structures/all/")
        == "rsync.rcsb.org:873"
    )
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
