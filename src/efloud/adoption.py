from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.artifacts import sha256_hex
from efloud.registry import SourceKind
from efloud.repository_models import ContentId, ObservationId, OperationId, RunId, RunStatus, SourceId
from efloud.transport.http_utils import dest_for_http_source

if TYPE_CHECKING:
    from efloud.json_types import JsonObject
    from efloud.models import EngineConfig
    from efloud.registry import SourceDefinition
    from efloud.repository import Repository


type _AdoptionCandidate = tuple[str, Path, str | None]


@dataclass(frozen=True, slots=True)
class AdoptionResult:
    run_id: RunId
    observations: tuple[ObservationId, ...]
    unchanged_artifacts: tuple[str, ...]
    skipped_source_ids: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(slots=True)
class _AdoptionState:
    observations: list[ObservationId] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    succeeded_operations: int = 0
    failed_operations: int = 0


@dataclass(slots=True)
class _SourceAdoptionState:
    adopted_count: int = 0
    unchanged_count: int = 0
    errors: list[str] = field(default_factory=list)


def _source_definition(source: SourceDefinition) -> JsonObject:
    payload: JsonObject = {
        "description": source.description,
        "url": source.url,
        "kind": source.kind.value,
        "tags": list(source.tags),
        "adoption_registered": True,
    }
    if source.cache_name is not None:
        payload["cache_name"] = source.cache_name
    if source.local_subpath is not None:
        payload["local_subpath"] = source.local_subpath
    if source.mirror_mode is not None:
        payload["mirror_mode"] = source.mirror_mode.value
    if source.mirror_paths is not None:
        payload["mirror_paths"] = list(source.mirror_paths)
    if source.port is not None:
        payload["port"] = source.port
    if source.include is not None:
        payload["include"] = list(source.include)
    if source.exclude is not None:
        payload["exclude"] = list(source.exclude)
    if source.role is not None:
        payload["role"] = source.role
    return payload


def _http_candidate(cfg: EngineConfig, source: SourceDefinition) -> _AdoptionCandidate | None:
    path = dest_for_http_source(
        Path(cfg.root) / cfg.http_dir,
        url=source.url,
        description=source.description,
        kind=source.kind.value,
        cache_name=source.cache_name,
    )
    return (f"adopted:{source.id}:http", path, None) if path.is_file() else None


def _rsync_candidates(cfg: EngineConfig, source: SourceDefinition) -> tuple[_AdoptionCandidate, ...]:
    root = Path(cfg.root) / cfg.mirrors_dir / (source.local_subpath or source.id)
    if not root.is_dir():
        return ()
    candidates: list[_AdoptionCandidate] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.name in {".mirror_meta.json", ".DS_Store"}:
            continue
        relative = path.relative_to(root).as_posix()
        candidates.append((f"adopted:{source.id}:path:{relative}", path, relative))
    return tuple(candidates)


def _source_candidates(cfg: EngineConfig, source: SourceDefinition) -> tuple[_AdoptionCandidate, ...]:
    if source.kind in {SourceKind.HTTP, SourceKind.REST}:
        candidate = _http_candidate(cfg, source)
        return () if candidate is None else (candidate,)
    if source.kind is SourceKind.RSYNC:
        return _rsync_candidates(cfg, source)
    return ()


def _content_id(path: Path) -> ContentId:
    return ContentId(f"sha256:{sha256_hex(path)}")


def _adopt_file(
    repository: Repository,
    *,
    artifact_key: str,
    path: Path,
    configured_source_id: str,
    source_relative_path: str | None,
    run_id: RunId,
    operation_id: OperationId,
    observed_at: float,
) -> ObservationId | None:
    content_id = _content_id(path)
    previous = repository.latest_observation(artifact_key)
    if previous is not None and previous.content_id == content_id and repository.verify_content(content_id):
        return None

    metadata: JsonObject = {
        "adoption": True,
        "historical_provenance_known": False,
        "configured_source_id": configured_source_id,
        "materialized_path": path.resolve().as_posix(),
    }
    if source_relative_path is not None:
        metadata["source_relative_path"] = source_relative_path
    observation = repository.ingest_path(
        artifact_key,
        path,
        run_id=run_id,
        operation_id=operation_id,
        source_id=None,
        observed_at=observed_at,
        metadata=metadata,
        materialization_kind="adopted-local",
    )
    return observation.observation_id


