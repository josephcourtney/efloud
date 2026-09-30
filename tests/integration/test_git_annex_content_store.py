from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from efloud.content.git_annex import GitAnnexCommandError, GitAnnexContentStore
from efloud.git_commands import run_git

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


def test_annex_drop_fails_closed_without_verified_other_copy(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")
    key = store.ingest_bytes(b"only copy")

    with pytest.raises(GitAnnexCommandError):
        store.drop(key)

    assert store.has_content(key)
    assert store.verify(key)


def test_annex_drop_and_reacquire_preserve_key_identity(tmp_path: Path) -> None:
    primary = GitAnnexContentStore.initialize(tmp_path / "primary", description="primary")
    backup = GitAnnexContentStore.initialize(tmp_path / "backup", description="backup")
    run_git(primary.root, "remote", "add", "backup", backup.root.as_posix())
    run_git(backup.root, "remote", "add", "primary", primary.root.as_posix())

    key = primary.ingest_bytes(b"portable payload")
    run_git(primary.root, "annex", "copy", "--to=backup", f"--key={key}")
    assert backup.has_content(key)

    primary.drop(key)
    assert not primary.has_content(key)
    with pytest.raises(FileNotFoundError):
        primary.open(key)

    primary.get(key)
    assert primary.has_content(key)
    assert primary.verify(key)
    with primary.open(key) as stream:
        recovered_bytes = stream.read()
    assert recovered_bytes == b"portable payload"

    recovered = tmp_path / "recovered.dat"
    recovered.write_bytes(recovered_bytes)
    assert primary.calculate_key(recovered) == key
