from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from efloud.state import (
    HASH_ALGORITHM,
    MirrorSourceState,
    MirrorState,
    MirrorStateNode,
    build_hash_tree,
    compare_hash_trees,
    load_mirror_state,
    node_at_path,
    update_hash_tree_for_subdirs,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def _write_tree(root: Path) -> None:
    (root / "group").mkdir(parents=True, exist_ok=True)
    (root / "group" / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")


def test_mirror_state_node_and_source_state_round_trip():
    node = MirrorStateNode("file", "abc", 1, 0)
    assert MirrorStateNode.from_dict(node.to_dict()) == node
    assert MirrorStateNode.from_dict({"type": "bad", "hash": "x"}) is None
    assert MirrorStateNode.from_dict({"type": "file", "hash": "legacy"}) == MirrorStateNode(
        "file",
        "legacy",
        1,
        0,
    )

    source = MirrorSourceState("src", "group", "abc")
    assert MirrorSourceState.from_dict(source.to_dict()) == source
    assert MirrorSourceState.from_dict({"source_id": 1, "local_subdir": "group"}) is None


def test_build_hash_tree_node_lookup_and_diffing(tmp_path: Path):
    _write_tree(tmp_path)
    tree = build_hash_tree(tmp_path)
    assert tree is not None
    assert tree.path_type == "dir"
    assert tree.file_count == 2
    assert tree.dir_count >= 2
    assert node_at_path(tree, "group/a.txt") is not None
    assert node_at_path(tree, "") == tree
    assert node_at_path(tree, "missing") is None

    other = build_hash_tree(tmp_path)
    assert compare_hash_trees(tree, other) == []

    (tmp_path / "group" / "a.txt").write_text("changed", encoding="utf-8")
    changed = build_hash_tree(tmp_path)
    diffs = compare_hash_trees(tree, changed, max_diffs=2)
    assert diffs[0] == "hash mismatch at ."
    assert any("group" in diff or "a.txt" in diff for diff in diffs)


def test_update_hash_tree_for_subdirs_replaces_only_requested_subtrees(tmp_path: Path):
    _write_tree(tmp_path)
    base = build_hash_tree(tmp_path)
    assert base is not None

    (tmp_path / "group" / "a.txt").write_text("updated", encoding="utf-8")
    updated = update_hash_tree_for_subdirs(base, tmp_path, ["group"])

    assert updated.hash != base.hash
    assert node_at_path(updated, "group/a.txt") is not None
    assert node_at_path(updated, "b.txt") == node_at_path(base, "b.txt")


def test_build_hash_tree_reports_progress(tmp_path: Path):
    _write_tree(tmp_path)
    events: list[tuple[int, int, str]] = []

    def on_progress(files: int, dirs: int, current_path: Path) -> None:
        events.append((files, dirs, current_path.name))

    tree = build_hash_tree(tmp_path, on_progress=on_progress)

    assert tree is not None
    assert events
    assert any(name == "a.txt" for _, _, name in events)
    assert any(name == "group" for _, _, name in events)
    assert events[-1][0] == 2
    assert events[-1][1] >= 2


def test_mirror_state_build_to_from_dict_and_load(tmp_path: Path, monkeypatch):
    mirrors = tmp_path / "mirrors"
    _write_tree(mirrors)
    manifest_path = tmp_path / "log" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("efloud.state.time.time", lambda: 123.5)
    state = MirrorState.build(
        cache_root=tmp_path,
        mirrors_root=mirrors,
        manifest_path=manifest_path,
        sources_info=[("src-a", "group"), ("src-b", "missing")],
    )

    assert state.version == 1
    assert state.hash_algo == HASH_ALGORITHM
    assert state.generated_at_unix == pytest.approx(123.5)
    assert state.sources[0].source_id == "src-a"
    group_node = node_at_path(state.tree, "group")
    assert group_node is not None
    assert state.sources[0].hash == group_node.hash
    assert state.sources[1].hash is None

    state_path = tmp_path / "mirror-state.json"
    state_path.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    loaded = load_mirror_state(state_path)
    assert loaded == state
    assert MirrorState.from_dict({"version": "x"}) is None
    assert load_mirror_state(tmp_path / "missing.json") is None
