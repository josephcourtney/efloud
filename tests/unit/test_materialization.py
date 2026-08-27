from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from efloud.materialization import http_dest_for_source_url, http_dests_for_source_urls

if TYPE_CHECKING:
    from pathlib import Path


class _SyncResult:
    def __init__(self, *, root: Path, manifest: dict[str, object]) -> None:
        self.root = root
        self.manifest_path = None
        self.manifest = manifest


@pytest.mark.small
def test_http_dest_for_source_url_returns_matching_dest(tmp_path: Path) -> None:
    dest = tmp_path / "http" / "holdings.json.gz"
    sync_res = _SyncResult(
        root=tmp_path,
        manifest={
            "results": {
                "http": {
                    "holdings": {
                        "url": "https://example.test/holdings.json.gz",
                        "dest": str(dest),
                    }
                }
            }
        },
    )

    path = http_dest_for_source_url(sync_res, "https://example.test/holdings.json.gz")
    assert path == dest


@pytest.mark.small
def test_http_dests_for_source_urls_returns_ordered_results(tmp_path: Path) -> None:
    a_dest = tmp_path / "http" / "a.json"
    b_dest = tmp_path / "http" / "b.json"
    sync_res = _SyncResult(
        root=tmp_path,
        manifest={
            "results": {
                "http": {
                    "a": {
                        "url": "https://example.test/a.json",
                        "dest": str(a_dest),
                    },
                    "b": {
                        "url": "https://example.test/b.json",
                        "dest": str(b_dest),
                    },
                }
            }
        },
    )

    a_path, b_path = http_dests_for_source_urls(
        sync_res,
        ("https://example.test/a.json", "https://example.test/b.json"),
    )

    assert a_path == a_dest
    assert b_path == b_dest
