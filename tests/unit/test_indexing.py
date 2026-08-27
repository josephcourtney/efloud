from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from efloud.indexing import IndexDefinition, IndexRegistry, JsonTtlIndex, load_index, write_index

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.mark.small
def test_json_ttl_index_round_trip_and_expiry(monkeypatch):
    index = JsonTtlIndex(fetched_at=100.0, ttl_seconds=10, payload={"ok": True})

    monkeypatch.setattr("efloud.indexing.time.time", lambda: 105.0)
    assert index.expires_at == pytest.approx(110.0)
    assert index.is_expired() is False
    assert index.to_dict() == {"fetched_at": 100.0, "ttl_seconds": 10, "payload": {"ok": True}}

    loaded = JsonTtlIndex.from_dict({"fetched_at": 100, "ttl_seconds": 10, "payload": {"ok": True}})
    assert loaded == index

    monkeypatch.setattr("efloud.indexing.time.time", lambda: 200.0)
    assert index.is_expired() is True

    with pytest.raises(TypeError, match="Index payload must be an object"):
        JsonTtlIndex.from_dict({"payload": []})


@pytest.mark.medium
def test_write_and_load_index_round_trip(tmp_path: Path):
    path = tmp_path / "index.json"
    index = JsonTtlIndex(fetched_at=1.0, ttl_seconds=2, payload={"value": 1})

    write_index(path, index)

    assert load_index(path, JsonTtlIndex) == index
    assert load_index(tmp_path / "missing.json", JsonTtlIndex) is None

    path.write_text("{", encoding="utf-8")
    assert load_index(path, JsonTtlIndex) is None

    path.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")
    assert load_index(path, JsonTtlIndex) is None


@pytest.mark.medium
def test_index_registry_build_reuses_fresh_cache_and_reports_status(tmp_path: Path, monkeypatch):
    built_values: list[Path] = []

    def builder(*, root: Path) -> JsonTtlIndex:
        built_values.append(root)
        return JsonTtlIndex(fetched_at=100.0, ttl_seconds=30, payload={"root": root.name})

    registry = IndexRegistry([
        IndexDefinition(
            index_id="alpha",
            filename="alpha.json",
            ttl_seconds=30,
            build=builder,
            parser=JsonTtlIndex,
            description="Alpha index",
        )
    ])

    monkeypatch.setattr("efloud.indexing.time.time", lambda: 101.0)
    built = cast("JsonTtlIndex", registry.build("alpha", root=tmp_path))
    assert built.payload == {"root": tmp_path.name}
    assert built_values == [tmp_path]

    cached = cast("JsonTtlIndex", registry.build("alpha", root=tmp_path))
    assert cached.payload == {"root": tmp_path.name}
    assert built_values == [tmp_path]

    status = registry.status("alpha", root=tmp_path)
    assert status.present is True
    assert status.loaded is True
    assert status.expired is False
    assert status.to_dict()["index_id"] == "alpha"
    assert registry.ids() == ("alpha",)
    assert registry.path_for("alpha", root=tmp_path) == tmp_path / "alpha.json"
    assert registry.definition("alpha") is not None
    assert registry.load("alpha", root=tmp_path) is not None


@pytest.mark.medium
def test_index_registry_handles_unparseable_and_unknown_indexes(tmp_path: Path):
    registry = IndexRegistry([
        IndexDefinition(
            index_id="alpha",
            filename="alpha.json",
            ttl_seconds=30,
            build=lambda *, root: JsonTtlIndex(fetched_at=0.0, ttl_seconds=0, payload={"root": root.name}),
            parser=JsonTtlIndex,
        )
    ])

    bad_path = tmp_path / "alpha.json"
    bad_path.write_text("{", encoding="utf-8")
    status = registry.status("alpha", root=tmp_path)
    assert status.present is True
    assert status.loaded is False
    assert status.error == "Index exists but could not be parsed."

    with pytest.raises(ValueError, match="Unknown index identifier"):
        registry.path_for("missing", root=tmp_path)
    with pytest.raises(ValueError, match="Unknown index identifier"):
        registry.load("missing", root=tmp_path)
    with pytest.raises(ValueError, match="Unknown index identifier"):
        registry.build("missing", root=tmp_path)
    with pytest.raises(ValueError, match="Unknown index identifier"):
        registry.status("missing", root=tmp_path)
