from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from efloud.models import NormalizedManifest, SyncResult
from efloud.planning import SyncRequest
from efloud.policy import DefaultSyncPolicy, RoleDrivenSyncPolicy
from efloud.registry import RsyncMode, SourceDefinition, SourceKind
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
from efloud.sources import CollectionSource, HttpSource, RestSource, RsyncSource

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
            rsync_mode=RsyncMode.PATHS,
            rsync_paths=("subset",),
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
    assert manifest_entry_for_source_id(manifest, "http-id", aliases=aliases) == manifest["results"]["http"]["http-id"]
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
    assert iter_manifest_entries(manifest, sources, aliases=aliases)[2][1] == manifest["results"]["derived"]["fanout"]


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
    assert manifest_entry_for_source_aliasable(manifest, sources[1]) == manifest["results"]["rsync"]["rsync-id"]
    assert materialized_path_for_source(manifest, sources[2]) == tmp_path / "fanout"
    assert manifest_entry_for_source(manifest, sources[0]) == manifest["results"]["http"]["http-id"]
    assert manifest_entry_for_source(None, None) is None


@pytest.mark.small
def test_default_sync_policy_uses_request_refresh_and_typed_rsync_scope() -> None:
    http = HttpSource("http-id", "https://example.test/file")
    rsync = RsyncSource("rsync-id", "rsync.example.test::module", paths=("subset",))
    request = SyncRequest(refresh_source_ids=(http.id,))

    assert DefaultSyncPolicy.refresh_decision(http, request, snapshot=None).refresh is True
    assert DefaultSyncPolicy.refresh_decision(rsync, request, snapshot=None).refresh is False

    refresh_all = SyncRequest(refresh=True)
    assert DefaultSyncPolicy.refresh_decision(rsync, refresh_all, snapshot=None).refresh is True

    assert DefaultSyncPolicy.source_scope(rsync, request) == ("subset",)
    assert DefaultSyncPolicy.source_scope(http, request) == ()


@pytest.mark.small
def test_role_driven_sync_policy_overrides_refresh_by_role_and_collection() -> None:
    holdings = HttpSource(
        "holdings-id",
        "https://example.test/holdings",
        role="holdings",
    )
    mappings = RestSource(
        "mapping-id",
        "https://example.test/map",
        role="mappings_exact",
    )
    collection = CollectionSource(
        "core-id",
        "https://example.test/core",
    )
    mirror = RsyncSource(
        "mirror-id",
        "rsync.example.test::mirror",
        paths=("subset",),
    )
    policy = RoleDrivenSyncPolicy(
        role_refresh={"holdings": True, "mappings_exact": False},
        collection_refresh=True,
    )
    request = SyncRequest(refresh_source_ids=(mirror.id,))

    assert policy.refresh_decision(holdings, request, snapshot=None).refresh is True
    assert policy.refresh_decision(mappings, request, snapshot=None).refresh is False
    assert policy.refresh_decision(collection, request, snapshot=None).refresh is True
    assert policy.refresh_decision(mirror, request, snapshot=None).refresh is True
    assert policy.source_scope(mirror, request) == ("subset",)
