from __future__ import annotations

from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal, Self

from efloud.dataset_constraints import DatasetConstraintError as _InternalDatasetConstraintError
from efloud.dataset_constraints import DatasetConstraints
from efloud.dataset_export import DetachedDatasetManifest, export_dataset_manifest
from efloud.dataset_selectors import ExactSourceSnapshot, LatestCompleteSourceSnapshot, SourceSelection
from efloud.datasets import (
    DatasetDefinition,
    DatasetSelection,
    ExactObservation,
    ImmutableDataset,
    Latest,
    LatestAll,
    LatestBefore,
    resolve_dataset,
)
from efloud.engine import Engine as _EngineCore
from efloud.errors import (
    DatasetConstraintError,
    DatasetError,
    ExecutionError,
    ExportError,
    RepositoryBusyError,
    RepositoryOpenError,
    RepositorySchemaError,
)
from efloud.maintenance import AuditReport, RepositoryMaintenance
from efloud.materialization import DatasetMaterializer, ExportPlan, ExportStrategy
from efloud.read_only_repository import ReadOnlyRepository
from efloud.repository import Repository as _WritableRepository
from efloud.writer_coordination import RepositoryBusyError as _InternalRepositoryBusyError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime, timedelta
    from types import TracebackType

    from efloud.adapters import AdapterRegistry
    from efloud.json_types import JsonObject
    from efloud.metadata_store import RunRecord, SourceRecord
    from efloud.planning import SyncPlan, SyncRequest
    from efloud.repository_models import ArtifactObservation, ProvenanceEdge, SourceSnapshot
    from efloud.sources import Source
    from efloud.validation import ValidationRegistry

RepositoryMode = Literal["r", "rw"]
RepositoryLocation = str | PathLike[str]


def _path_for(location: RepositoryLocation) -> Path:
    return Path(location).expanduser()


def _aware_timestamp(value: datetime | None, *, field_name: str) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{field_name} must be timezone-aware"
        raise ValueError(msg)
    return value.timestamp()


def _required_timestamp(value: datetime, *, field_name: str) -> float:
    timestamp = _aware_timestamp(value, field_name=field_name)
    if timestamp is None:
        msg = f"{field_name} is required"
        raise ValueError(msg)
    return timestamp


def _duration_seconds(value: timedelta | None, *, field_name: str) -> float | None:
    if value is None:
        return None
    seconds = value.total_seconds()
    if seconds < 0:
        msg = f"{field_name} must not be negative"
        raise ValueError(msg)
    return seconds


def _existing_repository_root(location: RepositoryLocation) -> Path:
    root = _path_for(location).resolve(strict=True)
    if not root.is_dir():
        msg = f"Repository location is not a directory: {root}"
        raise RepositoryOpenError(msg)
    return root


