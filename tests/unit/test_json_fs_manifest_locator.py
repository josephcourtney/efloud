from __future__ import annotations

import gzip
import json
from collections import UserDict
from pathlib import Path
from typing import cast

import pytest

from efloud.fs import (
    atomic_write_bytes,
    atomic_write_text,
    delete_http_cache_files,
    ensure_root_dirs,
    prune_orphan_mirrors,
    read_gz_json,
    read_text_maybe_gzip,
    safe_json_dump,
)
from efloud.json_types import (
    JsonValue,
    copy_json_mapping,
    is_json_mapping,
    is_json_object,
    json_mapping_or_none,
    json_object_or_none,
)
from efloud.locator import (
    apply_structured_locator,
    csv_locator_to_rfc7111,
    jsonpath_to_pointer,
    locator_candidates,
    locator_parts,
    resolve_locator_from_file,
    resolve_single_locator_from_file,
    split_locator,
    star_locator_to_pointer,
)
from efloud.manifest import load_latest_manifest, merge_manifests, normalize_manifest

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def test_json_type_helpers_recognize_and_copy_mappings():
    class StringKeyMapping(UserDict):
        pass

    mapping = StringKeyMapping({"a": 1})

    assert is_json_mapping(mapping) is True
    assert is_json_mapping({1: "x"}) is False
    assert is_json_object({"a": 1}) is True
    assert is_json_object(mapping) is False
    assert json_mapping_or_none(mapping) is mapping
    assert json_mapping_or_none("x") is None
    assert json_object_or_none({"a": 1}) == {"a": 1}
    assert json_object_or_none(mapping) is None
    assert copy_json_mapping(mapping) == {"a": 1}


def test_fs_helpers_round_trip_and_manage_directories(tmp_path: Path):
    text_path = tmp_path / "nested" / "payload.txt"
    bytes_path = tmp_path / "nested" / "payload.bin"
    json_gz_path = tmp_path / "payload.json.gz"

    atomic_write_text(text_path, "hello")
    atomic_write_bytes(bytes_path, b"abc")
    with gzip.open(json_gz_path, "wt", encoding="utf-8") as handle:
        json.dump({"ok": True}, handle)

    dirs = ensure_root_dirs(tmp_path / "root", {"cache": "cache", "log": "log"})

    assert text_path.read_text(encoding="utf-8") == "hello"
    assert bytes_path.read_bytes() == b"abc"
    assert read_gz_json(json_gz_path) == {"ok": True}
    assert read_text_maybe_gzip(json_gz_path) == '{"ok": true}'
    assert safe_json_dump({"b": 1, "a": "x"}).splitlines()[1].startswith('  "a"')
    assert dirs["root"].is_dir()
    assert dirs["cache"] == dirs["root"] / "cache"


def test_fs_helpers_prune_and_delete_cache_files(tmp_path: Path):
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    keep = cache_root / "note.txt"
    keep.write_text("keep", encoding="utf-8")
    cache_a = cache_root / "a.sqlite"
    cache_b = cache_root / "b.sqlite"
    cache_a.write_text("a", encoding="utf-8")
    cache_b.write_text("b", encoding="utf-8")

    mirrors_root = tmp_path / "mirrors"
    keep_dir = mirrors_root / "keep"
    remove_dir = mirrors_root / "remove"
    keep_dir.mkdir(parents=True)
    remove_dir.mkdir(parents=True)

    removed_caches = delete_http_cache_files(cache_root)
    removed_dirs = prune_orphan_mirrors(mirrors_root, [keep_dir])

    assert sorted(Path(item).name for item in removed_caches) == ["a.sqlite", "b.sqlite"]
    assert keep.exists()
    assert keep_dir.exists()
    assert removed_dirs == [str(remove_dir)]
    assert not remove_dir.exists()


def test_normalize_manifest_adds_defaults_and_hoists_request_url():
    manifest = normalize_manifest({
        "results": {
            "http": {
                "s1": {
                    "request": {"url": "https://example.test/data.json"},
                }
            }
        }
    })

    assert manifest["version"] == 1
    assert manifest["root"] == ""
    assert manifest["errors"] == []
    assert manifest["results"]["http"]["s1"]["url"] == "https://example.test/data.json"
    assert manifest["results"]["rsync"] == {}
    assert manifest["results"]["derived"] == {}


def test_normalize_manifest_rejects_non_mapping():
    with pytest.raises(TypeError, match="manifest must be a JSON object"):
        normalize_manifest(["not", "a", "mapping"])


