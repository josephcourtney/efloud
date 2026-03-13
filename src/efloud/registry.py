from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class SourceKind(StrEnum):
    HTTP = "HTTP"
    REST = "REST"
    REST_BASE = "REST_BASE"
    RSYNC = "RSYNC"


class MirrorMode(StrEnum):
    FULL = "full"
    PATHS = "paths"


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    description: str
    url: str
    kind: SourceKind

    cache_name: str | None = None
    local_subpath: str | None = None
    mirror_mode: MirrorMode | None = None
    mirror_paths: tuple[str, ...] | None = None

    include: tuple[str, ...] | None = None
    exclude: tuple[str, ...] | None = None

    role: str | None = None
    tags: tuple[str, ...] = ()


def source_ids(sources: Sequence[SourceDefinition]) -> tuple[str, ...]:
    return tuple(source.id for source in sources)


def source_by_id(source_id: str, sources: Sequence[SourceDefinition]) -> SourceDefinition | None:
    for source in sources:
        if source.id == source_id:
            return source
    return None


def iter_upstream_sources(sources: Sequence[SourceDefinition]) -> Iterable[SourceDefinition]:
    return tuple(sources)


def source_ids_for_kind(kind: SourceKind, sources: Sequence[SourceDefinition]) -> list[str]:
    return [source.id for source in sources if source.kind == kind]
