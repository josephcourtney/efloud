from __future__ import annotations

import hashlib
import json
import logging
import operator
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from efloud.json_types import JsonMapping, JsonObject, JsonValue, json_mapping_or_none

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)

HASH_ALGORITHM = "sha256"

HashTreeChildren = dict[str, "MirrorStateNode"]


@dataclass(frozen=True)
class MirrorStateNode:
    path_type: Literal["file", "dir"]
    hash: str
    file_count: int
    dir_count: int
    children: HashTreeChildren | None = None

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "type": self.path_type,
            "hash": self.hash,
            "file_count": self.file_count,
            "dir_count": self.dir_count,
        }
        if self.children is not None:
            payload["children"] = {name: child.to_dict() for name, child in self.children.items()}
        return payload

    @staticmethod
    def from_dict(raw: JsonMapping) -> MirrorStateNode | None:
        path_type = _node_type(raw.get("type"))
        if path_type is None:
            return None
        hash_value = raw.get("hash")
        if not isinstance(hash_value, str):
            return None
        children_raw = raw.get("children")
        children: HashTreeChildren | None = None
        children_mapping = json_mapping_or_none(children_raw)
        if children_mapping is not None:
            entries: dict[str, MirrorStateNode] = {}
            for name, child in children_mapping.items():
                child_mapping = json_mapping_or_none(child)
                if child_mapping is None:
                    continue
                node = MirrorStateNode.from_dict(child_mapping)
                if node is not None:
                    entries[name] = node
            if entries:
                children = entries
        file_count = raw.get("file_count")
        dir_count = raw.get("dir_count")
        if not isinstance(file_count, int) or not isinstance(dir_count, int):
            file_count, dir_count = _node_counts(path_type=path_type, children=children)
        return MirrorStateNode(
            path_type=path_type,
            hash=hash_value,
            file_count=file_count,
            dir_count=dir_count,
            children=children,
        )


def _node_counts(
    *,
    path_type: Literal["file", "dir"],
    children: HashTreeChildren | None,
) -> tuple[int, int]:
    if path_type == "file":
        return (1, 0)
    file_count = 0
    dir_count = 1
    for child in (children or {}).values():
        file_count += child.file_count
        dir_count += child.dir_count
    return (file_count, dir_count)


def _hash_file(path: Path) -> str | None:
    try:
        hasher = hashlib.new(HASH_ALGORITHM)
    except ValueError:
        logger.warning("unsupported hash algorithm %s", HASH_ALGORITHM)
        return None
    try:
        with path.open("rb") as fin:
            while chunk := fin.read(8192):
                hasher.update(chunk)
    except OSError as exc:
        logger.warning("failed to hash %s: %s", path, exc)
        return None
    return hasher.hexdigest()


def _hash_directory(children: list[tuple[str, MirrorStateNode]]) -> str:
    hasher = hashlib.new(HASH_ALGORITHM)
    for name, node in children:
        entry = f"{name}:{node.path_type}:{node.hash}".encode()
        hasher.update(entry)
    return hasher.hexdigest()


def build_hash_tree(
    path: Path,
    *,
    on_progress: Callable[[int, int, Path], None] | None = None,
    _progress_state: dict[str, int] | None = None,
) -> MirrorStateNode | None:
    progress_state = _progress_state if _progress_state is not None else {"files": 0, "dirs": 0}
    if not path.exists():
        return None
    if path.is_file():
        file_hash = _hash_file(path)
        if file_hash is None:
            return None
        progress_state["files"] = int(progress_state["files"]) + 1
        if on_progress is not None:
            on_progress(int(progress_state["files"]), int(progress_state["dirs"]), path)
        return MirrorStateNode(path_type="file", hash=file_hash, file_count=1, dir_count=0)
    if path.is_dir():
        entries: list[tuple[str, MirrorStateNode]] = []
        sorted_paths = sorted(path.iterdir(), key=lambda child: child.name)
        for child in sorted_paths:
            node = build_hash_tree(child, on_progress=on_progress, _progress_state=progress_state)
            if node is not None:
                entries.append((child.name, node))
        directory_hash = _hash_directory(entries)
        children = dict(entries) if entries else None
        file_count, dir_count = _node_counts(path_type="dir", children=children)
        progress_state["dirs"] = int(progress_state["dirs"]) + 1
        if on_progress is not None:
            on_progress(int(progress_state["files"]), int(progress_state["dirs"]), path)
        return MirrorStateNode(
            path_type="dir",
            hash=directory_hash,
            file_count=file_count,
            dir_count=dir_count,
            children=children,
        )
    return None


