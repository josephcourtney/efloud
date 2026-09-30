from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from efloud.git_commands import run_git
from efloud.tree.git import GitTreeStore
from efloud.tree.protocol import TreeBlob

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.medium]


def test_git_tree_is_canonical_and_preserves_portable_paths(tmp_path: Path) -> None:
    store = GitTreeStore.initialize(tmp_path / "repository")
    entries = (
        TreeBlob("nested/with space.txt", b"alpha"),
        TreeBlob("unicode/δ.bin", b"beta", mode="100755"),
        TreeBlob("link", b"nested/with space.txt", mode="120000"),
    )

    first = store.write_tree(entries)
    reordered = store.write_tree(tuple(reversed(entries)))

    assert reordered == first
    listed = store.list_tree(first)
    assert [(entry.relative_path, entry.mode, entry.object_type) for entry in listed] == [
        ("link", "120000", "blob"),
        ("nested/with space.txt", "100644", "blob"),
        ("unicode/δ.bin", "100755", "blob"),
    ]

    changed = store.write_tree((
        TreeBlob("nested/with space.txt", b"changed"),
        entries[1],
        entries[2],
    ))
    assert changed != first


def test_git_tree_commits_are_retained_as_linear_ref_history(tmp_path: Path) -> None:
    store = GitTreeStore.initialize(tmp_path / "repository")
    ref = "refs/efloud/sources/example"

    first_tree = store.write_tree((TreeBlob("item.txt", b"first"),))
    first_commit = store.commit_tree(first_tree, ref=ref, message="first snapshot")

    second_tree = store.write_tree((TreeBlob("item.txt", b"second"),))
    second_commit = store.commit_tree(second_tree, ref=ref, message="second snapshot")

    assert second_commit != first_commit
    assert run_git(store.root, "rev-parse", ref).stdout.strip() == str(second_commit)
    assert run_git(store.root, "show", "-s", "--format=%P", str(second_commit)).stdout.strip() == str(first_commit)
    assert [entry.relative_path for entry in store.list_tree(second_commit)] == ["item.txt"]
