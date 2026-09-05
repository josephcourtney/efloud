from __future__ import annotations

from collections.abc import Mapping
from typing import TypeGuard

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | JsonObject | JsonArray
type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]
type JsonMapping = Mapping[str, JsonValue]


def is_json_value(value: object) -> TypeGuard[JsonValue]:
    """Return whether an arbitrary runtime value is representable by the JSON model."""
    if value is None or isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
    return False


def is_json_mapping(value: object) -> TypeGuard[JsonMapping]:
    """Narrow an arbitrary runtime value to a string-keyed JSON mapping."""
    return isinstance(value, Mapping) and all(
        isinstance(key, str) and is_json_value(item) for key, item in value.items()
    )


def is_json_object(value: object) -> TypeGuard[JsonObject]:
    """Narrow an arbitrary runtime value to a mutable JSON object."""
    return isinstance(value, dict) and all(
        isinstance(key, str) and is_json_value(item) for key, item in value.items()
    )


def json_mapping_or_none(value: object) -> JsonMapping | None:
    """Return a validated JSON mapping or ``None`` for non-mappings/invalid values."""
    return value if is_json_mapping(value) else None


def json_object_or_none(value: object) -> JsonObject | None:
    """Return a validated JSON object or ``None`` for non-objects/invalid values."""
    return value if is_json_object(value) else None


def copy_json_mapping(value: JsonMapping) -> JsonObject:
    return dict(value.items())
