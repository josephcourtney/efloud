from __future__ import annotations

import hashlib
import operator
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from efloud.fs import atomic_write_text, safe_json_dump
from efloud.registry import SourceKind
from efloud.repository_models import ArtifactObservation, SourceId
from efloud.state import HASH_ALGORITHM, MirrorSourceState, MirrorState, MirrorStateNode

if TYPE_CHECKING:
    from efloud.models import EngineConfig
    from efloud.repository import Repository


@dataclass(slots=True)
class _Directory:
    files: dict[str, str] = field(default_factory=dict)
    directories: dict[str, _Directory] = field(default_factory=dict)


def _content_digest(content_id: str) -> str:
    algorithm, separator, digest = content_id.partition(":")
    if separator and algorithm == HASH_ALGORITHM and digest:
        return digest
    return content_id


def _insert_file(root: _Directory, relative_path: str, digest: str) -> None:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        return
    current = root
    for part in path.parts[:-1]:
        current = current.directories.setdefault(part, _Directory())
    current.files[path.parts[-1]] = digest


def _directory_hash(children: list[tuple[str, MirrorStateNode]]) -> str:
    hasher = hashlib.new(HASH_ALGORITHM)
    for name, node in children:
        hasher.update(f"{name}:{node.path_type}:{node.hash}".encode())
    return hasher.hexdigest()


def _finalize(directory: _Directory) -> MirrorStateNode:
    children: list[tuple[str, MirrorStateNode]] = []
    for name, child in directory.directories.items():
        children.append((name, _finalize(child)))
    for name, digest in directory.files.items():
        children.append((
            name,
            MirrorStateNode(
                path_type="file",
                hash=digest,
                file_count=1,
                dir_count=0,
            ),
        ))
    children.sort(key=operator.itemgetter(0))
    file_count = sum(node.file_count for _, node in children)
    dir_count = 1 + sum(node.dir_count for _, node in children)
    return MirrorStateNode(
        path_type="dir",
        hash=_directory_hash(children),
        file_count=file_count,
        dir_count=dir_count,
        children=dict(children) if children else None,
    )


def _source_has_complete_baseline(repository: Repository, source_id: SourceId) -> bool:
    for snapshot in repository.metadata.source_snapshots_for(source_id, limit=1000):
        if snapshot.complete and snapshot.evidence.get("reconciliation_complete") is True:
            return True
    return False


def _current_source_files(repository: Repository, source_id: SourceId) -> tuple[ArtifactObservation, ...]:
    observations: list[ArtifactObservation] = []
    for artifact_key in repository.artifact_keys():
        state = repository.latest_state(artifact_key)
        if not isinstance(state, ArtifactObservation):
            continue
        if state.source_id != source_id or state.source_path is None:
            continue
        observations.append(state)
    observations.sort(key=lambda item: item.source_path or "")
    return tuple(observations)


def _source_directory(repository: Repository, source_id: SourceId) -> _Directory:
    directory = _Directory()
    for observation in _current_source_files(repository, source_id):
        if observation.source_path is None:
            continue
        _insert_file(directory, observation.source_path, _content_digest(str(observation.content_id)))
    return directory


def _mount_directory(root: _Directory, prefix: str, source: _Directory) -> None:
    normalized = PurePosixPath(prefix.strip("/")) if prefix.strip("/") else PurePosixPath()
    current = root
    for part in normalized.parts:
        current = current.directories.setdefault(part, _Directory())

    def merge(destination: _Directory, incoming: _Directory) -> None:
        destination.files.update(incoming.files)
        for name, child in incoming.directories.items():
            merge(destination.directories.setdefault(name, _Directory()), child)

    merge(current, source)


def repository_mirror_state(
    repository: Repository,
    *,
    cfg: EngineConfig,
    manifest_path: Path | None = None,
    generated_at: float | None = None,
) -> MirrorState | None:
    """Build compatibility mirror state without rescanning mirror files.

    Returns ``None`` when there are no configured rsync sources or when any
    configured rsync source lacks a complete repository reconciliation baseline.
    """
    rsync_sources = [source for source in cfg.sources if source.kind is SourceKind.RSYNC]
    if not rsync_sources:
        return None

    global_directory = _Directory()
    source_states: list[MirrorSourceState] = []

    for source in rsync_sources:
        source_id = SourceId(source.id)
        if not _source_has_complete_baseline(repository, source_id):
            return None
        source_directory = _source_directory(repository, source_id)
        source_node = _finalize(source_directory)
        local_subdir = source.local_subpath or ""
        _mount_directory(global_directory, local_subdir, source_directory)
        source_states.append(
            MirrorSourceState(
                source_id=source.id,
                local_subdir=local_subdir,
                hash=source_node.hash,
            )
        )

    root = Path(cfg.root)
    return MirrorState(
        version=1,
        generated_at_unix=time.time() if generated_at is None else generated_at,
        cache_root=str(root.resolve()),
        mirrors_root=str((root / cfg.mirrors_dir).resolve()),
        hash_algo=HASH_ALGORITHM,
        manifest_path=str(manifest_path) if manifest_path is not None else None,
        tree=_finalize(global_directory),
        sources=tuple(source_states),
    )


def write_repository_mirror_state(
    repository: Repository,
    *,
    cfg: EngineConfig,
    manifest_path: Path | None = None,
    generated_at: float | None = None,
) -> tuple[MirrorState | None, Path | None]:
    state = repository_mirror_state(
        repository,
        cfg=cfg,
        manifest_path=manifest_path,
        generated_at=generated_at,
    )
    if state is None:
        return None, None
    path = Path(cfg.root) / cfg.state_filename
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, safe_json_dump(state.to_dict()))
    return state, path.resolve()


__all__ = ["repository_mirror_state", "write_repository_mirror_state"]
