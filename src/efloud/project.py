from __future__ import annotations

import json
import math
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from efloud.api import Dataset, DatasetSpec, Engine, Repository, SyncResult
from efloud.collections import CollectionDefinition
from efloud.dataset_constraints import DatasetConstraints
from efloud.dataset_selectors import ExactSourceSnapshot, LatestCompleteSourceSnapshot, SourceSelection
from efloud.datasets import DatasetDefinition, DatasetSelection, ExactObservation, Latest, LatestAll, LatestBefore
from efloud.errors import EfloudError
from efloud.fs import atomic_write_text
from efloud.inventory import IntegrityExpectation
from efloud.json_types import JsonObject, JsonValue, is_json_object, is_json_value
from efloud.planning import SyncPlan, SyncRequest
from efloud.repository_models import stable_id
from efloud.sources import CollectionSource, HttpSource, LocalSource, RestSource, RsyncSource, Source

if TYPE_CHECKING:
    from efloud.adapters import AdapterRegistry
    from efloud.validation import ValidationRegistry

DECLARATION_VERSION = 1
_DEFAULT_FILENAME = "efloud.toml"
_NAMESPACED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.:/-]*$")


class ProjectError(EfloudError):
    """Declarative project loading, resolution, or locking failed."""


class ProjectSchemaError(ProjectError):
    """A declarative project file does not satisfy the supported schema."""


class ProviderResolutionError(ProjectError):
    """A declared advanced provider could not be resolved exactly."""


@dataclass(frozen=True, slots=True)
class ProviderReference:
    """Stable declarative reference to application-supplied collection behavior."""

    provider_id: str
    version: str
    parameters: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_namespaced(self.provider_id, field_name="provider.id")
        _require_text(self.version, field_name="provider.version")
        if not is_json_object(self.parameters):
            raise ProjectSchemaError("provider.parameters must be JSON-compatible")
        object.__setattr__(self, "parameters", dict(self.parameters))

    def to_dict(self) -> JsonObject:
        return {
            "id": self.provider_id,
            "version": self.version,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ProviderReference:
        _reject_unknown(value, {"id", "version", "parameters"}, context="provider")
        parameters = value.get("parameters", {})
        if not is_json_object(parameters):
            raise ProjectSchemaError("provider.parameters must be a table of JSON-compatible values")
        return cls(
            _text(value.get("id"), field_name="provider.id"),
            _text(value.get("version"), field_name="provider.version"),
            dict(parameters),
        )


class CollectionProvider(Protocol):
    """Application implementation named by a declarative collection provider reference."""

    @property
    def provider_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def build(
        self,
        *,
        source: CollectionSource,
        parameters: JsonObject,
        base_dir: Path,
    ) -> CollectionDefinition: ...


@dataclass(frozen=True, slots=True)
class DeclaredSource:
    """Open declarative source for non-built-in namespaced adapters."""

    id: str
    adapter_id: str
    config: JsonObject = field(default_factory=dict)
    description: str = ""
    role: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.id, field_name="source.id")
        _require_namespaced(self.adapter_id, field_name="source.adapter")
        if not is_json_object(self.config):
            raise ProjectSchemaError("source.config must be JSON-compatible")
        reserved = {"adapter_id", "description", "role", "tags"}.intersection(self.config)
        if reserved:
            raise ProjectSchemaError(f"source.config uses reserved keys: {sorted(reserved)}")
        object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(self, "tags", _tags(self.tags, field_name="source.tags"))

    def definition(self) -> JsonObject:
        payload: JsonObject = {
            "adapter_id": self.adapter_id,
            "description": self.description,
            "tags": list(self.tags),
            **self.config,
        }
        if self.role is not None:
            payload["role"] = self.role
        return payload


