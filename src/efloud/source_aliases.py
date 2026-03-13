from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

AliasMap = Mapping[str, tuple[str, ...] | list[str]]


class SupportsSourceId(Protocol):
    id: str


class SourceAliasResolver:
    """
    Resolve source identifiers through a user-supplied alias map.

    The engine itself stays agnostic about domain-specific naming, while
    applications can supply compatibility aliases such as:

        {
            "new_name": ("old_name",),
            "old_name": ("new_name",),
        }

    Resolution policy is intentionally conservative:
      1. exact source id match wins
      2. aliases are consulted in declared order
      3. first matching source id is returned
    """

    def __init__(self, aliases: AliasMap | None = None) -> None:
        self._aliases: dict[str, tuple[str, ...]] = {
            str(key): tuple(str(value) for value in values) for key, values in (aliases or {}).items()
        }

    @property
    def aliases(self) -> dict[str, tuple[str, ...]]:
        return dict(self._aliases)

    def candidates(self, source_id: str) -> tuple[str, ...]:
        values = [source_id]
        for alias in self._aliases.get(source_id, ()):  # declared order matters
            if alias not in values:
                values.append(alias)
        for canonical, aliases in self._aliases.items():
            if source_id == canonical:
                continue
            if source_id in aliases and canonical not in values:
                values.append(canonical)
        return tuple(values)

    def resolve_id(self, source_id: str, sources: Sequence[SupportsSourceId]) -> str | None:
        available = {source.id for source in sources}
        for candidate in self.candidates(source_id):
            if candidate in available:
                return candidate
        return None

    def source_by_id[TSource: SupportsSourceId](
        self, source_id: str, sources: Sequence[TSource]
    ) -> TSource | None:
        resolved = self.resolve_id(source_id, sources)
        if resolved is None:
            return None
        for source in sources:
            if source.id == resolved:
                return source
        return None


def source_by_id_or_alias[TSource: SupportsSourceId](
    source_id: str,
    sources: Sequence[TSource],
    aliases: AliasMap | None = None,
) -> TSource | None:
    return SourceAliasResolver(aliases).source_by_id(source_id, sources)


__all__ = [
    "AliasMap",
    "SourceAliasResolver",
    "SupportsSourceId",
    "source_by_id_or_alias",
]
