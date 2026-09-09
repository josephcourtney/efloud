"""One-way conversion from alpha EngineConfig into canonical execution inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from efloud.planning import SyncRequest
from efloud.registry import SourceKind
from efloud.runtime import EngineRuntime
from efloud.sources import CollectionSource, HttpSource, RestSource, RsyncSource, Source

if TYPE_CHECKING:
    from efloud.models import EngineConfig
    from efloud.registry import SourceDefinition


def _source(definition: SourceDefinition) -> Source:
    common = {
        "id": definition.id,
        "url": definition.url,
        "description": definition.description,
        "role": definition.role,
        "tags": definition.tags,
    }
    if definition.kind is SourceKind.HTTP:
        return HttpSource(
            **common,
            cache_name=definition.cache_name,
            expected_integrity=definition.expected_integrity,
        )
    if definition.kind is SourceKind.REST:
        return RestSource(
            **common,
            cache_name=definition.cache_name,
            expected_integrity=definition.expected_integrity,
        )
    if definition.kind is SourceKind.RSYNC:
        return RsyncSource(
            **common,
            paths=definition.rsync_paths or (),
            local_subpath=definition.local_subpath,
            port=definition.port,
            include=definition.include or (),
            exclude=definition.exclude or (),
        )
    if definition.kind is SourceKind.REST_BASE:
        return CollectionSource(**common)
    msg = f"Unsupported legacy source kind: {definition.kind!r}"
    raise ValueError(msg)


def legacy_sources(config: EngineConfig) -> tuple[Source, ...]:
    """Translate monolithic source records into typed canonical sources."""
    return tuple(_source(source) for source in config.sources)


def legacy_runtime(config: EngineConfig) -> EngineRuntime:
    """Translate operational path settings without mixing them into sync intent."""
    return EngineRuntime(
        root=config.root,
        http_dir=config.http_dir,
        cache_dir=config.cache_dir,
        mirrors_dir=config.mirrors_dir,
        rate_limits_dir=config.rate_limits_dir,
        http_cache_dir=config.http_cache_dir,
        runtime_progress=config.runtime_progress,
        remove_empty_dirs_after_rsync=config.remove_empty_dirs_after_rsync,
    )


def legacy_request(config: EngineConfig) -> SyncRequest:
    """Translate per-run alpha flags into the canonical request object."""
    sources = tuple(
        source for source in legacy_sources(config) if not (config.skip_rsync and isinstance(source, RsyncSource))
    )
    refresh_ids: set[str] = set()
    if config.refresh_http:
        refresh_ids.update(
            source.id for source in sources if isinstance(source, HttpSource | RestSource | CollectionSource)
        )
    if config.refresh_rsync:
        refresh_ids.update(source.id for source in sources if isinstance(source, RsyncSource))
    return SyncRequest(
        source_ids=tuple(source.id for source in sources),
        include_derived=not config.skip_derived,
        dry_run=config.dry_run,
        max_concurrency=config.http_concurrency,
        refresh=config.refresh_all,
        refresh_source_ids=tuple(sorted(refresh_ids)),
    )


__all__ = ["legacy_request", "legacy_runtime", "legacy_sources"]