def _record_candidate_result(
    state: _AdoptionState,
    source_state: _SourceAdoptionState,
    *,
    artifact_key: str,
    observation_id: ObservationId | None,
) -> None:
    if observation_id is None:
        state.unchanged.append(artifact_key)
        source_state.unchanged_count += 1
        return
    state.observations.append(observation_id)
    source_state.adopted_count += 1


def _source_operation_details(
    source: SourceDefinition,
    candidates: tuple[_AdoptionCandidate, ...],
    state: _SourceAdoptionState,
) -> JsonObject:
    details: JsonObject = {
        "adoption": True,
        "configured_source_id": source.id,
        "historical_provenance_known": False,
        "candidate_count": len(candidates),
        "adopted_count": state.adopted_count,
        "unchanged_count": state.unchanged_count,
        "error_count": len(state.errors),
    }
    if state.errors:
        details["errors"] = list(state.errors)
    return details


def _adopt_source(
    repository: Repository,
    *,
    source: SourceDefinition,
    candidates: tuple[_AdoptionCandidate, ...],
    run_id: RunId,
    observed_at: float,
    state: _AdoptionState,
) -> None:
    operation_id = repository.start_operation(
        run_id=run_id,
        source_id=None,
        kind="adoption",
        subject=source.id,
        started_at=observed_at,
        parameters={
            "configured_source_id": source.id,
            "historical_provenance_known": False,
        },
    )
    source_state = _SourceAdoptionState()
    for artifact_key, path, relative in candidates:
        try:
            observation_id = _adopt_file(
                repository,
                artifact_key=artifact_key,
                path=path,
                configured_source_id=source.id,
                source_relative_path=relative,
                run_id=run_id,
                operation_id=operation_id,
                observed_at=observed_at,
            )
        except (OSError, ValueError) as exc:
            detail = f"{source.id}:{path}: {type(exc).__name__}: {exc}"
            source_state.errors.append(detail)
            state.errors.append(detail)
            continue
        _record_candidate_result(
            state,
            source_state,
            artifact_key=artifact_key,
            observation_id=observation_id,
        )

    failed = bool(source_state.errors)
    repository.finish_operation(
        operation_id,
        status="failed" if failed else "succeeded",
        finished_at=observed_at,
        details=_source_operation_details(source, candidates, source_state),
    )
    if failed:
        state.failed_operations += 1
    else:
        state.succeeded_operations += 1


def _run_status(state: _AdoptionState) -> RunStatus:
    if state.failed_operations and state.succeeded_operations:
        return "partial"
    if state.failed_operations:
        return "failed"
    return "succeeded"


def adopt_existing_store(
    repository: Repository,
    *,
    cfg: EngineConfig,
    observed_at: float | None = None,
) -> AdoptionResult:
    """Adopt retained local bytes without importing legacy provenance claims.

    The original files remain in place. Content is hashed into the repository CAS,
    and any observation created here records only the fact that the retained local
    file was observed during adoption. It does not claim a historical acquisition,
    source snapshot, completeness, or absence.
    """
    observed = time.time() if observed_at is None else observed_at
    for source in cfg.sources:
        repository.register_source(SourceId(source.id), _source_definition(source))
    run_id = repository.start_run(
        source_ids=(),
        started_at=observed,
        metadata={"adoption": True, "historical_provenance_known": False},
    )
    state = _AdoptionState()

    for source in cfg.sources:
        candidates = _source_candidates(cfg, source)
        if not candidates:
            state.skipped.append(source.id)
            continue
        _adopt_source(
            repository,
            source=source,
            candidates=candidates,
            run_id=run_id,
            observed_at=observed,
            state=state,
        )

    repository.finish_run(run_id, status=_run_status(state), finished_at=observed)
    return AdoptionResult(
        run_id=run_id,
        observations=tuple(state.observations),
        unchanged_artifacts=tuple(sorted(state.unchanged)),
        skipped_source_ids=tuple(sorted(set(state.skipped))),
        errors=tuple(state.errors),
    )


__all__ = ["AdoptionResult", "adopt_existing_store"]
