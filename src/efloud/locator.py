from __future__ import annotations

import gzip
import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def split_locator(target: str) -> tuple[str, str | None]:
    """
    Split ``<target>#<locator>`` into ``(target, locator)``.

    Examples
    --------
    >>> split_locator("artifact.json#/items/0/name")
    ('artifact.json', '/items/0/name')
    >>> split_locator("artifact.json")
    ('artifact.json', None)
    """
    if "#" not in target:
        return target, None

    base, locator = target.split("#", 1)
    locator = locator.strip()
    if not locator:
        msg = f"Invalid locator in target: {target!r}"
        raise ValueError(msg)
    return base, locator


def read_text_auto(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return path.read_text(encoding="utf-8", errors="replace")


def locator_parts(locator: str) -> list[str]:
    """
    Convert a locator into path segments.

    Supported structured forms
    --------------------------
    - JSON Pointer-like:
        /items/0/name
        #/items/0/name
    - Dotted / bracketed JSONPath-lite:
        $.items[0].name
        items[0].name

    Returns normalized path components suitable for walking nested objects.
    """
    loc = locator.strip()
    if not loc:
        return []

    loc = loc.removeprefix("#")

    pointer = _jsonpath_to_pointer(loc)
    if pointer is not None:
        loc = pointer

    if loc.startswith("/"):
        return [part for part in loc.split("/") if part]

    # Allow plain "a.b[0].c" as a convenience.
    if "." in loc or "[" in loc:
        converted = _jsonpath_to_pointer("$." + loc if not loc.startswith("$") else loc)
        if converted is not None:
            return [part for part in converted.split("/") if part]

    return [part for part in loc.split("/") if part]


def apply_structured_locator(value: object, locator: str) -> tuple[object | None, str | None]:
    """
    Apply a structured locator to a nested Python object.

    Supported container traversal
    -----------------------------
    - dict / Mapping lookup by key
    - list lookup by integer index

    Returns
    -------
    (resolved_value, error_message)
    """
    current: object = value
    for part in locator_parts(locator):
        if isinstance(current, Mapping):
            if part not in current:
                return None, f"Locator segment {part!r} not found in object"
            current = current[part]
            continue

        if isinstance(current, list):
            if not part.isdigit():
                return None, f"Locator segment {part!r} is not a valid list index"
            index = int(part)
            if index < 0 or index >= len(current):
                return None, f"Locator index {index} out of range (0..{len(current) - 1})"
            current = current[index]
            continue

        return None, f"Locator segment {part!r} cannot be applied to scalar value"

    return current, None


def resolve_single_locator_from_file(path: Path, locator: str) -> tuple[object | None, str | None]:
    """
    Resolve a locator against a file.

    Supported file/locator combinations
    -----------------------------------
    JSON / JSON.GZ
        Structured locators such as:
        - /items/0/name
        - #/items/0/name
        - $.items[0].name
        - items[0].name

    Text / any other file
        Text locators:
        - line:<n>         (1-based)
        - lines:<a>-<b>    (inclusive, 1-based)
        - regex:<pattern>  (returns first capture group if present, else full match)
        - text             (returns full text)

    Returns
    -------
    (resolved_value, error_message)
    """
    suffixes = "".join(path.suffixes).lower()

    if suffixes.endswith(".json.gz") or path.suffix.lower() == ".json":
        try:
            obj = json.loads(read_text_auto(path))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"Failed to read JSON payload at {path}: {exc}"
        return apply_structured_locator(obj, locator)

    text = read_text_auto(path)
    return _resolve_text_locator(text, locator)


def resolve_locator_from_file(path: Path, locator: str) -> tuple[object | None, str | None, str | None]:
    """
    Resolve a locator from a file, trying a small set of normalized fallback forms.

    Returns
    -------
    (value, error_message, resolved_locator)
    """
    attempts: list[str] = []
    for candidate in locator_candidates(locator):
        value, err = resolve_single_locator_from_file(path, candidate)
        if err is None:
            return value, None, candidate
        attempts.append(f"{candidate}: {err}")
    return None, "Locator evaluation failed for all candidates: " + " | ".join(attempts), None


def locator_candidates(locator: str) -> tuple[str, ...]:
    """
    Generate a deterministic set of fallback locator forms.

    This is intentionally small and conservative.
    """
    raw = locator.strip()
    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    add(raw)

    if raw.startswith("#"):
        add(raw[1:])

    pointer = _jsonpath_to_pointer(raw)
    if pointer is not None:
        add(pointer)

    if raw.startswith("#"):
        pointer = _jsonpath_to_pointer(raw[1:])
        if pointer is not None:
            add(pointer)

    if raw.startswith("/") and not raw.startswith("#/"):
        add("#" + raw)

    if raw.startswith("#/"):
        add(raw[1:])

    return tuple(candidates)


def _resolve_text_locator(text: str, locator: str) -> tuple[object | None, str | None]:
    loc = locator.strip()

    if loc == "text":
        return text, None

    if loc.startswith("line:"):
        number = loc.removeprefix("line:").strip()
        if not number.isdigit():
            return None, f"Invalid line locator: {locator!r}"
        line_no = int(number)
        lines = text.splitlines()
        if line_no < 1 or line_no > len(lines):
            return None, f"Line {line_no} out of range (1..{len(lines)})"
        return lines[line_no - 1], None

    if loc.startswith("lines:"):
        spec = loc.removeprefix("lines:").strip()
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", spec)
        if match is None:
            return None, f"Invalid lines locator: {locator!r}"
        start = int(match.group(1))
        end = int(match.group(2))
        if start < 1 or end < start:
            return None, f"Invalid line range {start}-{end}"
        lines = text.splitlines()
        if end > len(lines):
            return None, f"Line range {start}-{end} exceeds file length {len(lines)}"
        return "\n".join(lines[start - 1 : end]), None

    if loc.startswith("regex:"):
        pattern = loc.removeprefix("regex:")
        try:
            compiled = re.compile(pattern, re.MULTILINE | re.DOTALL)
        except re.error as exc:
            return None, f"Invalid regex locator {locator!r}: {exc}"
        match = compiled.search(text)
        if match is None:
            return None, f"Regex locator {locator!r} did not match"
        if match.groups():
            return match.group(1), None
        return match.group(0), None

    return None, (
        f"Unsupported locator for non-JSON file: {locator!r}. "
        "Use one of: text, line:<n>, lines:<a>-<b>, regex:<pattern>."
    )


def _jsonpath_to_pointer(locator: str) -> str | None:
    """
    Convert a narrow JSONPath-lite syntax into JSON Pointer-like form.

    Supported examples
    ------------------
    $.items[0].name   -> /items/0/name
    items[0].name     -> /items/0/name
    /items/0/name     -> /items/0/name
    #/items/0/name    -> /items/0/name
    """
    loc = locator.strip()
    if not loc:
        return None

    if loc.startswith("#/"):
        return loc[1:]
    if loc.startswith("/"):
        return loc

    loc = loc.removeprefix("#")

    loc = loc.removeprefix("$")

    loc = loc.removeprefix(".")

    if not loc:
        return "/"

    parts: list[str] = []
    i = 0
    while i < len(loc):
        ch = loc[i]

        if ch == ".":
            i += 1
            continue

        if ch == "[":
            end = loc.find("]", i + 1)
            if end == -1:
                return None
            token = loc[i + 1 : end].strip()
            if not token:
                return None
            if (token.startswith("'") and token.endswith("'")) or (
                token.startswith('"') and token.endswith('"')
            ):
                token = token[1:-1]
            parts.append(token)
            i = end + 1
            continue

        start = i
        while i < len(loc) and loc[i] not in ".[":
            i += 1
        token = loc[start:i].strip()
        if token:
            parts.append(token)

    return "/" + "/".join(parts)


__all__ = [
    "apply_structured_locator",
    "locator_candidates",
    "locator_parts",
    "read_text_auto",
    "resolve_locator_from_file",
    "resolve_single_locator_from_file",
    "split_locator",
]
