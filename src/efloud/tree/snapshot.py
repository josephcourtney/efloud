from __future__ import annotations

import json
from typing import TYPE_CHECKING

from efloud.json_types import json_object_or_none
from efloud.repository_models import ContentId, TreeEntry, canonical_json_bytes
from efloud.tree.protocol import GitTreeId, TreeBlob

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.tree.protocol import TreeStore

_MANIFEST_PATH = "efloud-tree.json"


def _entry_payload(entry: TreeEntry) -> JsonObject:
    payload: JsonObject = {
        "relative_path": entry.relative_path,
        "kind": entry.kind,
        "metadata": dict(entry.metadata),
    }
    if entry.content_id is not None:
        payload["content_id"] = str(entry.content_id)
    if entry.byte_size is not None:
        payload["byte_size"] = entry.byte_size
    if entry.target is not None:
        payload["target"] = entry.target
    return payload


def write_tree_snapshot(store: TreeStore, entries: tuple[TreeEntry, ...]) -> GitTreeId:
    """Persist one canonical semantic tree projection in Git's object database."""
    ordered = tuple(sorted(entries, key=lambda entry: entry.relative_path))
    if len({entry.relative_path for entry in ordered}) != len(ordered):
        msg = "Tree snapshot entries must have unique relative paths"
        raise ValueError(msg)
    payload = [_entry_payload(entry) for entry in ordered]
    return store.write_tree((TreeBlob(_MANIFEST_PATH, canonical_json_bytes(payload)),))


def read_tree_snapshot(store: TreeStore, tree_id: str) -> tuple[TreeEntry, ...]:
    """Load semantic tree entries from one exact Git tree projection."""
    listed = store.list_tree(tree_id)
    if len(listed) != 1 or listed[0].relative_path != _MANIFEST_PATH or listed[0].object_type != "blob":
        msg = f"Git tree {tree_id} is not an Efloud tree snapshot"
        raise ValueError(msg)
    decoded: object = json.loads(store.read_blob(listed[0].object_id))
    if not isinstance(decoded, list):
        msg = f"Git tree {tree_id} has an invalid Efloud tree manifest"
        raise ValueError(msg)
    entries: list[TreeEntry] = []
    for value in decoded:
        raw = json_object_or_none(value)
        if raw is None:
            msg = f"Git tree {tree_id} contains a non-object tree entry"
            raise ValueError(msg)
        relative_path = raw.get("relative_path")
        kind = raw.get("kind")
        content_id = raw.get("content_id")
        byte_size = raw.get("byte_size")
        target = raw.get("target")
        metadata = json_object_or_none(raw.get("metadata", {}))
        if not isinstance(relative_path, str) or not isinstance(kind, str):
            msg = f"Git tree {tree_id} contains an invalid tree entry identity"
            raise ValueError(msg)
        if content_id is not None and not isinstance(content_id, str):
            msg = f"Git tree {tree_id} contains an invalid content identity"
            raise ValueError(msg)
        if byte_size is not None and (not isinstance(byte_size, int) or isinstance(byte_size, bool)):
            msg = f"Git tree {tree_id} contains an invalid byte size"
            raise ValueError(msg)
        if target is not None and not isinstance(target, str):
            msg = f"Git tree {tree_id} contains an invalid symlink target"
            raise ValueError(msg)
        if metadata is None:
            msg = f"Git tree {tree_id} contains invalid entry metadata"
            raise ValueError(msg)
        entries.append(
            TreeEntry(
                relative_path=relative_path,
                kind=kind,
                content_id=ContentId(content_id) if content_id is not None else None,
                byte_size=byte_size,
                target=target,
                metadata=metadata,
            )
        )
    ordered = tuple(sorted(entries, key=lambda entry: entry.relative_path))
    if len({entry.relative_path for entry in ordered}) != len(ordered):
        msg = f"Git tree {tree_id} contains duplicate semantic paths"
        raise ValueError(msg)
    return ordered


__all__ = ["read_tree_snapshot", "write_tree_snapshot"]
