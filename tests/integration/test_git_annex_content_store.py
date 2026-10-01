from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from efloud.content.git_annex import GitAnnexContentStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.skipif(shutil.which("git-annex") is None, reason="git-annex is not installed"),
]


def test_annex_ingest_uses_content_only_key_and_preserves_source(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")
    first = tmp_path / "first.dat"
    second = tmp_path / "different-name.bin"
    first.write_bytes(b"payload")
    second.write_bytes(b"payload")

    first_key = store.ingest_path(first)
    second_key = store.ingest_path(second)

    assert first_key == second_key
    assert str(first_key).startswith("SHA256-")
    content = store.content_ref(first_key, media_type="application/octet-stream")
    assert str(content.content_id).startswith("sha256:")
    assert content.byte_size == len(b"payload")
    assert content.custody_key == str(first_key)
    assert first.read_bytes() == b"payload"
    assert second.read_bytes() == b"payload"
    assert store.has_content(first_key)
    assert store.verify(first_key)
    with store.open(first_key) as stream:
        assert stream.read() == b"payload"


def test_annex_ingest_bytes_deduplicates(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")

    first_key = store.ingest_bytes(b"payload")
    duplicate_key = store.ingest_bytes(b"payload")
    assert duplicate_key == first_key

    assert store.has_content(first_key)
    assert store.verify(first_key)


def test_repository_content_reference_survives_reopen(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    store = GitAnnexContentStore.open_or_initialize(root)
    key = store.ingest_bytes(b"payload")
    first = store.content_ref(key)
    reopened = GitAnnexContentStore.open_or_initialize(root)
    second = reopened.content_ref(key)
    assert second == first
    assert reopened.has_content(key)