def _replace_subtree(
    root: MirrorStateNode,
    *,
    parts: tuple[str, ...],
    replacement: MirrorStateNode | None,
) -> MirrorStateNode:
    if root.path_type != "dir":
        root = MirrorStateNode(path_type="dir", hash=_hash_directory([]), file_count=0, dir_count=1, children=None)

    if not parts:
        if replacement is None:
            return MirrorStateNode(path_type="dir", hash=_hash_directory([]), file_count=0, dir_count=1, children=None)
        return replacement

    children: dict[str, MirrorStateNode] = dict(root.children or {})
    head = parts[0]
    tail = parts[1:]
    if not tail:
        if replacement is None:
            children.pop(head, None)
        else:
            children[head] = replacement
    else:
        current = children.get(head)
        if current is None or current.path_type != "dir":
            current = MirrorStateNode(
                path_type="dir",
                hash=_hash_directory([]),
                file_count=0,
                dir_count=1,
                children=None,
            )
        children[head] = _replace_subtree(current, parts=tail, replacement=replacement)

    ordered_entries = sorted(children.items(), key=operator.itemgetter(0))
    merged_children = dict(ordered_entries) if ordered_entries else None
    file_count, dir_count = _node_counts(path_type="dir", children=merged_children)
    return MirrorStateNode(
        path_type="dir",
        hash=_hash_directory(ordered_entries),
        file_count=file_count,
        dir_count=dir_count,
        children=merged_children,
    )


def update_hash_tree_for_subdirs(
    base_tree: MirrorStateNode,
    mirrors_root: Path,
    subdirs: Sequence[str],
    *,
    on_progress: Callable[[str, int, int, Path], None] | None = None,
) -> MirrorStateNode:
    """
    Re-hash only the requested mirror subdirectories and splice them into an existing tree.

    This avoids full-tree hashing when a sync run touched only a subset of sources.
    """
    normalized = sorted({subdir.strip("/").replace("\\", "/") for subdir in subdirs if subdir.strip("/")})
    updated = base_tree
    for rel in normalized:
        progress_state = {"files": 0, "dirs": 0}
        replacement = build_hash_tree(
            mirrors_root / rel,
            on_progress=(
                (lambda files, dirs, current_path, rel_path=rel: on_progress(rel_path, files, dirs, current_path))
                if on_progress is not None
                else None
            ),
            _progress_state=progress_state,
        )
        updated = _replace_subtree(updated, parts=tuple(rel.split("/")), replacement=replacement)
    return updated


def node_at_path(root: MirrorStateNode | None, rel_path: str) -> MirrorStateNode | None:
    if root is None:
        return None
    normalized = rel_path.strip("/")
    if not normalized:
        return root
    current: MirrorStateNode | None = root
    for part in normalized.split("/"):
        if current is None or current.children is None:
            return None
        current = current.children.get(part)
    return current


def compare_hash_trees(
    expected: MirrorStateNode | None,
    actual: MirrorStateNode | None,
    base_path: str = "",
    max_diffs: int = 24,
) -> list[str]:
    diffs: list[str] = []
    _append_tree_diffs(expected, actual, base_path, diffs=diffs, max_diffs=max_diffs)
    return diffs


def _append_tree_diffs(
    expected: MirrorStateNode | None,
    actual: MirrorStateNode | None,
    path: str,
    *,
    diffs: list[str],
    max_diffs: int,
) -> None:
    if len(diffs) >= max_diffs or (expected is None and actual is None):
        return
    if expected is None:
        diffs.append(f"unexpected artifact at {_describe_tree_path(path)}")
        return
    if actual is None:
        diffs.append(f"missing artifact at {_describe_tree_path(path)}")
        return
    if expected.path_type != actual.path_type:
        diffs.append(
            f"type mismatch at {_describe_tree_path(path)}: expected {expected.path_type}, found {actual.path_type}",
        )
        return
    if expected.hash != actual.hash:
        diffs.append(f"hash mismatch at {_describe_tree_path(path)}")
    if expected.path_type != "dir":
        return
    for name in _child_names(expected, actual):
        _append_tree_diffs(
            (expected.children or {}).get(name),
            (actual.children or {}).get(name),
            f"{path}/{name}" if path else name,
            diffs=diffs,
            max_diffs=max_diffs,
        )
        if len(diffs) >= max_diffs:
            return


def _describe_tree_path(path: str) -> str:
    return path or "."


def _child_names(expected: MirrorStateNode, actual: MirrorStateNode) -> list[str]:
    return sorted(set(expected.children or {}) | set(actual.children or {}))