def test_merge_manifests_preserves_previous_sections_and_replaces_metadata():
    previous = {
        "root": "/old",
        "results": {
            "http": {"h": {"ok": True}},
            "rsync": {"r": {"ok": True}},
            "derived": {},
        },
        "errors": [{"error": "old"}],
    }
    new = {
        "root": "/new",
        "started_at_unix": 100,
        "results": {
            "http": {"h2": {"ok": False}},
            "derived": {"d": {"ok": True}},
        },
        "errors": [{"error": "new"}],
    }

    merged = merge_manifests(previous, new)

    assert merged["root"] == "/new"
    assert merged["errors"] == [{"error": "new"}]
    assert merged["results"]["http"] == {"h": {"ok": True}, "h2": {"ok": False}}
    assert merged["results"]["rsync"] == {"r": {"ok": True}}
    assert merged["results"]["derived"] == {"d": {"ok": True}}


def test_load_latest_manifest_handles_missing_invalid_and_root_mismatch(tmp_path: Path):
    log_dir = tmp_path / "log"
    manifest, warnings, guessed = load_latest_manifest(log_dir, "sync-manifest.json", expected_root=tmp_path)
    assert manifest is None
    assert guessed == log_dir / "sync-manifest.json"
    assert warnings == [f"sync manifest missing: {log_dir / 'sync-manifest.json'}"]

    log_dir.mkdir()
    bad_path = log_dir / "sync-manifest.json"
    bad_path.write_text("{", encoding="utf-8")
    manifest, warnings, guessed = load_latest_manifest(log_dir, "sync-manifest.json", expected_root=tmp_path)
    assert manifest is None
    assert guessed == bad_path
    assert warnings
    assert warnings[0].startswith("sync manifest unreadable:")

    payload = {
        "root": str(tmp_path / "other"),
        "results": {"http": {}, "rsync": {}, "derived": {}},
        "errors": [],
    }
    bad_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest, warnings, guessed = load_latest_manifest(log_dir, "sync-manifest.json", expected_root=tmp_path)
    assert manifest is not None
    assert guessed == bad_path
    assert "conflicts with configured cache root" in warnings[0]


def test_split_locator_and_parts_cover_supported_forms():
    assert split_locator("artifact.json#/items/0/name") == ("artifact.json", "/items/0/name")
    assert split_locator("artifact.json") == ("artifact.json", None)
    with pytest.raises(ValueError, match="Invalid locator"):
        split_locator("artifact.json# ")

    assert locator_parts("#/items/0/name") == ["items", "0", "name"]
    assert locator_parts("$.items[0].name") == ["items", "0", "name"]
    assert locator_parts("items[0]['name']") == ["items", "0", "name"]
    assert locator_parts("") == []
    assert jsonpath_to_pointer("$.items[0].name") == "/items/0/name"
    assert csv_locator_to_rfc7111("CSV row=3 cols[0] cols[2]") == "#row=3&col=1-3"
    assert star_locator_to_pointer("STAR tag=_Entry.ID value=1") == "#/Entry/ID"


def test_apply_structured_locator_handles_dict_list_and_errors():
    value = cast("JsonValue", {"items": [{"name": "alpha"}]})

    assert apply_structured_locator(value, "/items/0/name") == ("alpha", None)
    assert apply_structured_locator(value, "/items/1") == (None, "Locator index 1 out of range (0..0)")
    assert apply_structured_locator(value, "/items/x") == (
        None,
        "Locator segment 'x' is not a valid list index",
    )
    assert apply_structured_locator(value, "/items/0/name/x") == (
        None,
        "Locator segment 'x' cannot be applied to scalar value",
    )


def test_resolve_locator_from_file_supports_json_text_and_candidate_fallbacks(tmp_path: Path):
    json_path = tmp_path / "payload.json"
    json_path.write_text(json.dumps({"items": [{"name": "alpha"}]}), encoding="utf-8")
    text_path = tmp_path / "notes.txt"
    text_path.write_text("line1\nline2\nvalue=42\n", encoding="utf-8")

    assert resolve_single_locator_from_file(json_path, "$.items[0].name") == ("alpha", None)
    assert resolve_single_locator_from_file(text_path, "line:2") == ("line2", None)
    assert resolve_single_locator_from_file(text_path, "lines:1-2") == ("line1\nline2", None)
    assert resolve_single_locator_from_file(text_path, r"regex:value=(\d+)") == ("42", None)
    assert resolve_single_locator_from_file(text_path, "text") == ("line1\nline2\nvalue=42\n", None)

    value, err, resolved = resolve_locator_from_file(json_path, "#/items/0/name")
    assert (value, err, resolved) == ("alpha", None, "#/items/0/name")

    value, err, resolved = resolve_locator_from_file(text_path, "missing")
    assert value is None
    assert resolved is None
    assert err is not None
    assert "Locator evaluation failed for all candidates" in err

    assert locator_candidates("#/items/0/name") == ("#/items/0/name", "/items/0/name")