def _open_repository_view(root: Path, mode: RepositoryMode) -> ReadOnlyRepository | _WritableRepository:
    if mode == "r":
        return ReadOnlyRepository(root)
    with ReadOnlyRepository(root):
        pass
    return _WritableRepository(root)


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """Immutable, compositional dataset selection intent."""

    _selections: tuple[DatasetSelection, ...] = ()
    _metadata: JsonObject = field(default_factory=dict)
    _constraints: DatasetConstraints = field(default_factory=DatasetConstraints)

    @classmethod
    def exact_observation(cls, observation_id: str, *, role: str | None = None) -> DatasetSpec:
        return cls((DatasetSelection(ExactObservation(observation_id), role),))

    @classmethod
    def latest(cls, artifact_key: str, *, role: str | None = None) -> DatasetSpec:
        return cls((DatasetSelection(Latest(artifact_key), role),))

    @classmethod
    def latest_before(cls, artifact_key: str, before: datetime, *, role: str | None = None) -> DatasetSpec:
        return cls((
            DatasetSelection(
                LatestBefore(artifact_key, _required_timestamp(before, field_name="before")),
                role,
            ),
        ))

    @classmethod
    def latest_all(cls, *, before: datetime | None = None) -> DatasetSpec:
        return cls((DatasetSelection(LatestAll(_aware_timestamp(before, field_name="before"))),))

    @classmethod
    def source(
        cls,
        source_id: str | None = None,
        *,
        role: str | None = None,
        tags: tuple[str, ...] = (),
        prefix: str = "",
        after: datetime | None = None,
        before: datetime | None = None,
        member_role: str | None = None,
    ) -> DatasetSpec:
        selector = SourceSelection(
            source_id=source_id,
            role=role,
            tags=tuple(tags),
            prefix=prefix,
            after=_aware_timestamp(after, field_name="after"),
            before=_aware_timestamp(before, field_name="before"),
        )
        return cls((DatasetSelection(selector, member_role),))

    @classmethod
    def source_snapshot(cls, snapshot_id: str, *, role: str | None = None) -> DatasetSpec:
        return cls((DatasetSelection(ExactSourceSnapshot(snapshot_id), role),))

    @classmethod
    def latest_source_snapshot(
        cls,
        source_id: str,
        *,
        before: datetime | None = None,
        role: str | None = None,
    ) -> DatasetSpec:
        selector = LatestCompleteSourceSnapshot(source_id, _aware_timestamp(before, field_name="before"))
        return cls((DatasetSelection(selector, role),))

    def include(self, other: DatasetSpec) -> DatasetSpec:
        """Combine selections while preserving this specification's policy metadata."""
        return DatasetSpec(self._selections + other._selections, dict(self._metadata), self._constraints)

    def with_metadata(self, **metadata: object) -> DatasetSpec:
        updated: JsonObject = dict(self._metadata)
        for key, value in metadata.items():
            if value is None or isinstance(value, str | int | float | bool | list | dict):
                updated[key] = value
            else:
                msg = f"Dataset metadata value is not JSON-compatible: {key}"
                raise TypeError(msg)
        return DatasetSpec(self._selections, updated, self._constraints)

    def require(
        self,
        *,
        same_run: bool | None = None,
        max_observation_skew: timedelta | None = None,
        complete_snapshots: bool | None = None,
        validations: tuple[tuple[str, str], ...] | None = None,
    ) -> DatasetSpec:
        current = self._constraints
        constraints = DatasetConstraints(
            same_run=current.same_run if same_run is None else same_run,
            max_observation_skew=(
                current.max_observation_skew
                if max_observation_skew is None
                else _duration_seconds(max_observation_skew, field_name="max_observation_skew")
            ),
            complete_snapshots=current.complete_snapshots if complete_snapshots is None else complete_snapshots,
            validations=current.validations if validations is None else tuple(validations),
        )
        return DatasetSpec(self._selections, dict(self._metadata), constraints)

    def _definition(self) -> DatasetDefinition:
        if not self._selections:
            msg = "DatasetSpec must contain at least one selection"
            raise DatasetError(msg)
        return DatasetDefinition(self._selections, dict(self._metadata), self._constraints)


