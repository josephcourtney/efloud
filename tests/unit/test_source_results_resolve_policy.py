from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from efloud.models import EngineConfig, NormalizedManifest, SyncResult
from efloud.policy import DefaultSyncPolicy, RoleDrivenSyncPolicy
from efloud.registry import MirrorMode, SourceDefinition, SourceKind
from efloud.resolve import (
    manifest_entry_for_source,
    manifest_entry_for_source_aliasable,
    manifest_http_dest_for_url,
    materialized_path_for_source,
    mirror_dir,
    mirror_root_subdir_for_source,
)
from efloud.source_results import (
    iter_manifest_entries,
    local_materialized_path,
    manifest_entry_for_source_id,
    manifest_section_for_kind,
    source_status_hint,
)
from efloud.source_results import (
    manifest_entry_for_source as manifest_entry_for_source_result,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture
def sources():
    return [
        SourceDefinition("http-id", "HTTP", "https://example.test/file", SourceKind.HTTP),
        SourceDefinition(
            "rsync-id",
            "Mirror",
            "rsync.example.test::module",
            SourceKind.RSYNC,
            local_subpath="group/source",
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("subset",),
        ),
        SourceDefinition("derived-id", "Derived", "https://api.example.test", SourceKind.REST_BASE),
    ]


@pytest.fixture
def manifest(tmp_path: Path) -> NormalizedManifest:
    return {
        "version": 1,
        "root": str(tmp_path),
        "errors": [],
        "results": {
            "http": {
                "http-id": {
                    "ok": True,
                    "dest": str(tmp_path / "http.json"),
                    "url": "https://example.test/file",
                },
                "legacy-http": {"ok": True, "dest": str(tmp_path / "legacy.json")},
            },
            "rsync": {
                "rsync-id": {"ok": False, "local": str(tmp_path / "mirror")},
            },
            "derived": {
                "fanout": {
                    "source_id": "derived-id",
                    "request": {"fanout_root": str(tmp_path / "fanout")},
                    "err": 0,
                }
            },
        },
    }


@pytest.mark.small
def test_manifest_section_and_entry_helpers_resolve_sources_and_aliases(sources, manifest):
    aliases = {"http-id": ("legacy-http",)}

    assert manifest_section_for_kind(SourceKind.HTTP) == "http"
    assert manifest_section_for_kind(SourceKind.REST) == "http"
    assert manifest_section_for_kind(SourceKind.RSYNC) == "rsync"
    assert manifest_section_for_kind(SourceKind.REST_BASE) == "derived"

    assert manifest_entry_for_source_id(manifest, "http-id") == manifest["results"]["http"]["http-id"]
    assert (
        manifest_entry_for_source_id(manifest, "http-id", aliases=aliases)
        == manifest["results"]["http"]["http-id"]
    )
    assert (
        manifest_entry_for_source_id(manifest, "legacy-http", aliases=aliases)
        == manifest["results"]["http"]["legacy-http"]
    )
    assert (
        manifest_entry_for_source_id(manifest, "derived-id", kind=SourceKind.REST_BASE)
        == manifest["results"]["derived"]["fanout"]
    )
    assert manifest_entry_for_source_id(None, "http-id") is None

    assert (
        manifest_entry_for_source_result(manifest, sources[0], aliases=aliases)
        == manifest["results"]["http"]["http-id"]
    )
    assert (
        iter_manifest_entries(manifest, sources, aliases=aliases)[2][1]
        == manifest["results"]["derived"]["fanout"]
    )


@pytest.mark.small
def test_local_materialized_path_and_status_hint_cover_supported_shapes(tmp_path: Path):
    assert local_materialized_path({"dest": str(tmp_path / "a")}) == tmp_path / "a"
    assert local_materialized_path({"local": str(tmp_path / "b")}) == tmp_path / "b"
    assert local_materialized_path({"request": {"fanout_root": str(tmp_path / "c")}}) == tmp_path / "c"
    assert local_materialized_path(None) is None

    assert source_status_hint(None) == "missing"
    assert source_status_hint({"ok": True}) == "ok"
    assert source_status_hint({"ok": False}) == "error"
    assert source_status_hint({"err": 0}) == "ok"
    assert source_status_hint({"err": 2}) == "error"
    assert source_status_hint({"error": "boom"}) == "error"
    assert source_status_hint({"dest": "x"}) == "present"


@pytest.mark.small
def test_resolve_helpers_locate_mirror_and_materialized_paths(sources, manifest, tmp_path: Path):
    sync_result = SyncResult(ok=True, root=tmp_path, manifest_path=None, manifest=manifest)

    assert mirror_dir(tmp_path, "group") == tmp_path / "mirrors" / "group"
    assert mirror_root_subdir_for_source(sources[1]) == "group"
    assert mirror_root_subdir_for_source(sources[0]) is None
    assert manifest_http_dest_for_url(sync_result, "https://example.test/file") == tmp_path / "http.json"
    assert manifest_http_dest_for_url(sync_result, "https://missing.test") is None
    assert (
        manifest_entry_for_source_aliasable(manifest, sources[1]) == manifest["results"]["rsync"]["rsync-id"]
    )
    assert materialized_path_for_source(manifest, sources[2]) == tmp_path / "fanout"
    assert manifest_entry_for_source(manifest, sources[0]) == manifest["results"]["http"]["http-id"]
    assert manifest_entry_for_source(None, None) is None


@pytest.mark.small
def test_default_sync_policy_uses_refresh_flags_and_rsync_paths(tmp_path: Path, sources):
    cfg = EngineConfig(root=tmp_path, sources=sources, refresh_http=True, refresh_rsync=False)

    assert DefaultSyncPolicy.should_refresh(sources[0], cfg) is True
    assert DefaultSyncPolicy.should_refresh(sources[1], cfg) is False

    refresh_all_cfg = EngineConfig(root=tmp_path, sources=sources, refresh_all=True)
    assert DefaultSyncPolicy.should_refresh(sources[1], refresh_all_cfg) is True

    assert DefaultSyncPolicy.rsync_paths_for_source(
        source=sources[1], cache_root=tmp_path, manifest=None
    ) == ("subset",)
    assert (
        DefaultSyncPolicy.rsync_paths_for_source(source=sources[0], cache_root=tmp_path, manifest=None)
        is None
    )


@pytest.mark.small
def test_role_driven_sync_policy_overrides_refresh_by_role_and_rest_base(tmp_path: Path):
    sources = [
        SourceDefinition(
            "holdings-id",
            "Holdings",
            "https://example.test/holdings",
            SourceKind.HTTP,
            role="holdings",
        ),
        SourceDefinition(
            "mapping-id",
            "Mappings",
            "https://example.test/map",
            SourceKind.REST,
            role="mappings_exact",
        ),
        SourceDefinition(
            "core-id",
            "Core",
            "https://example.test/core",
            SourceKind.REST_BASE,
        ),
        SourceDefinition(
            "mirror-id",
            "Mirror",
            "rsync.example.test::mirror",
            SourceKind.RSYNC,
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("subset",),
        ),
    ]
    policy = RoleDrivenSyncPolicy(
        http_role_refresh={"holdings": True, "mappings_exact": False},
        rest_base_refresh=True,
        rsync_mode=MirrorMode.PATHS,
    )
    cfg = EngineConfig(root=tmp_path, sources=sources, refresh_http=False, refresh_rsync=True)

    assert policy.should_refresh(sources[0], cfg) is True
    assert policy.should_refresh(sources[1], cfg) is False
    assert policy.should_refresh(sources[2], cfg) is True
    assert policy.should_refresh(sources[3], cfg) is True
    assert policy.rsync_paths_for_source(source=sources[3], cache_root=tmp_path, manifest=None) == ("subset",)
