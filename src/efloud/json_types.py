from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeGuard

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | JsonObject | JsonArray
type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]
type JsonMapping = Mapping[str, JsonValue]


# These validators sit at deserialization boundaries and must accept arbitrary runtime payloads.
def is_json_mapping(value: Any) -> TypeGuard[JsonMapping]:  # noqa: ANN401
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)


def is_json_object(value: Any) -> TypeGuard[JsonObject]:  # noqa: ANN401
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def json_mapping_or_none(value: Any) -> JsonMapping | None:  # noqa: ANN401
    return value if is_json_mapping(value) else None


def json_object_or_none(value: Any) -> JsonObject | None:  # noqa: ANN401
    return value if is_json_object(value) else None


def copy_json_mapping(value: JsonMapping) -> JsonObject:
    return dict(value.items())