@dataclass(frozen=True)
class MirrorSourceState:
    source_id: str | None
    local_subdir: str
    hash: str | None

    def to_dict(self) -> JsonObject:
        return {"source_id": self.source_id, "local_subdir": self.local_subdir, "hash": self.hash}

    @staticmethod
    def from_dict(raw: JsonMapping) -> MirrorSourceState | None:
        local_subdir = raw.get("local_subdir")
        if not isinstance(local_subdir, str):
            return None
        source_id = raw.get("source_id")
        if source_id is not None and not isinstance(source_id, str):
            return None
        hash_value = raw.get("hash")
        if hash_value is not None and not isinstance(hash_value, str):
            return None
        return MirrorSourceState(source_id=source_id, local_subdir=local_subdir, hash=hash_value)


@dataclass(frozen=True)
class MirrorState:
    version: int
    generated_at_unix: float
    cache_root: str
    mirrors_root: str
    hash_algo: str
    manifest_path: str | None
    tree: MirrorStateNode
    sources: tuple[MirrorSourceState, ...]

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "version": self.version,
            "generated_at_unix": self.generated_at_unix,
            "cache_root": self.cache_root,
            "mirrors_root": self.mirrors_root,
            "hash_algo": self.hash_algo,
            "manifest_path": self.manifest_path,
            "sources": [source.to_dict() for source in self.sources],
        }
        payload["tree"] = self.tree.to_dict()
        return payload

    @staticmethod
    def from_dict(raw: JsonMapping) -> MirrorState | None:
        version = raw.get("version")
        if not isinstance(version, int):
            return None
        generated_at_unix = raw.get("generated_at_unix")
        if not isinstance(generated_at_unix, (float, int)):
            return None
        cache_root = raw.get("cache_root")
        mirrors_root = raw.get("mirrors_root")
        hash_algo = raw.get("hash_algo")
        if not isinstance(cache_root, str) or not isinstance(mirrors_root, str) or not isinstance(hash_algo, str):
            return None
        manifest_path = raw.get("manifest_path")
        if manifest_path is not None and not isinstance(manifest_path, str):
            return None
        tree_raw = json_mapping_or_none(raw.get("tree"))
        tree = MirrorStateNode.from_dict(tree_raw) if tree_raw is not None else None
        if tree is None:
            return None
        sources_raw = raw.get("sources")
        sources: list[MirrorSourceState] = []
        if isinstance(sources_raw, list):
            for entry in sources_raw:
                entry_mapping = json_mapping_or_none(entry)
                if entry_mapping is not None:
                    source_state = MirrorSourceState.from_dict(entry_mapping)
                    if source_state is not None:
                        sources.append(source_state)
        return MirrorState(
            version=version,
            generated_at_unix=float(generated_at_unix),
            cache_root=cache_root,
            mirrors_root=mirrors_root,
            hash_algo=hash_algo,
            manifest_path=manifest_path,
            tree=tree,
            sources=tuple(sources),
        )

    @staticmethod
    def build(
        cache_root: Path,
        mirrors_root: Path,
        manifest_path: Path | None,
        sources_info: Sequence[tuple[str | None, str]] | None = None,
        *,
        on_progress: Callable[[int, int, Path], None] | None = None,
    ) -> MirrorState:
        tree = build_hash_tree(mirrors_root, on_progress=on_progress)
        if tree is None:
            msg = f"failed to build hash tree for mirror root {mirrors_root}"
            raise RuntimeError(msg)
        entries: list[MirrorSourceState] = []
        if sources_info:
            for source_id, subdir in sources_info:
                normalized = subdir or ""
                node = node_at_path(tree, normalized)
                entries.append(
                    MirrorSourceState(
                        source_id=source_id,
                        local_subdir=normalized,
                        hash=node.hash if node is not None else None,
                    ),
                )
        return MirrorState(
            version=1,
            generated_at_unix=time.time(),
            cache_root=str(cache_root.resolve()),
            mirrors_root=str(mirrors_root.resolve()),
            hash_algo=HASH_ALGORITHM,
            manifest_path=str(manifest_path) if manifest_path else None,
            tree=tree,
            sources=tuple(entries),
        )


def load_mirror_state(path: Path) -> MirrorState | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_mapping = json_mapping_or_none(raw)
    if raw_mapping is None:
        return None
    return MirrorState.from_dict(raw_mapping)


def _node_type(value: JsonValue | None) -> Literal["file", "dir"] | None:
    if value == "file":
        return "file"
    if value == "dir":
        return "dir"
    return None
