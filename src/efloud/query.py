from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from efloud.locator import resolve_locator_from_file
from efloud.manifest import load_latest_manifest
from efloud.query_targets import parse_query_target
from efloud.repository import Repository
from efloud.repository_compat import repository_exists, repository_source_entry
from efloud.repository_query import RepositoryQueryService
from efloud.source_aliases import source_by_id_or_alias
from efloud.source_results import local_materialized_path, manifest_entry_for_source
from efloud.store_inspection import (
    StoreSpec,
    generic_store_metadata,
    mirror_state_metadata,
    store_payload_for_specs,
    store_summary_entries,
    sync_manifest_metadata,
)

if TYPE_CHECKING:
    from efloud.models import EngineConfig
    from efloud.registry import SourceDefinition


def store_specs(cfg: EngineConfig) -> tuple[StoreSpec, ...]:
    root = Path(cfg.root)
    return (
        StoreSpec(
            store_id="repository_metadata",
            label="repository metadata",
            path=root / "metadata.sqlite",
            category="authoritative",
            path_kind="file",
            description="Authoritative SQLite repository metadata.",
            metadata_provider=generic_store_metadata,
        ),
        StoreSpec(
            store_id="repository_objects",
            label="repository object store",
            path=root / "objects",
            category="authoritative",
            path_kind="dir",
            description="Immutable content-addressed repository objects.",
        ),
        StoreSpec(
            store_id="sync_manifest",
            label="sync manifest",
            path=root / cfg.log_dir / cfg.manifest_filename,
            category="derived",
            path_kind="file",
            description="Compatibility sync-manifest projection.",
            metadata_provider=sync_manifest_metadata,
        ),
        StoreSpec(
            store_id="mirror_state",
            label="mirror state",
            path=root / cfg.state_filename,
            category="derived",
            path_kind="file",
            description="Compatibility hash-tree view of mirrored filesystem state.",
            metadata_provider=mirror_state_metadata,
        ),
        StoreSpec(
            store_id="http_cache_dir",
            label="HTTP cache directory",
            path=root / cfg.cache_dir / cfg.http_cache_dir,
            category="cached",
            path_kind="dir",
            description="Persistent HTTP response cache storage.",
        ),
        StoreSpec(
            store_id="rate_limits_dir",
            label="rate limit state directory",
            path=root / cfg.rate_limits_dir,
            category="cached",
            path_kind="dir",
            description="Rate-limit and backoff state persisted across sync runs.",
        ),
        StoreSpec(
            store_id="sync_log_dir",
            label="sync log directory",
            path=root / cfg.log_dir,
            category="derived",
            path_kind="dir",
            description="Directory containing compatibility sync artifacts.",
        ),
        StoreSpec(
            store_id="http_cache_sqlite",
            label="HTTP cache sqlite",
            path=root / cfg.cache_dir / cfg.http_cache_dir / "cache.sqlite",
            category="cached",
            path_kind="file",
            description="SQLite metadata store used by the persistent HTTP cache.",
            metadata_provider=generic_store_metadata,
        ),
    )


def _store_summary_entries(cfg: EngineConfig) -> list[dict[str, str]]:
    return store_summary_entries(store_specs(cfg))


def store_payload(store_id: str, *, cfg: EngineConfig) -> dict[str, Any]:
    return store_payload_for_specs(store_id, root=Path(cfg.root), specs=store_specs(cfg))


def index_payload(index_id: str, *, cfg: EngineConfig) -> dict[str, Any]:
    if cfg.index_registry is None:
        msg = "No index registry configured for this engine instance."
        raise ValueError(msg)
    root = Path(cfg.root)
    status = cfg.index_registry.status(index_id, root=root)
    definition = cfg.index_registry.definition(index_id)
    payload: dict[str, Any] = {
        "target_kind": "index",
        "index_id": index_id,
        "description": definition.description if definition is not None else "",
        "status": status.to_dict(),
    }
    loaded = cfg.index_registry.load(index_id, root=root)
    if loaded is not None:
        payload["payload"] = loaded.to_dict()
    return payload


def root_payload(cfg: EngineConfig) -> dict[str, Any]:
    return {
        "target_kind": "root",
        "repository_authoritative": repository_exists(cfg),
        "stores": _store_summary_entries(cfg),
        "indexes": list(cfg.index_registry.ids()) if cfg.index_registry is not None else [],
        "sources": [
            {
                "source_id": source.id,
                "kind": source.kind.value,
                "description": source.description,
                "url": source.url,
            }
            for source in cfg.sources
        ],
        "usage": [
            "query root",
            "query source:<source-id>",
            "query store:repository_metadata",
            "query store:repository_objects",
            "query store:sync_manifest",
            "query index:<index-id>",
            "query source:<source-id>#/some/json/pointer",
        ],
    }


