from __future__ import annotations

import json
from typing import TYPE_CHECKING

from efloud.json_types import json_object_or_none
from efloud.repository_models import ContentId, TreeEntry, canonical_json_bytes
from efloud.tree.protocol import GitTreeId, TreeBlob

if TYPE_CHECKING:
    from efloud.json_types import JsonObject, JsonValue
    from efloud.tree.protocol import TreeStore

_MANIFEST_PATH = "efloud-tree.json"
_RETENTION_REF = "refs/efloud/tree-snapshots"


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
    """Persist and retain one canonical semantic tree projection in Git."""
    ordered = tuple(sorted(entries, key=lambda entry: entry.relative_path))
    if len({entry.relative_path for entry in ordered}) != len(ordered):
        msg = "Tree snapshot entries must have unique relative paths"
        raise ValueError(msg)
    payload = [_entry_payload(entry) for entry in ordered]
    tree = store.write_tree((TreeBlob(_MANIFEST_PATH, canonical_json_bytes(payload)),))
    # The commit/ref is storage reachability only. SourceSnapshot.tree_id remains
    # the Git tree object ID, so commit metadata never participates in semantic identity.
    store.commit_tree(tree, ref=_RETENTION_REF, message="retain Efloud tree snapshot")
    return tree


def _require_optional_string(value: JsonValue | None, *, field: str, tree_id: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    msg = f"Git tree {tree_id} contains invalid {field}"
    raise TypeError(msg)


def _require_optional_size(value: JsonValue | None, *, tree_id: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = f"Git tree {tree_id} contains an invalid byte size"
    raise TypeError(msg)


def _decode_tree_entry(value: object, *, tree_id: str) -> TreeEntry:
    raw = json_object_or_none(value)
    if raw is None:
        msg = f"Git tree {tree_id} contains a non-object tree entry"
        raise TypeError(msg)

    relative_path = raw.get("relative_path")
    kind = raw.get("kind")
    if not isinstance(relative_path, str) or not isinstance(kind, str):
        msg = f"Git tree {tree_id} contains an invalid tree entry identity"
        raise TypeError(msg)

    metadata = json_object_or_none(raw.get("metadata", {}))
    if metadata is None:
        msg = f"Git tree {tree_id} contains invalid entry metadata"
        raise TypeError(msg)

    content_id = _require_optional_string(raw.get("content_id"), field="content identity", tree_id=tree_id)
    target = _require_optional_string(raw.get("target"), field="symlink target", tree_id=tree_id)
    byte_size = _require_optional_size(raw.get("byte_size"), tree_id=tree_id)
    return TreeEntry(
        relative_path=relative_path,
        kind=kind,
        content_id=ContentId(content_id) if content_id is not None else None,
        byte_size=byte_size,
        target=target,
        metadata=metadata,
    )


def read_tree_snapshot(store: TreeStore, tree_id: str) -> tuple[TreeEntry, ...]:
    """Load semantic tree entries from one exact Git tree projection."""
    listed = store.list_tree(tree_id)
    if len(listed) != 1 or listed[0].relative_path != _MANIFEST_PATH or listed[0].object_type != "blob":
        msg = f"Git tree {tree_id} is not an Efloud tree snapshot"
        raise ValueError(msg)

    decoded: object = json.loads(store.read_blob(listed[0].object_id))
    if not isinstance(decoded, list):
        msg = f"Git tree {tree_id} has an invalid Efloud tree manifest"
        raise TypeError(msg)

    entries = tuple(
        sorted((_decode_tree_entry(value, tree_id=tree_id) for value in decoded), key=lambda e: e.relative_path)
    )
    if len({entry.relative_path for entry in entries}) != len(entries):
        msg = f"Git tree {tree_id} contains duplicate semantic paths"
        raise ValueError(msg)
    return entries


__all__ = ["read_tree_snapshot", "write_tree_snapshot"]
