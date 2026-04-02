from __future__ import annotations

import json
import sqlite3
from enum import StrEnum
from typing import TYPE_CHECKING, cast

import pytest

from efloud.health import build_mirror_health_summary
from efloud.indexing import IndexDefinition, IndexRegistry, JsonTtlIndex
from efloud.models import EngineConfig, SyncResult
from efloud.query import index_payload, query_target, root_payload, store_payload
from efloud.registry import SourceDefinition, SourceKind
from efloud.status import collect_status_payload, derived_summary, describe_source_status, source_status_rows
from efloud.store_inspection import rel_to_root
from efloud.summary import build_summary

if TYPE_CHECKING:
    from pathlib import Path

    from efloud.models import NormalizedManifest

pytestmark = [pytest.mark.unit, pytest.mark.medium]


class ForeignSourceKind(StrEnum):
    HTTP = "HTTP"
    REST = "REST"
    REST_BASE = "REST_BASE"
    RSYNC = "RSYNC"


@pytest.fixture
def cfg(tmp_path: Path):
    sources = [
        SourceDefinition("http-id", "HTTP Source", "https://example.test/data.json", SourceKind.HTTP),
        SourceDefinition(
            "rsync-id",
            "Mirror Source",
            "rsync.example.test::module",
            SourceKind.RSYNC,
            local_subpath="mirror/source",
        ),
        SourceDefinition("fanout-id", "Fanout", "https://api.example.test", SourceKind.REST_BASE),
    ]
    registry = IndexRegistry([
        IndexDefinition(
            index_id="alpha",
            filename="indexes/alpha.json",
            ttl_seconds=60,
            build=lambda *, root: JsonTtlIndex(fetched_at=100.0, ttl_seconds=60, payload={"root": root.name}),
            parser=JsonTtlIndex,
            description="Alpha index",
        )
    ])
    return EngineConfig(
        root=tmp_path, sources=sources, index_registry=registry, source_aliases={"http-id": ("legacy-http",)}
    )


def _write_manifest(root: Path, cfg: EngineConfig) -> Path:
    manifest_dir = root / cfg.log_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
        "root": str(root),
        "errors": [{"error": "broken source"}],
        "results": {
            "http": {
                "http-id": {
                    "ok": True,
                    "status_code": 200,
                    "dest": str(root / cfg.http_dir / "data.json"),
                    "url": "https://example.test/data.json",
                }
            },
            "rsync": {
                "rsync-id": {
                    "ok": False,
                    "local": str(root / cfg.mirrors_dir / "mirror/source"),
                    "mode": "update",
                    "results": {
                        "update": {
                            "status": "failed",
                            "attempt_count": 2,
                            "attempt_errors": ["failed to connect", "failed to connect"],
                        }
                    },
                }
            },
            "derived": {
                "fanout": {
                    "source_id": "fanout-id",
                    "ok": 1,
                    "err": 0,
                    "count": 2,
                    "dest": str(root / "fanout"),
                    "manifest": str(manifest_dir / cfg.manifest_filename),
                    "request": {
                        "base_url": "https://api.example.test",
                        "fanout_root": str(root / "fanout"),
                    },
                }
            },
        },
    }
    path = manifest_dir / cfg.manifest_filename
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_build_summary_and_status_helpers(cfg: EngineConfig, tmp_path: Path):
    manifest_path = _write_manifest(tmp_path, cfg)
    result = SyncResult(
        ok=False,
        root=tmp_path,
        manifest_path=manifest_path,
        manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
    )

    summary = build_summary(result)
    assert summary["ok"] is False
    assert summary["http"]["core"]["ok_count"] == 1
    assert summary["rsync"]["core"]["error_count"] == 1
    assert summary["rsync"]["entries"][0]["status"] == "failed"
    assert summary["rsync"]["entries"][0]["updated_count"] == 0
    assert summary["rsync"]["entries"][0]["retry_count"] == 1
    assert summary["rsync"]["entries"][0]["request_count"] == 2

    http_status = describe_source_status(cfg.sources[0], result.manifest["results"]["http"]["http-id"])
    rsync_status = describe_source_status(cfg.sources[1], result.manifest["results"]["rsync"]["rsync-id"])
    rest_status = describe_source_status(cfg.sources[2], result.manifest["results"]["derived"]["fanout"])

    assert http_status == (
        "ok",
        {"description": "HTTP Source", "status_code": 200, "dest": str(tmp_path / "http" / "data.json")},
    )
    assert rsync_status[0] == "error"
    assert rsync_status[1]["updates"] == [{"name": "update", "status": "failed"}]
    assert rest_status[1]["base_url"] == "https://api.example.test"

    derived = derived_summary(result.manifest)
    assert derived == [
        {
            "name": "fanout",
            "dest": str(tmp_path / "fanout"),
            "count": 2,
            "ok": 1,
            "err": 0,
            "manifest": str(manifest_path),
            "base_url": "https://api.example.test",
            "fanout_root": str(tmp_path / "fanout"),
        }
    ]

    rows = source_status_rows(result.manifest, cfg.sources, aliases=cfg.source_aliases)
    assert [row["status"] for row in rows] == ["ok", "error", "ok"]


