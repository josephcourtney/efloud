from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from efloud.locator import split_locator

TargetKind = Literal["root", "store", "source", "index"]


@dataclass(frozen=True)
class QueryTarget:
    kind: TargetKind
    identifier: str | None
    locator: str | None
    raw: str


_PREFIXES: dict[str, TargetKind] = {
    "store:": "store",
    "source:": "source",
    "index:": "index",
}


def parse_query_target(raw: str) -> QueryTarget:
    text = raw.strip()
    if not text:
        msg = "Query target must not be empty."
        raise ValueError(msg)

    base, locator = split_locator(text)
    if base == "root":
        return QueryTarget(kind="root", identifier=None, locator=locator, raw=text)

    for prefix, kind in _PREFIXES.items():
        if base.startswith(prefix):
            identifier = base.removeprefix(prefix).strip()
            if not identifier:
                msg = f"Invalid {kind} target: {raw!r}"
                raise ValueError(msg)
            return QueryTarget(kind=kind, identifier=identifier, locator=locator, raw=text)

    msg = (
        f"Unsupported query target: {raw!r}. "
        "Use one of: root, source:<id>, store:<id>, index:<id>."
    )
    raise ValueError(msg)


__all__ = [
    "QueryTarget",
    "TargetKind",
    "parse_query_target",
]