def query_target(raw: str, *, cfg: EngineConfig, fetch_requested: bool = False) -> dict[str, Any]:
    target = parse_query_target(raw)

    if target.kind == "root":
        if target.locator is not None:
            msg = "Locators are not supported for the root target."
            raise ValueError(msg)
        return root_payload(cfg)

    if target.kind == "store":
        if target.identifier is None:
            msg = "Store target missing identifier."
            raise ValueError(msg)
        if target.locator is not None:
            msg = "Locators are not supported for store targets."
            raise ValueError(msg)
        return store_payload(target.identifier, cfg=cfg)

    if target.kind == "index":
        if target.identifier is None:
            msg = "Index target missing identifier."
            raise ValueError(msg)
        if target.locator is not None:
            msg = "Locators are not supported for index targets."
            raise ValueError(msg)
        return index_payload(target.identifier, cfg=cfg)

    source = source_by_id_or_alias(target.identifier or "", cfg.sources, cfg.source_aliases)
    if source is None:
        msg = f"Unknown source identifier: {target.identifier!r}"
        raise ValueError(msg)
    return source_payload(
        source,
        source_query=None,
        locator=target.locator,
        fetch_requested=fetch_requested,
        cfg=cfg,
    )


def _repository_local_path(entry: Mapping[str, object]) -> Path | None:
    for key in ("dest", "local"):
        value = entry.get(key)
        if isinstance(value, str):
            return Path(value)
    return None


def _repository_source_payload(
    source: SourceDefinition,
    *,
    source_query: str | None,
    locator: str | None,
    fetch_requested: bool,
    cfg: EngineConfig,
) -> dict[str, Any]:
    warnings: list[str] = []
    with Repository(Path(cfg.root)) as repository:
        entry = repository_source_entry(repository, source, cfg=cfg)
        local_path = _repository_local_path(entry)
        payload: dict[str, Any] = {
            "target_kind": "source",
            "source_id": source.id,
            "kind": source.kind.value,
            "description": source.description,
            "url": source.url,
            "query": source_query,
            "local_path": str(local_path) if local_path is not None else None,
            "manifest_entry": dict(entry),
            "repository_entry": dict(entry),
            "repository_backed": True,
            "warnings": warnings,
        }

        if source_query is not None and not fetch_requested:
            warnings.append("--fetch was not requested; query overrides are informational only.")
        if locator is None:
            return payload

        if source.kind.value in {"HTTP", "REST"}:
            repository_payload = RepositoryQueryService(repository).query(
                f"artifact:source:{source.id}#{locator}"
            )
            locator_payload = repository_payload.get("locator")
            payload["locator"] = locator_payload
            if isinstance(locator_payload, dict):
                error = locator_payload.get("error")
                if isinstance(error, str):
                    warnings.append(error)
            return payload

        result: dict[str, Any] = {
            "path": locator,
            "resolved_locator": None,
            "value": None,
            "error": None,
        }
        if local_path is None:
            result["error"] = "No repository-backed source materialization is available for locator evaluation."
        else:
            absolute = local_path if local_path.is_absolute() else Path(cfg.root) / local_path
            value, err, resolved_locator = resolve_locator_from_file(absolute, locator)
            result["value"] = value
            result["error"] = err
            result["resolved_locator"] = resolved_locator
            if err:
                warnings.append(err)
        payload["locator"] = result
        return payload


def source_payload(
    source: SourceDefinition,
    *,
    source_query: str | None,
    locator: str | None,
    fetch_requested: bool,
    cfg: EngineConfig,
) -> dict[str, Any]:
    if repository_exists(cfg):
        return _repository_source_payload(
            source,
            source_query=source_query,
            locator=locator,
            fetch_requested=fetch_requested,
            cfg=cfg,
        )

    root = Path(cfg.root)
    manifest, manifest_warnings, _ = load_latest_manifest(
        root / cfg.log_dir,
        cfg.manifest_filename,
        expected_root=root,
    )
    warnings = list(manifest_warnings)
    manifest_entry = manifest_entry_for_source(
        manifest if isinstance(manifest, Mapping) else None,
        source,
        aliases=cfg.source_aliases,
    )

    local_path = local_materialized_path(manifest_entry)

    payload: dict[str, Any] = {
        "target_kind": "source",
        "source_id": source.id,
        "kind": source.kind.value,
        "description": source.description,
        "url": source.url,
        "query": source_query,
        "local_path": str(local_path) if local_path is not None else None,
        "manifest_entry": dict(manifest_entry) if isinstance(manifest_entry, Mapping) else None,
        "repository_backed": False,
        "warnings": warnings,
    }

    if source_query is not None and not fetch_requested:
        warnings.append("--fetch was not requested; query overrides are informational only.")

    if locator is None:
        return payload

    result: dict[str, Any] = {
        "path": locator,
        "resolved_locator": None,
        "value": None,
        "error": None,
    }

    if local_path is None:
        result["error"] = "No cached source artifact is available for locator evaluation."
    else:
        absolute = local_path
        if not absolute.is_absolute():
            absolute = root / absolute
        value, err, resolved_locator = resolve_locator_from_file(absolute, locator)
        result["value"] = value
        result["error"] = err
        result["resolved_locator"] = resolved_locator
        if err:
            warnings.append(err)

    payload["locator"] = result
    return payload
