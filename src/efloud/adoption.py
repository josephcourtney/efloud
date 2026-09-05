from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.artifacts import sha256_hex
from efloud.registry import SourceKind
from efloud.repository_models import ContentId, ObservationId, RunId, SourceId
from efloud.transport.http_utils import dest_for_http_source

if TYPE_CHECKING:
    from collections.abc import Iterable

    from efloud.json_types import JsonObject
    from efloud.models import EngineConfig
    from efloud.registry import SourceDefinition
    from efloud.repository import Repository


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


def _source_definition(source: SourceDefinition) -> JsonObject:
    payload: JsonObject = {
        "description": source.description,
        "url": source.url,
        "kind": source.kind.value,
        "tags": list(source.tags),
        "adoption_registered": True,
    }
    if source.local_subpath is not None:
        payload["local_subpath"] = source.local_subpath
    if source.role is not None:
        payload["role"] = source.role
    return payload


def _http_candidate(cfg: EngineConfig, source: SourceDefinition) -> tuple[str, Path]:
    path = dest_for_http_source(
        Path(cfg.root) / cfg.http_dir,
        url=source.url,
        description=source.description,
        kind=source.kind.value,
        cache_name=source.cache_name,
    )
    return f"adopted:{source.id}:http", path


def _rsync_candidates(cfg: EngineConfig, source: SourceDefinition) -> Iterable[tuple[str, Path, str]]:
    root = Path(cfg.root) / cfg.mirrors_dir / (source.local_subpath or source.id)
    if not root.is_dir():
        return ()
    candidates: list[tuple[str, Path, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.name in {".mirror_meta.json", ".DS_Store"}:
            continue
        relative = path.relative_to(root).as_posix()
        candidates.append((f"adopted:{source.id}:path:{relative}", path, relative))
    return tuple(candidates)


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
    operation_id,
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

    observations: list[ObservationId] = []
    unchanged: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    succeeded_operations = 0
    failed_operations = 0

    for source in cfg.sources:
        candidates: tuple[tuple[str, Path, str | None], ...]
        if source.kind in {SourceKind.HTTP, SourceKind.REST}:
            artifact_key, path = _http_candidate(cfg, source)
            candidates = ((artifact_key, path, None),) if path.is_file() else ()
        elif source.kind is SourceKind.RSYNC:
            candidates = tuple(
                (artifact_key, path, relative)
                for artifact_key, path, relative in _rsync_candidates(cfg, source)
            )
        else:
            skipped.append(source.id)
            continue

        if not candidates:
            skipped.append(source.id)
            continue

        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source.id,
            kind="adoption",
            subject=source.id,
            started_at=observed,
            parameters={"historical_provenance_known": False},
        )
        source_errors: list[str] = []
        adopted_count = 0
        unchanged_count = 0
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
                    observed_at=observed,
                )
            except (OSError, ValueError) as exc:
                detail = f"{source.id}:{path}: {type(exc).__name__}: {exc}"
                source_errors.append(detail)
                errors.append(detail)
                continue
            if observation_id is None:
                unchanged.append(artifact_key)
                unchanged_count += 1
            else:
                observations.append(observation_id)
                adopted_count += 1

        details: JsonObject = {
            "adoption": True,
            "historical_provenance_known": False,
            "candidate_count": len(candidates),
            "adopted_count": adopted_count,
            "unchanged_count": unchanged_count,
            "error_count": len(source_errors),
        }
        if source_errors:
            details["errors"] = list(source_errors)
            repository.finish_operation(operation_id, status="failed", finished_at=observed, details=details)
            failed_operations += 1
        else:
            repository.finish_operation(operation_id, status="succeeded", finished_at=observed, details=details)
            succeeded_operations += 1

    if failed_operations and succeeded_operations:
        run_status = "partial"
    elif failed_operations:
        run_status = "failed"
    else:
        run_status = "succeeded"
    repository.finish_run(run_id, status=run_status, finished_at=observed)
    return AdoptionResult(
        run_id=run_id,
        observations=tuple(observations),
        unchanged_artifacts=tuple(sorted(unchanged)),
        skipped_source_ids=tuple(sorted(set(skipped))),
        errors=tuple(errors),
    )


__all__ = ["AdoptionResult", "adopt_existing_store"]