@dataclass(frozen=True, slots=True)
class DatasetMember:
    artifact_key: str
    observation_id: str
    content_id: str
    role: str | None


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Canonical detached dataset manifest independent of repository storage."""

    _manifest: DetachedDatasetManifest

    @property
    def dataset_id(self) -> str:
        return self._manifest.dataset_id

    @property
    def content_identity(self) -> str:
        return self._manifest.content_identity

    @property
    def definition(self) -> JsonObject:
        return dict(self._manifest.definition)

    def to_bytes(self) -> bytes:
        return self._manifest.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> DatasetManifest:
        try:
            return cls(DetachedDatasetManifest.from_bytes(data))
        except (KeyError, TypeError, ValueError) as exc:
            raise DatasetError(str(exc)) from exc

    def verify(self, root: RepositoryLocation) -> bool:
        return self._manifest.verify(_path_for(root))


@dataclass(frozen=True, slots=True)
class Dataset:
    """Exact immutable dataset resolved against one repository state."""

    _dataset: ImmutableDataset

    @property
    def id(self) -> str:
        return str(self._dataset.id)

    @property
    def specification_id(self) -> str:
        return str(self._dataset.specification_id)

    @property
    def content_identity(self) -> str:
        return self._dataset.content_identity

    def members(self) -> tuple[DatasetMember, ...]:
        return tuple(
            DatasetMember(str(item.artifact_key), str(item.observation_id), str(item.content_id), item.role)
            for item in self._dataset.artifacts()
        )

    def member(self, artifact_key: str) -> DatasetMember:
        try:
            item = self._dataset.artifact(artifact_key)
        except KeyError as exc:
            raise DatasetError(str(exc)) from exc
        return DatasetMember(str(item.artifact_key), str(item.observation_id), str(item.content_id), item.role)

    def open(self, artifact_key: str) -> BinaryIO:
        try:
            return self._dataset.open(artifact_key)
        except (FileNotFoundError, KeyError) as exc:
            raise DatasetError(str(exc)) from exc

    def verify(self) -> bool:
        return self._dataset.verify()

    def manifest(self, *, paths: Mapping[str, str] | None = None) -> DatasetManifest:
        try:
            return DatasetManifest(export_dataset_manifest(self._dataset, paths=paths))
        except (KeyError, TypeError, ValueError) as exc:
            raise DatasetError(str(exc)) from exc

    def plan_export(
        self,
        destination: RepositoryLocation,
        *,
        paths: Mapping[str, str] | None = None,
        strategy: ExportStrategy = "auto",
    ) -> ExportPlan:
        try:
            manifest = self.manifest(paths=paths)
            return DatasetMaterializer(self._dataset.repository).plan(
                manifest._manifest,
                _path_for(destination),
                strategy=strategy,
            )
        except DatasetError as exc:
            raise ExportError(str(exc)) from exc
        except (FileNotFoundError, FileExistsError, OSError, TypeError, ValueError) as exc:
            raise ExportError(str(exc)) from exc

    def export(
        self,
        destination: RepositoryLocation,
        *,
        paths: Mapping[str, str] | None = None,
        strategy: ExportStrategy = "auto",
        dry_run: bool = False,
    ) -> DatasetManifest:
        try:
            manifest = self.manifest(paths=paths)
            DatasetMaterializer(self._dataset.repository).export(
                manifest._manifest,
                _path_for(destination),
                strategy=strategy,
                dry_run=dry_run,
            )
        except DatasetError as exc:
            raise ExportError(str(exc)) from exc
        except (FileNotFoundError, FileExistsError, OSError, TypeError, ValueError) as exc:
            raise ExportError(str(exc)) from exc
        return manifest


class _DatasetCollection:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def resolve(self, spec: DatasetSpec) -> Dataset:
        try:
            manifest = resolve_dataset(self._repository._view, spec._definition())
            return Dataset(ImmutableDataset(self._repository._view, manifest))
        except _InternalDatasetConstraintError as exc:
            raise DatasetConstraintError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise DatasetError(str(exc)) from exc

    def freeze(self, spec: DatasetSpec) -> Dataset:
        writer = self._repository._require_writer()
        try:
            return Dataset(writer.resolve_dataset(spec._definition()))
        except _InternalDatasetConstraintError as exc:
            raise DatasetConstraintError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise DatasetError(str(exc)) from exc

    def get(self, dataset_id: str) -> Dataset:
        try:
            return Dataset(self._repository._view.dataset(dataset_id))
        except KeyError as exc:
            raise DatasetError(str(exc)) from exc


class _ArtifactCollection:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def keys(self) -> tuple[str, ...]:
        return tuple(str(key) for key in self._repository._view.artifact_keys())

    def latest(self, artifact_key: str, *, before: datetime | None = None) -> ArtifactObservation | None:
        return self._repository._view.latest_observation(
            artifact_key,
            before=_aware_timestamp(before, field_name="before"),
        )

    def history(self, artifact_key: str) -> tuple[ArtifactObservation, ...]:
        return self._repository._view.observations_for(artifact_key)

    def open(self, artifact_key: str, *, before: datetime | None = None) -> BinaryIO:
        observation = self.latest(artifact_key, before=before)
        if observation is None:
            msg = f"Unknown artifact: {artifact_key}"
            raise DatasetError(msg)
        return self._repository._view.open_content(observation.content_id)


class _SourceCollection:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def all(self) -> tuple[SourceRecord, ...]:
        return self._repository._view.sources()

    def get(self, source_id: str) -> SourceRecord | None:
        return self._repository._view.source(source_id)

    def snapshots(self, source_id: str, *, limit: int | None = 50) -> tuple[SourceSnapshot, ...]:
        if limit is not None and limit < 0:
            msg = "limit must be nonnegative or None"
            raise ValueError(msg)
        return self._repository._view.source_snapshots_for(source_id, limit=limit)


class _RunCollection:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def get(self, run_id: str) -> RunRecord | None:
        return self._repository._view.run(run_id)

    def recent(self, *, limit: int = 50) -> tuple[RunRecord, ...]:
        if limit < 0:
            msg = "limit must be nonnegative"
            raise ValueError(msg)
        return self._repository._view.recent_runs(limit=limit)


class _ProvenanceCollection:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def inputs(self, observation_id: str) -> tuple[ProvenanceEdge, ...]:
        return self._repository._view.provenance_inputs(observation_id)


class _MaintenanceFacade:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def audit(self) -> AuditReport:
        return RepositoryMaintenance(self._repository.root).fsck()


class Repository:
    """Explicitly opened public repository capability."""

    def __init__(
        self,
        root: Path,
        mode: RepositoryMode,
        view: ReadOnlyRepository | _WritableRepository,
    ) -> None:
        self.root = root
        self.mode = mode
        self._view = view

    @classmethod
    def create(cls, location: RepositoryLocation) -> Repository:
        root = _path_for(location).resolve()
        if root.exists():
            msg = f"Repository location already exists: {root}"
            raise RepositoryOpenError(msg)
        try:
            root.mkdir(parents=True)
            view = _WritableRepository(root)
        except _InternalRepositoryBusyError as exc:
            raise RepositoryBusyError(str(exc)) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise RepositoryOpenError(str(exc)) from exc
        return cls(root, "rw", view)

    @classmethod
    def open(cls, location: RepositoryLocation, *, mode: RepositoryMode = "r") -> Repository:
        if mode not in {"r", "rw"}:
            msg = f"Unsupported repository mode: {mode!r}"
            raise RepositoryOpenError(msg)
        try:
            root = _existing_repository_root(location)
            view = _open_repository_view(root, mode)
        except _InternalRepositoryBusyError as exc:
            raise RepositoryBusyError(str(exc)) from exc
        except RuntimeError as exc:
            raise RepositorySchemaError(str(exc)) from exc
        except RepositoryOpenError:
            raise
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise RepositoryOpenError(str(exc)) from exc
        return cls(root, mode, view)

    def __enter__(self) -> Self:
        """Return this opened repository capability."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the underlying repository stores."""
        self.close()

    def close(self) -> None:
        self._view.close()

    def _require_writer(self) -> _WritableRepository:
        if self.mode != "rw" or not isinstance(self._view, _WritableRepository):
            msg = "Operation requires Repository.open(..., mode='rw')"
            raise RepositoryOpenError(msg)
        return self._view

    @property
    def datasets(self) -> _DatasetCollection:
        return _DatasetCollection(self)

    @property
    def artifacts(self) -> _ArtifactCollection:
        return _ArtifactCollection(self)

    @property
    def sources(self) -> _SourceCollection:
        return _SourceCollection(self)

    @property
    def runs(self) -> _RunCollection:
        return _RunCollection(self)

    @property
    def provenance(self) -> _ProvenanceCollection:
        return _ProvenanceCollection(self)

    @property
    def maintenance(self) -> _MaintenanceFacade:
        return _MaintenanceFacade(self)