def test_health_and_collect_status_payload(cfg: EngineConfig, tmp_path: Path):
    manifest_path = _write_manifest(tmp_path, cfg)
    mirror_root = tmp_path / cfg.mirrors_dir / "mirror/source"
    mirror_root.mkdir(parents=True)
    (mirror_root / ".mirror_meta.json").write_text(
        json.dumps({"version": 1, "paths": {".": {"updated_at_unix": 123, "updated": ["x"]}}}),
        encoding="utf-8",
    )

    health = build_mirror_health_summary(
        {"rsync-id": mirror_root}, json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    assert health.mirror_timestamps == {"rsync-id": 123.0}
    assert health.missing_roots == ()
    assert health.manifest_errors == ("broken source",)

    payload, warnings = collect_status_payload(cfg)
    assert warnings == []
    assert payload["source_count"] == 3
    assert payload["index_count"] == 1
    assert payload["health"]["manifest_errors"] == ["broken source"]


def test_store_index_root_and_query_payloads(cfg: EngineConfig, tmp_path: Path):
    _write_manifest(tmp_path, cfg)
    source_file = tmp_path / cfg.http_dir / "data.json"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(json.dumps({"dest": str(source_file)}), encoding="utf-8")
    state_path = tmp_path / cfg.state_filename
    state_path.write_text(
        json.dumps({
            "version": 1,
            "generated_at_unix": 100.0,
            "cache_root": str(tmp_path),
            "mirrors_root": str(tmp_path / cfg.mirrors_dir),
            "hash_algo": "sha256",
            "manifest_path": str(tmp_path / cfg.log_dir / cfg.manifest_filename),
            "tree": {"type": "dir", "hash": "abc"},
            "sources": [],
        }),
        encoding="utf-8",
    )

    cache_dir = tmp_path / cfg.cache_dir / cfg.http_cache_dir
    cache_dir.mkdir(parents=True)
    sqlite_path = cache_dir / "cache.sqlite"
    con = sqlite3.connect(sqlite_path)
    con.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    con.execute("INSERT INTO meta VALUES ('a', 'b')")
    con.commit()
    con.close()

    assert cfg.index_registry is not None
    cfg.index_registry.build("alpha", root=tmp_path)

    manifest_store = store_payload("sync_manifest", cfg=cfg)
    state_store = store_payload("mirror_state", cfg=cfg)
    rate_store = store_payload("rate_limits_dir", cfg=cfg)
    sqlite_store = store_payload("http_cache_sqlite", cfg=cfg)
    index_info = index_payload("alpha", cfg=cfg)
    root_info = root_payload(cfg)
    source_info = query_target("source:http-id#/dest", cfg=cfg)

    assert manifest_store["metadata"]["results_sections"] == ["derived", "http", "rsync"]
    assert state_store["metadata"]["hash_algo"] == "sha256"
    assert rate_store["store_status"] == "missing"
    assert sqlite_store["metadata"] == {"a": "b"}
    assert sqlite_store["root_relative_path"] == rel_to_root(sqlite_path, tmp_path)
    assert index_info["status"]["present"] is True
    assert root_info["target_kind"] == "root"
    assert source_info["locator"]["value"] == str(source_file)
    assert source_info["locator"]["resolved_locator"] in {"/dest", "#/dest"}

    with pytest.raises(ValueError, match="Unknown store identifier"):
        store_payload("missing", cfg=cfg)
    with pytest.raises(ValueError, match="No index registry configured"):
        index_payload("alpha", cfg=EngineConfig(root=tmp_path, sources=[]))
    with pytest.raises(ValueError, match="Unsupported query target"):
        query_target("bad", cfg=cfg)


def test_status_helpers_accept_foreign_but_value_compatible_source_kind_enum(tmp_path: Path):
    foreign_rsync = SourceDefinition(
        "foreign-rsync",
        "Foreign Mirror",
        "rsync.example.test::module",
        cast("SourceKind", ForeignSourceKind.RSYNC),
        local_subpath="mirror/source",
    )
    manifest = cast(
        "NormalizedManifest",
        {
            "results": {
                "http": {},
                "rsync": {
                    "foreign-rsync": {
                        "ok": True,
                        "local": str(tmp_path / "mirrors" / "mirror/source"),
                        "mode": "update",
                        "results": {"update": {"status": "success"}},
                    }
                },
                "derived": {},
            },
        },
    )

    rows = source_status_rows(manifest, [foreign_rsync])

    assert rows == [
        {
            "source_id": "foreign-rsync",
            "kind": "RSYNC",
            "status": "ok",
            "details": {
                "description": "Foreign Mirror",
                "local": str(tmp_path / "mirrors" / "mirror/source"),
                "mode": "update",
                "updates": [{"name": "update", "status": "success"}],
            },
        }
    ]