@dataclass(frozen=True, slots=True)
class SourceDeclaration:
    """Serializable source intent independent of acquisition state."""

    id: str
    adapter: str
    config: JsonObject
    description: str = ""
    role: str | None = None
    tags: tuple[str, ...] = ()
    adapter_version: str | None = None
    provider: ProviderReference | None = None

    def __post_init__(self) -> None:
        _require_text(self.id, field_name="source.id")
        _require_namespaced(self.adapter, field_name="source.adapter")
        if self.adapter_version is not None:
            _require_text(self.adapter_version, field_name="source.adapter_version")
        if not is_json_object(self.config):
            raise ProjectSchemaError("source.config must be JSON-compatible")
        if self.provider is not None and self.adapter != "efloud:collection":
            raise ProjectSchemaError("provider is supported only for efloud:collection in schema v1")
        if self.adapter == "efloud:collection" and self.provider is None:
            raise ProjectSchemaError("efloud:collection requires a provider reference")
        object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(self, "tags", _tags(self.tags, field_name="source.tags"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SourceDeclaration:
        allowed = {"id", "adapter", "adapter_version", "description", "role", "tags", "config", "provider"}
        _reject_unknown(value, allowed, context="source")
        config = value.get("config", {})
        if not is_json_object(config):
            raise ProjectSchemaError("source.config must be a table of JSON-compatible values")
        provider_value = value.get("provider")
        provider = None
        if provider_value is not None:
            if not isinstance(provider_value, Mapping):
                raise ProjectSchemaError("source.provider must be a table")
            provider = ProviderReference.from_mapping(provider_value)
        role = _optional_text(value.get("role"), field_name="source.role")
        adapter_version = _optional_text(value.get("adapter_version"), field_name="source.adapter_version")
        return cls(
            id=_text(value.get("id"), field_name="source.id"),
            adapter=_text(value.get("adapter"), field_name="source.adapter"),
            config=dict(config),
            description=_optional_text(value.get("description"), field_name="source.description") or "",
            role=role,
            tags=_string_tuple(value.get("tags", []), field_name="source.tags"),
            adapter_version=adapter_version,
            provider=provider,
        )

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "id": self.id,
            "adapter": self.adapter,
            "description": self.description,
            "tags": list(self.tags),
            "config": dict(self.config),
        }
        if self.role is not None:
            payload["role"] = self.role
        if self.adapter_version is not None:
            payload["adapter_version"] = self.adapter_version
        if self.provider is not None:
            payload["provider"] = self.provider.to_dict()
        return payload

    def materialize(self, *, base_dir: Path) -> Source:
        common = {
            "id": self.id,
            "description": self.description,
            "role": self.role,
            "tags": self.tags,
        }
        config = dict(self.config)
        if self.adapter == "efloud:http":
            return HttpSource(
                **common,
                url=_pop_text(config, "url", context=self.id),
                cache_name=_pop_optional_text(config, "cache_name", context=self.id),
                expected_integrity=_pop_integrity(config),
                **_empty_config(config, self.id),
            )
        if self.adapter == "efloud:rest":
            return RestSource(
                **common,
                url=_pop_text(config, "url", context=self.id),
                cache_name=_pop_optional_text(config, "cache_name", context=self.id),
                expected_integrity=_pop_integrity(config),
                **_empty_config(config, self.id),
            )
        if self.adapter == "efloud:local":
            raw_path = _pop_text(config, "path", context=self.id)
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = base_dir / path
            return LocalSource(
                **common,
                path=path.resolve(strict=False),
                artifact_key=_pop_optional_text(config, "artifact_key", context=self.id),
                media_type=_pop_optional_text(config, "media_type", context=self.id),
                expected_integrity=_pop_integrity(config),
                **_empty_config(config, self.id),
            )
        if self.adapter == "efloud:rsync":
            return RsyncSource(
                **common,
                url=_pop_text(config, "url", context=self.id),
                paths=_pop_text_tuple(config, "paths", context=self.id),
                local_subpath=_pop_optional_text(config, "local_subpath", context=self.id),
                port=_pop_optional_int(config, "port", context=self.id),
                include=_pop_text_tuple(config, "include", context=self.id),
                exclude=_pop_text_tuple(config, "exclude", context=self.id),
                **_empty_config(config, self.id),
            )
        if self.adapter == "efloud:collection":
            provider = self.provider
            if provider is None:
                raise ProjectSchemaError(f"Collection source {self.id!r} has no provider")
            return CollectionSource(
                **common,
                url=_pop_text(config, "url", context=self.id),
                provider_id=provider.provider_id,
                provider_version=provider.version,
                provider_parameters=provider.parameters,
                **_empty_config(config, self.id),
            )
        return DeclaredSource(
            id=self.id,
            adapter_id=self.adapter,
            config=config,
            description=self.description,
            role=self.role,
            tags=self.tags,
        )


@dataclass(frozen=True, slots=True)
class DatasetDeclaration:
    """Named declarative dataset selection intent."""

    name: str
    _definition: DatasetDefinition = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.name, field_name="dataset.name")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DatasetDeclaration:
        allowed = {"name", "selections", "metadata", "constraints"}
        _reject_unknown(value, allowed, context="dataset")
        name = _text(value.get("name"), field_name="dataset.name")
        definition = _dataset_definition(value)
        return cls(name, definition)

    @property
    def spec(self) -> DatasetSpec:
        return DatasetSpec(
            self._definition.selections,
            dict(self._definition.metadata),
            self._definition.constraints,
        )

    @property
    def specification_id(self) -> str:
        return str(self._definition.specification_id)

    def to_dict(self) -> JsonObject:
        return {"name": self.name, **self._definition.to_dict()}