@dataclass(frozen=True, slots=True)
class SyncResult:
    ok: bool
    plan_id: str
    run_id: str | None
    observation_ids: tuple[str, ...]
    skipped_source_ids: tuple[str, ...]
    failed_source_ids: tuple[str, ...]
    diagnostics: tuple[JsonObject, ...]


class Engine:
    """Public acquisition orchestrator over an explicitly opened writable repository."""

    def __init__(
        self,
        repository: Repository,
        sources: Sequence[Source],
        *,
        adapters: AdapterRegistry | None = None,
        validators: ValidationRegistry | None = None,
    ) -> None:
        writer = repository._require_writer()
        self.repository = repository
        self.sources = tuple(sources)
        self._core = _EngineCore(
            writer,
            self.sources,
            adapters=adapters,
            validators=validators,
        )

    def plan(self, request: SyncRequest | None = None) -> SyncPlan:
        return self._core.plan(request)

    async def sync(self, request: SyncRequest | None = None) -> SyncResult:
        try:
            result = await self._core.sync(request)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ExecutionError(str(exc)) from exc
        failed_source_ids = tuple(
            sorted(
                operation.operation_key.removeprefix("source:")
                for operation in result.execution.operations
                if operation.operation_key.startswith("source:") and operation.status == "failed"
            )
        )
        diagnostics: tuple[JsonObject, ...] = tuple(
            {
                "operation_key": operation.operation_key,
                "status": operation.status,
                "details": dict(operation.details),
            }
            for operation in result.execution.operations
        )
        return SyncResult(
            ok=result.ok,
            plan_id=result.plan.plan_id,
            run_id=None if result.repository_run_id is None else str(result.repository_run_id),
            observation_ids=tuple(str(value) for value in result.observations),
            skipped_source_ids=result.skipped_source_ids,
            failed_source_ids=failed_source_ids,
            diagnostics=diagnostics,
        )


__all__ = [
    "Dataset",
    "DatasetManifest",
    "DatasetMember",
    "DatasetSpec",
    "Engine",
    "Repository",
    "RepositoryLocation",
    "RepositoryMode",
    "SyncResult",
]
