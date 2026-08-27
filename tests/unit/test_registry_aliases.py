from __future__ import annotations

import pytest

from efloud.registry import (
    MirrorMode,
    SourceDefinition,
    SourceKind,
    iter_upstream_sources,
    source_by_id,
    source_ids,
    source_ids_for_kind,
)
from efloud.source_aliases import SourceAliasResolver, source_by_id_or_alias

pytestmark = [pytest.mark.unit]


@pytest.fixture
def sources():
    return [
        SourceDefinition("http-one", "HTTP One", "https://example.test/a", SourceKind.HTTP),
        SourceDefinition(
            "mirror-one",
            "Mirror One",
            "rsync.example.test::module",
            SourceKind.RSYNC,
            local_subpath="mirrors/one",
            mirror_mode=MirrorMode.PATHS,
            mirror_paths=("a/b",),
        ),
        SourceDefinition("rest-base", "REST Base", "https://api.example.test", SourceKind.REST_BASE),
    ]


@pytest.mark.small
def test_registry_helpers_return_expected_source_views(sources):
    assert source_ids(sources) == ("http-one", "mirror-one", "rest-base")
    assert source_by_id("mirror-one", sources) is sources[1]
    assert source_by_id("missing", sources) is None
    assert tuple(iter_upstream_sources(sources)) == tuple(sources)
    assert source_ids_for_kind(SourceKind.RSYNC, sources) == ["mirror-one"]


@pytest.mark.small
def test_source_alias_resolver_handles_declared_and_reverse_aliases(sources):
    resolver = SourceAliasResolver({
        "http-one": ("legacy-http", "alias-http"),
        "mirror-one": ("legacy-mirror",),
    })

    assert resolver.aliases == {
        "http-one": ("legacy-http", "alias-http"),
        "mirror-one": ("legacy-mirror",),
    }
    assert resolver.candidates("http-one") == ("http-one", "legacy-http", "alias-http")
    assert resolver.candidates("legacy-http") == ("legacy-http", "http-one")
    assert resolver.resolve_id("legacy-mirror", sources) == "mirror-one"
    assert resolver.source_by_id("alias-http", sources) is sources[0]
    assert resolver.source_by_id("missing", sources) is None


@pytest.mark.small
def test_source_by_id_or_alias_uses_alias_map(sources):
    aliases = {"http-one": ("legacy-http",)}

    assert source_by_id_or_alias("legacy-http", sources, aliases) is sources[0]
    assert source_by_id_or_alias("mirror-one", sources, aliases) is sources[1]
    assert source_by_id_or_alias("missing", sources, aliases) is None