@dataclass(frozen=True, slots=True)
class Project:
    """Human-editable declarative Efloud project loaded from ``efloud.toml``."""

    sources: tuple[SourceDeclaration, ...] = ()
    datasets: tuple[DatasetDeclaration, ...] = ()
    sync_request: SyncRequest = field(default_factory=SyncRequest)
    path: Path | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        source_ids = [item.id for item in self.sources]
        dataset_names = [item.name for item in self.datasets]
        if len(source_ids) != len(set(source_ids)):
            raise ProjectSchemaError("source ids must be unique")
        if len(dataset_names) != len(set(dataset_names)):
            raise ProjectSchemaError("dataset names must be unique")
        object.__setattr__(self, "sources", tuple(sorted(self.sources, key=lambda item: item.id)))
        object.__setattr__(self, "datasets", tuple(sorted(self.datasets, key=lambda item: item.name)))
        if self.path is not None:
            object.__setattr__(self, "path", self.path.expanduser().resolve(strict=False))

    @property
    def base_dir(self) -> Path:
        return self.path.parent if self.path is not None else Path.cwd().resolve()

    @property
    def declaration_id(self) -> str:
        return stable_id("project-declaration-v1", self.to_dict())

    @classmethod
    def load(cls, path: str | Path = _DEFAULT_FILENAME) -> Project:
        resolved = Path(path).expanduser().resolve(strict=True)
        try:
            value = tomllib.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ProjectSchemaError(str(exc)) from exc
        return cls.from_mapping(value, path=resolved)

    @classmethod
    def from_toml(cls, text: str, *, base_dir: str | Path | None = None) -> Project:
        try:
            value = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ProjectSchemaError(str(exc)) from exc
        path = None if base_dir is None else Path(base_dir).expanduser().resolve() / _DEFAULT_FILENAME
        return cls.from_mapping(value, path=path)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object], *, path: Path | None = None) -> Project:
        _reject_unknown(value, {"schema_version", "sync", "sources", "datasets"}, context="project")
        version = value.get("schema_version")
        if type(version) is not int or version != DECLARATION_VERSION:
            raise ProjectSchemaError(
                f"Unsupported efloud.toml schema version: {version!r}; expected {DECLARATION_VERSION}"
            )
        raw_sources = value.get("sources", [])
        raw_datasets = value.get("datasets", [])
        if not isinstance(raw_sources, list) or not all(isinstance(item, Mapping) for item in raw_sources):
            raise ProjectSchemaError("sources must be an array of tables")
        if not isinstance(raw_datasets, list) or not all(isinstance(item, Mapping) for item in raw_datasets):
            raise ProjectSchemaError("datasets must be an array of tables")
        raw_sync = value.get("sync", {})
        if not isinstance(raw_sync, Mapping):
            raise ProjectSchemaError("sync must be a table")
        return cls(
            sources=tuple(SourceDeclaration.from_mapping(item) for item in raw_sources),
            datasets=tuple(DatasetDeclaration.from_mapping(item) for item in raw_datasets),
            sync_request=_sync_request(raw_sync),
            path=path,
        )

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": DECLARATION_VERSION,
            "sync": self.sync_request.to_dict(),
            "sources": [item.to_dict() for item in self.sources],
            "datasets": [item.to_dict() for item in self.datasets],
        }

    def to_toml(self) -> str:
        return _project_toml(self)

    def write(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self.path
        if destination is None:
            raise ProjectError("No efloud.toml destination was supplied")
        destination = destination.expanduser().resolve(strict=False)
        atomic_write_text(destination, self.to_toml())
        return destination

    def dataset(self, name: str) -> DatasetSpec:
        for declaration in self.datasets:
            if declaration.name == name:
                return declaration.spec
        raise ProjectError(f"Unknown declared dataset: {name}")

    def materialize(
        self,
        *,
        providers: Mapping[str, CollectionProvider] | None = None,
    ) -> tuple[tuple[Source, ...], tuple[CollectionDefinition, ...]]:
        provider_map = providers or {}
        sources: list[Source] = []
        collections: list[CollectionDefinition] = []
        for declaration in self.sources:
            source = declaration.materialize(base_dir=self.base_dir)
            sources.append(source)
            if not isinstance(source, CollectionSource):
                continue
            reference = declaration.provider
            if reference is None:
                raise ProviderResolutionError(f"Collection source {source.id!r} has no provider")
            provider = provider_map.get(reference.provider_id)
            if provider is None:
                raise ProviderResolutionError(f"Unknown collection provider: {reference.provider_id}")
            if provider.provider_id != reference.provider_id or provider.version != reference.version:
                raise ProviderResolutionError(
                    f"Provider {reference.provider_id!r} version mismatch: "
                    f"declared {reference.version!r}, available {provider.version!r}"
                )
            definition = provider.build(
                source=source,
                parameters=dict(reference.parameters),
                base_dir=self.base_dir,
            )
            if definition.source_id != source.id:
                raise ProviderResolutionError(
                    f"Provider {reference.provider_id!r} returned definition for {definition.source_id!r}, "
                    f"expected {source.id!r}"
                )
            collections.append(definition)
        return tuple(sources), tuple(collections)

    def engine(
        self,
        repository: Repository,
        *,
        providers: Mapping[str, CollectionProvider] | None = None,
        adapters: AdapterRegistry | None = None,
        validators: ValidationRegistry | None = None,
    ) -> Engine:
        sources, collections = self.materialize(providers=providers)
        return Engine(
            repository,
            sources,
            adapters=adapters,
            validators=validators,
            collections=collections,
        )

    def plan(
        self,
        repository: Repository,
        *,
        providers: Mapping[str, CollectionProvider] | None = None,
        adapters: AdapterRegistry | None = None,
        validators: ValidationRegistry | None = None,
    ) -> SyncPlan:
        plan = self.engine(
            repository,
            providers=providers,
            adapters=adapters,
            validators=validators,
        ).plan(self.sync_request)
        self._check_adapter_versions(plan)
        return plan

    async def sync(
        self,
        repository: Repository,
        *,
        providers: Mapping[str, CollectionProvider] | None = None,
        adapters: AdapterRegistry | None = None,
        validators: ValidationRegistry | None = None,
    ) -> SyncResult:
        engine = self.engine(
            repository,
            providers=providers,
            adapters=adapters,
            validators=validators,
        )
        self._check_adapter_versions(engine.plan(self.sync_request))
        return await engine.sync(self.sync_request)

    def resolve_datasets(self, repository: Repository) -> dict[str, Dataset]:
        return {item.name: repository.datasets.resolve(item.spec) for item in self.datasets}

    def lock(
        self,
        repository: Repository,
        *,
        providers: Mapping[str, CollectionProvider] | None = None,
        adapters: AdapterRegistry | None = None,
        validators: ValidationRegistry | None = None,
        require_complete: bool = True,
    ) -> ProjectLock:
        from efloud.lockfile import ProjectLock

        sources, collections = self.materialize(providers=providers)
        engine = Engine(
            repository,
            sources,
            adapters=adapters,
            validators=validators,
            collections=collections,
        )
        plan = engine.plan(self.sync_request)
        self._check_adapter_versions(plan)
        source_locks = self._source_locks(repository, sources, plan, require_complete=require_complete)
        dataset_locks = self._dataset_locks(repository)
        return ProjectLock.create(
            declaration=self.to_dict(),
            sources=source_locks,
            datasets=dataset_locks,
        )

    def _check_adapter_versions(self, plan: SyncPlan) -> None:
        decisions = {item.source_id: item for item in plan.decisions}
        for source in self.sources:
            if source.adapter_version is None:
                continue
            decision = decisions.get(source.id)
            actual = None if decision is None else decision.adapter_version
            if actual != source.adapter_version:
                raise ProjectError(
                    f"Adapter {source.adapter!r} for source {source.id!r} resolved to version {actual!r}; "
                    f"declaration requires {source.adapter_version!r}"
                )

    def _source_locks(
        self,
        repository: Repository,
        sources: Sequence[Source],
        plan: SyncPlan,
        *,
        require_complete: bool,
    ) -> tuple[JsonObject, ...]:
        source_by_id = {item.id: item for item in sources}
        decision_by_id = {item.source_id: item for item in plan.decisions}
        result: list[JsonObject] = []
        for declaration in self.sources:
            materialized = source_by_id[declaration.id]
            record = repository.sources.get(declaration.id)
            if record is None or record.definition != materialized.definition():
                raise ProjectError(f"Repository does not contain the current definition of source {declaration.id!r}")
            snapshots = repository.sources.snapshots(declaration.id, limit=1)
            if not snapshots:
                raise ProjectError(f"Source {declaration.id!r} has no resolved snapshot")
            snapshot = snapshots[0]
            if require_complete and not snapshot.complete:
                raise ProjectError(f"Source {declaration.id!r} has no complete resolved snapshot")
            resolution: JsonObject | None = None
            if snapshot.complete:
                dataset = repository.datasets.resolve(DatasetSpec.source_snapshot(str(snapshot.snapshot_id)))
                decoded = json.loads(dataset.manifest().to_bytes())
                if not is_json_object(decoded):
                    raise ProjectError("Detached source resolution was not a JSON object")
                resolution = decoded
            decision = decision_by_id.get(declaration.id)
            if decision is None or decision.adapter_id is None or decision.adapter_version is None:
                raise ProjectError(f"No resolved adapter identity for source {declaration.id!r}")
            entry: JsonObject = {
                "source_id": declaration.id,
                "definition_id": str(record.revision_id),
                "definition": dict(record.definition),
                "adapter": {"id": decision.adapter_id, "version": decision.adapter_version},
                "snapshot": snapshot.to_dict(),
                "resolution": resolution,
            }
            if declaration.provider is not None:
                entry["provider"] = declaration.provider.to_dict()
            result.append(entry)
        return tuple(result)

    def _dataset_locks(self, repository: Repository) -> tuple[JsonObject, ...]:
        result: list[JsonObject] = []
        for declaration in self.datasets:
            dataset = repository.datasets.resolve(declaration.spec)
            decoded = json.loads(dataset.manifest().to_bytes())
            if not is_json_object(decoded):
                raise ProjectError("Detached dataset manifest was not a JSON object")
            result.append({
                "name": declaration.name,
                "specification_id": dataset.specification_id,
                "dataset_id": dataset.id,
                "content_identity": dataset.content_identity,
                "manifest": decoded,
            })
        return tuple(result)


def _dataset_definition(value: Mapping[str, object]) -> DatasetDefinition:
    raw_selections = value.get("selections")
    if not isinstance(raw_selections, list) or not raw_selections:
        raise ProjectSchemaError("dataset.selections must be a non-empty array of tables")
    selections = tuple(_dataset_selection(item) for item in raw_selections)
    metadata = value.get("metadata", {})
    if not is_json_object(metadata):
        raise ProjectSchemaError("dataset.metadata must be JSON-compatible")
    constraints = _dataset_constraints(value.get("constraints", {}))
    return DatasetDefinition(selections, dict(metadata), constraints)


def _dataset_selection(value: object) -> DatasetSelection:
    if not isinstance(value, Mapping):
        raise ProjectSchemaError("dataset selection must be a table")
    raw = dict(value)
    kind = _text(raw.pop("kind", None), field_name="dataset.selection.kind")
    role = _optional_text(raw.pop("role", None), field_name="dataset.selection.role")
    selector: ExactObservation | Latest | LatestBefore | LatestAll | SourceSelection | ExactSourceSnapshot | LatestCompleteSourceSnapshot
    if kind == "exact":
        selector = ExactObservation(_pop_text(raw, "observation_id", context=kind))
    elif kind == "latest":
        selector = Latest(_pop_text(raw, "artifact_key", context=kind))
    elif kind == "latest-before":
        selector = LatestBefore(
            _pop_text(raw, "artifact_key", context=kind),
            _pop_timestamp(raw, "timestamp", context=kind),
        )
    elif kind == "latest-all":
        selector = LatestAll(_pop_optional_timestamp(raw, "before", context=kind))
    elif kind == "source-selection":
        _pop_time_basis(raw, context=kind)
        selector = SourceSelection(
            source_id=_pop_optional_text(raw, "source_id", context=kind),
            role=_pop_optional_text(raw, "role_filter", context=kind),
            tags=_pop_text_tuple(raw, "tags", context=kind),
            prefix=_pop_optional_text(raw, "prefix", context=kind) or "",
            after=_pop_optional_timestamp(raw, "after", context=kind),
            before=_pop_optional_timestamp(raw, "before", context=kind),
        )
    elif kind == "source-snapshot":
        selector = ExactSourceSnapshot(_pop_text(raw, "snapshot_id", context=kind))
    elif kind == "latest-complete-source-snapshot":
        _pop_time_basis(raw, context=kind)
        selector = LatestCompleteSourceSnapshot(
            _pop_text(raw, "source_id", context=kind),
            _pop_optional_timestamp(raw, "before", context=kind),
        )
    else:
        raise ProjectSchemaError(f"Unsupported dataset selection kind: {kind!r}")
    _empty_config(raw, f"dataset selection {kind!r}")
    return DatasetSelection(selector, role)


def _dataset_constraints(value: object) -> DatasetConstraints:
    if value is None:
        return DatasetConstraints()
    if not isinstance(value, Mapping):
        raise ProjectSchemaError("dataset.constraints must be a table")
    raw = dict(value)
    same_run = _pop_bool(raw, "same_run", default=False, context="dataset.constraints")
    complete = _pop_bool(raw, "complete_snapshots", default=False, context="dataset.constraints")
    skew = _pop_optional_number(raw, "max_observation_skew", context="dataset.constraints")
    validations_raw = raw.pop("validations", [])
    if not isinstance(validations_raw, list):
        raise ProjectSchemaError("dataset.constraints.validations must be an array")
    validations: list[tuple[str, str]] = []
    for item in validations_raw:
        if not isinstance(item, list) or len(item) != 2 or not all(isinstance(part, str) and part for part in item):
            raise ProjectSchemaError("each validation constraint must be [validator, version]")
        validations.append((item[0], item[1]))
    _empty_config(raw, "dataset.constraints")
    return DatasetConstraints(
        same_run=same_run,
        max_observation_skew=skew,
        complete_snapshots=complete,
        validations=tuple(validations),
    )


def _sync_request(value: Mapping[str, object]) -> SyncRequest:
    raw = dict(value)
    source_ids_value = raw.pop("source_ids", None)
    source_ids = None if source_ids_value is None else _string_tuple(source_ids_value, field_name="sync.source_ids")
    request = SyncRequest(
        source_ids=source_ids,
        include_derived=_bool(raw.pop("include_derived", True), field_name="sync.include_derived"),
        dry_run=_bool(raw.pop("dry_run", False), field_name="sync.dry_run"),
        max_concurrency=_int(raw.pop("max_concurrency", 4), field_name="sync.max_concurrency"),
        refresh=_bool(raw.pop("refresh", False), field_name="sync.refresh"),
        refresh_source_ids=_string_tuple(raw.pop("refresh_source_ids", []), field_name="sync.refresh_source_ids"),
    )
    _empty_config(raw, "sync")
    return request


def _project_toml(project: Project) -> str:
    lines = [f"schema_version = {DECLARATION_VERSION}", "", "[sync]"]
    sync = project.sync_request.to_dict()
    for key in ("source_ids", "include_derived", "dry_run", "max_concurrency", "refresh", "refresh_source_ids"):
        value = sync[key]
        if value is not None:
            lines.append(f"{key} = {_toml_value(value)}")
    for source in project.sources:
        lines.extend(("", "[[sources]]", f"id = {_toml_value(source.id)}", f"adapter = {_toml_value(source.adapter)}"))
        if source.adapter_version is not None:
            lines.append(f"adapter_version = {_toml_value(source.adapter_version)}")
        if source.description:
            lines.append(f"description = {_toml_value(source.description)}")
        if source.role is not None:
            lines.append(f"role = {_toml_value(source.role)}")
        if source.tags:
            lines.append(f"tags = {_toml_value(list(source.tags))}")
        lines.append("[sources.config]")
        for key in sorted(source.config):
            lines.append(f"{_toml_key(key)} = {_toml_value(source.config[key])}")
        if source.provider is not None:
            lines.extend((
                "[sources.provider]",
                f"id = {_toml_value(source.provider.provider_id)}",
                f"version = {_toml_value(source.provider.version)}",
                f"parameters = {_toml_value(source.provider.parameters)}",
            ))
    for dataset in project.datasets:
        definition = dataset.to_dict()
        lines.extend(("", "[[datasets]]", f"name = {_toml_value(dataset.name)}"))
        metadata = definition.get("metadata", {})
        if metadata:
            lines.append(f"metadata = {_toml_value(metadata)}")
        constraints = definition.get("constraints")
        if constraints is not None:
            lines.append(f"constraints = {_toml_value(constraints)}")
        selections = definition.get("selections")
        if not isinstance(selections, list):
            raise ProjectSchemaError(f"Dataset {dataset.name!r} has invalid selections")
        for selection in selections:
            if not isinstance(selection, dict):
                raise ProjectSchemaError(f"Dataset {dataset.name!r} has invalid selection")
            lines.append("[[datasets.selections]]")
            for key in sorted(selection):
                value = selection[key]
                if value is not None:
                    lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _toml_key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else json.dumps(value, ensure_ascii=False)


def _toml_value(value: JsonValue) -> str:
    if value is None:
        raise ProjectSchemaError("TOML cannot represent null values; omit optional values instead")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProjectSchemaError("TOML declarations require finite numbers")
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(
            f"{_toml_key(key)} = {_toml_value(item)}" for key, item in sorted(value.items())
        ) + " }"
    raise ProjectSchemaError(f"Unsupported TOML value: {type(value).__name__}")


def _require_namespaced(value: str, *, field_name: str) -> None:
    _require_text(value, field_name=field_name)
    if _NAMESPACED_ID.fullmatch(value) is None:
        raise ProjectSchemaError(f"{field_name} must be a stable namespaced identity")


def _require_text(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ProjectSchemaError(f"{field_name} must not be empty")


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectSchemaError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, *, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name=field_name)


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ProjectSchemaError(f"{field_name} must be an array of non-empty strings")
    return tuple(value)


def _tags(value: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ProjectSchemaError(f"{field_name} must contain non-empty strings")
    return tuple(sorted(set(value)))


def _bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ProjectSchemaError(f"{field_name} must be a boolean")
    return value


def _int(value: object, *, field_name: str) -> int:
    if type(value) is not int:
        raise ProjectSchemaError(f"{field_name} must be an integer")
    return value


def _timestamp(value: object, *, field_name: str) -> float:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ProjectSchemaError(f"{field_name} datetime must include an offset")
        return value.timestamp()
    if isinstance(value, str):
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ProjectSchemaError(f"{field_name} must be RFC 3339 or a Unix timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ProjectSchemaError(f"{field_name} datetime must include an offset")
        return parsed.timestamp()
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise ProjectSchemaError(f"{field_name} must be RFC 3339 or a finite Unix timestamp")
    return float(value)


def _reject_unknown(value: Mapping[str, object], allowed: set[str], *, context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProjectSchemaError(f"Unsupported {context} keys: {unknown}")


def _empty_config(config: Mapping[str, object], context: str) -> dict[str, object]:
    if config:
        raise ProjectSchemaError(f"Unsupported {context} configuration keys: {sorted(config)}")
    return {}


def _pop_text(config: dict[str, object], key: str, *, context: str) -> str:
    return _text(config.pop(key, None), field_name=f"{context}.{key}")


def _pop_optional_text(config: dict[str, object], key: str, *, context: str) -> str | None:
    return _optional_text(config.pop(key, None), field_name=f"{context}.{key}")


def _pop_text_tuple(config: dict[str, object], key: str, *, context: str) -> tuple[str, ...]:
    return _string_tuple(config.pop(key, []), field_name=f"{context}.{key}")


def _pop_optional_int(config: dict[str, object], key: str, *, context: str) -> int | None:
    value = config.pop(key, None)
    return None if value is None else _int(value, field_name=f"{context}.{key}")


def _pop_integrity(config: dict[str, object]) -> tuple[IntegrityExpectation, ...]:
    value = config.pop("expected_integrity", [])
    if not isinstance(value, list):
        raise ProjectSchemaError("expected_integrity must be an array of tables")
    result: list[IntegrityExpectation] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ProjectSchemaError("expected_integrity entries must be tables")
        raw = dict(item)
        algorithm = _pop_text(raw, "algorithm", context="expected_integrity")
        digest = _pop_text(raw, "digest", context="expected_integrity")
        required = _pop_bool(raw, "required", default=True, context="expected_integrity")
        metadata = raw.pop("metadata", {})
        if not is_json_object(metadata):
            raise ProjectSchemaError("expected_integrity.metadata must be JSON-compatible")
        _empty_config(raw, "expected_integrity")
        result.append(IntegrityExpectation(algorithm, digest, required=required, metadata=dict(metadata)))
    return tuple(result)


def _pop_bool(config: dict[str, object], key: str, *, default: bool, context: str) -> bool:
    return _bool(config.pop(key, default), field_name=f"{context}.{key}")


def _pop_optional_number(config: dict[str, object], key: str, *, context: str) -> float | None:
    value = config.pop(key, None)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise ProjectSchemaError(f"{context}.{key} must be a finite number")
    return float(value)


def _pop_timestamp(config: dict[str, object], key: str, *, context: str) -> float:
    return _timestamp(config.pop(key, None), field_name=f"{context}.{key}")


def _pop_optional_timestamp(config: dict[str, object], key: str, *, context: str) -> float | None:
    value = config.pop(key, None)
    return None if value is None else _timestamp(value, field_name=f"{context}.{key}")


def _pop_time_basis(config: dict[str, object], *, context: str) -> None:
    value = config.pop("time_basis", "repository-observation")
    if value != "repository-observation":
        raise ProjectSchemaError(f"{context}.time_basis must be 'repository-observation'")


__all__ = [
    "CollectionProvider",
    "DECLARATION_VERSION",
    "DatasetDeclaration",
    "DeclaredSource",
    "Project",
    "ProjectError",
    "ProjectSchemaError",
    "ProviderReference",
    "ProviderResolutionError",
    "SourceDeclaration",
]
