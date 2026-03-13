from __future__ import annotations

import hashlib
import json
import logging
import operator
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

HASH_ALGORITHM = "sha256"

HashTreeChildren = dict[str, "MirrorStateNode"]


@dataclass(frozen=True)
class MirrorStateNode:
    path_type: Literal["file", "dir"]
    hash: str
    children: HashTreeChildren | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"type": self.path_type, "hash": self.hash}
        if self.children is not None:
            payload["children"] = {name: child.to_dict() for name, child in self.children.items()}
        return payload

    @staticmethod
    def from_dict(raw: Mapping[str, object]) -> MirrorStateNode | None:
        path_type = raw.get("type")
        if path_type not in {"file", "dir"}:
            return None
        hash_value = raw.get("hash")
        if not isinstance(hash_value, str):
            return None
        children_raw = raw.get("children")
        children: HashTreeChildren | None = None
        if isinstance(children_raw, Mapping):
            entries: dict[str, MirrorStateNode] = {}
            for name, child in children_raw.items():
                if not isinstance(name, str) or not isinstance(child, Mapping):
                    continue
                node = MirrorStateNode.from_dict(child)
                if node is not None:
                    entries[name] = node
            if entries:
                children = entries
        return MirrorStateNode(path_type=path_type, hash=hash_value, children=children)


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


def build_hash_tree(path: Path) -> MirrorStateNode | None:
    if not path.exists():
        return None
    if path.is_file():
        file_hash = _hash_file(path)
        if file_hash is None:
            return None
        return MirrorStateNode(path_type="file", hash=file_hash)
    if path.is_dir():
        entries: list[tuple[str, MirrorStateNode]] = []
        sorted_paths = sorted(path.iterdir(), key=lambda child: child.name)
        for child in sorted_paths:
            node = build_hash_tree(child)
            if node is not None:
                entries.append((child.name, node))
        directory_hash = _hash_directory(entries)
        children = dict(entries) if entries else None
        return MirrorStateNode(path_type="dir", hash=directory_hash, children=children)
    return None


def _replace_subtree(
    root: MirrorStateNode,
    *,
    parts: tuple[str, ...],
    replacement: MirrorStateNode | None,
) -> MirrorStateNode:
    if root.path_type != "dir":
        root = MirrorStateNode(path_type="dir", hash=_hash_directory([]), children=None)

    if not parts:
        if replacement is None:
            return MirrorStateNode(path_type="dir", hash=_hash_directory([]), children=None)
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
            current = MirrorStateNode(path_type="dir", hash=_hash_directory([]), children=None)
        children[head] = _replace_subtree(current, parts=tail, replacement=replacement)

    ordered_entries = sorted(children.items(), key=operator.itemgetter(0))
    merged_children = dict(ordered_entries) if ordered_entries else None
    return MirrorStateNode(
        path_type="dir",
        hash=_hash_directory(ordered_entries),
        children=merged_children,
    )


def update_hash_tree_for_subdirs(
    base_tree: MirrorStateNode,
    mirrors_root: Path,
    subdirs: Sequence[str],
) -> MirrorStateNode:
    """
    Re-hash only the requested mirror subdirectories and splice them into an existing tree.

    This avoids full-tree hashing when a sync run touched only a subset of sources.
    """
    normalized = sorted({subdir.strip("/").replace("\\", "/") for subdir in subdirs if subdir.strip("/")})
    updated = base_tree
    for rel in normalized:
        replacement = build_hash_tree(mirrors_root / rel)
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

    def _describe(path: str) -> str:
        return path or "."

    def _walk(exp: MirrorStateNode | None, act: MirrorStateNode | None, path: str) -> None:
        if len(diffs) >= max_diffs:
            return
        if exp is None and act is None:
            return
        if exp is None:
            diffs.append(f"unexpected artifact at {_describe(path)}")
            return
        if act is None:
            diffs.append(f"missing artifact at {_describe(path)}")
            return
        if exp.path_type != act.path_type:
            diffs.append(
                f"type mismatch at {_describe(path)}: expected {exp.path_type}, found {act.path_type}",
            )
            return
        if exp.hash != act.hash:
            diffs.append(f"hash mismatch at {_describe(path)}")
        if exp.path_type == "dir":
            expected_children = exp.children or {}
            actual_children = act.children or {}
            for name in sorted(set(expected_children) | set(actual_children)):
                _walk(
                    expected_children.get(name),
                    actual_children.get(name),
                    f"{path}/{name}" if path else name,
                )
                if len(diffs) >= max_diffs:
                    return

    _walk(expected, actual, base_path)
    return diffs


@dataclass(frozen=True)
class MirrorSourceState:
    source_id: str | None
    local_subdir: str
    hash: str | None

    def to_dict(self) -> dict[str, object | None]:
        return {"source_id": self.source_id, "local_subdir": self.local_subdir, "hash": self.hash}

    @staticmethod
    def from_dict(raw: Mapping[str, object]) -> MirrorSourceState | None:
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

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
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
    def from_dict(raw: Mapping[str, object]) -> MirrorState | None:
        version = raw.get("version")
        if not isinstance(version, int):
            return None
        generated_at_unix = raw.get("generated_at_unix")
        if not isinstance(generated_at_unix, (float, int)):
            return None
        cache_root = raw.get("cache_root")
        mirrors_root = raw.get("mirrors_root")
        hash_algo = raw.get("hash_algo")
        if (
            not isinstance(cache_root, str)
            or not isinstance(mirrors_root, str)
            or not isinstance(hash_algo, str)
        ):
            return None
        manifest_path = raw.get("manifest_path")
        if manifest_path is not None and not isinstance(manifest_path, str):
            return None
        tree_raw = raw.get("tree")
        tree = MirrorStateNode.from_dict(tree_raw) if isinstance(tree_raw, Mapping) else None
        if tree is None:
            return None
        sources_raw = raw.get("sources")
        sources: list[MirrorSourceState] = []
        if isinstance(sources_raw, list):
            for entry in sources_raw:
                if isinstance(entry, Mapping):
                    source_state = MirrorSourceState.from_dict(entry)
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
    ) -> MirrorState:
        tree = build_hash_tree(mirrors_root)
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
    if not isinstance(raw, Mapping):
        return None
    return MirrorState.from_dict(raw)
