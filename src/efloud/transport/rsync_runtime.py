from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess  # ruff: ignore[suspicious-subprocess-import] - rsync discovery intentionally invokes the local rsync executable.
import sys
from typing import TYPE_CHECKING

from efloud.json_types import JsonMapping, JsonObject, json_mapping_or_none
from efloud.transport.rsync import OpResult, RsyncCommandConfig

if TYPE_CHECKING:
    from efloud.registry import SourceDefinition
    from efloud.transport.rsync import RsyncMirror

logger = logging.getLogger(__name__)
_MMCIF_BUCKET_PARTS = 2
_MMCIF_BUCKET_WIDTH = 2
_MMCIF_PREFILTER_MIN_PATHS = 2
_RSYNC_FILE_OR_ATTR_ERROR_CODE = 23


def rsync_results_ok(results: JsonMapping) -> bool:
    """Whether every structured rsync result completed without transport failure."""
    for raw in results.values():
        result = json_mapping_or_none(raw)
        if result is not None and result.get("status") in {"failed", "timed_out"}:
            return False
    return True


def rsync_failure_detail(results: JsonMapping) -> str | None:
    """First useful failure description from structured rsync results."""
    for name, raw in results.items():
        result = json_mapping_or_none(raw)
        if result is None:
            continue
        status = result.get("status")
        if status not in {"failed", "timed_out"}:
            continue
        detail = result.get("detail")
        if isinstance(detail, str) and detail:
            return f"{name}: {detail}"
        return f"{name}: {status}"
    return None


def _looks_like_mmcif_bucket_path(relative_path: str) -> bool:
    parts = relative_path.strip().strip("/").split("/")
    if len(parts) != _MMCIF_BUCKET_PARTS or parts[0] != "mmCIF":
        return False
    bucket = parts[1]
    return len(bucket) == _MMCIF_BUCKET_WIDTH and bucket.isalnum()


def _is_missing_remote_mmcif_bucket(
    *,
    source: SourceDefinition,
    relative_path: str,
    result: OpResult,
) -> bool:
    if source.id != "pdb_mmcif" or result.status not in {"failed", "timed_out"}:
        return False
    if not _looks_like_mmcif_bucket_path(relative_path):
        return False
    if result.returncode != _RSYNC_FILE_OR_ATTR_ERROR_CODE:
        return False
    text = " ".join(part for part in (result.stderr, result.stdout, result.detail) if part).lower()
    return 'change_dir "' in text and "no such file or directory" in text


def _normalize_path_result(source: SourceDefinition, relative_path: str, result: OpResult) -> OpResult:
    if not _is_missing_remote_mmcif_bucket(source=source, relative_path=relative_path, result=result):
        return result
    return OpResult(
        status="success",
        detail="Skipped: remote shard not present",
        returncode=0,
        timed_out=False,
        stdout=result.stdout,
        stderr=result.stderr,
        updated=result.updated,
        phase=result.phase or "receiving file list",
        attempt_count=result.attempt_count,
        max_attempts=result.max_attempts,
        attempt_errors=result.attempt_errors,
    )


def _parse_list_only_directories(stdout: str) -> set[str]:
    names: set[str] = set()
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("total size is ") or stripped[0] != "d":
            continue
        parts = stripped.split()
        if not parts:
            continue
        name = parts[-1].strip().strip("/")
        if name and name not in {".", ".."}:
            names.add(name)
    return names


def _discover_mmcif_buckets(source: SourceDefinition) -> set[str] | None:
    remote = f"{source.url.rstrip('/')}/mmCIF/"
    timeout_seconds = 1200
    command = [
        "rsync",
        "--list-only",
        f"--timeout={timeout_seconds}",
        f"--contimeout={timeout_seconds}",
    ]
    if source.port is not None and source.port > 0:
        command.append(f"--port={source.port}")
    command.append(remote)
    try:
        process = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - argv is built from typed source settings without shell interpolation.
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        logger.debug(
            "Could not list remote pdb_mmcif buckets for %s (exit %s): %s",
            remote,
            process.returncode,
            (process.stderr or process.stdout or "").strip(),
        )
        return None
    discovered = _parse_list_only_directories(process.stdout)
    return {
        f"mmCIF/{name.lower()}/"
        for name in discovered
        if len(name) == _MMCIF_BUCKET_WIDTH and name.isalnum()
    }


def _emit_progress(text: str, *, enabled: bool, inline: bool = False, final: bool = False) -> None:
    if not enabled:
        return
    with contextlib.suppress(OSError):
        prefix = "\r" if inline else ""
        suffix = "\n" if final or not inline else ""
        sys.stderr.write(f"{prefix}{text}{suffix}")
        sys.stderr.flush()


def _should_prefilter(source: SourceDefinition, mirror_paths: tuple[str, ...] | None) -> bool:
    return (
        source.id == "pdb_mmcif"
        and mirror_paths is not None
        and len(mirror_paths) >= _MMCIF_PREFILTER_MIN_PATHS
        and all(_looks_like_mmcif_bucket_path(path) for path in mirror_paths)
    )


async def prepare_rsync_paths(
    *,
    source: SourceDefinition,
    mirror_paths: tuple[str, ...] | None,
    runtime_progress: bool,
) -> tuple[tuple[str, ...] | None, JsonObject]:
    """Filter known-missing PDB shards without turning absence into a transport failure."""
    if not mirror_paths or not _should_prefilter(source, mirror_paths):
        return mirror_paths, {}
    existing = await asyncio.to_thread(_discover_mmcif_buckets, source)
    if existing is None:
        return mirror_paths, {}
    filtered = tuple(path for path in mirror_paths if path in existing)
    skipped = tuple(path for path in mirror_paths if path not in existing)
    if skipped:
        _emit_progress(
            f"pdb_mmcif: skipping {len(skipped)} missing remote buckets discovered by rsync --list-only",
            enabled=runtime_progress,
        )
    synthetic: JsonObject = {}
    for relative_path in skipped:
        synthetic[relative_path] = {
            "status": "success",
            "detail": "Skipped: remote shard not present",
            "phase": "receiving file list",
            "returncode": 0,
            "timed_out": False,
            "attempt_count": 1,
            "max_attempts": 1,
            "attempt_errors": [],
            "stdout": "",
            "stderr": "",
            "updated": [],
        }
    return filtered, synthetic


def rsync_command_for_source(source: SourceDefinition) -> RsyncCommandConfig:
    """Protocol command settings for one declarative rsync source."""
    if source.id == "pdb_mmcif":
        return RsyncCommandConfig(
            rsync_bin="rsync",
            archive=True,
            compress=False,
            copy_links=False,
            delay_updates=True,
            itemize_changes=True,
            prune_empty_dirs=bool(source.include or source.exclude),
        )
    return RsyncCommandConfig(
        rsync_bin="rsync",
        archive=True,
        compress=True,
        copy_links=True,
        delay_updates=True,
        itemize_changes=True,
        prune_empty_dirs=bool(source.include or source.exclude),
    )


def _op_payload(result: OpResult) -> JsonObject:
    return {
        "status": result.status,
        "detail": result.detail,
        "phase": result.phase,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "attempt_count": result.attempt_count,
        "max_attempts": result.max_attempts,
        "attempt_errors": list(result.attempt_errors or []),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "updated": list(result.updated or []),
    }


async def _run_compact_mmcif(
    *,
    source: SourceDefinition,
    mirror: RsyncMirror,
    mirror_paths: tuple[str, ...],
    force: bool,
    synthetic_count: int,
    runtime_progress: bool,
) -> dict[str, OpResult]:
    total = len(mirror_paths) + synthetic_count
    done = synthetic_count
    ok = synthetic_count
    failed = 0
    current = "-"
    results: dict[str, OpResult] = {}
    _emit_progress(
        f"pdb_mmcif shards: {done}/{total} done; ok {ok}; failed {failed}; current {current}",
        enabled=runtime_progress,
        inline=True,
    )
    for relative_path in mirror_paths:
        shard_results = await mirror.update_paths([relative_path], force=force)
        raw = shard_results.get(relative_path, OpResult(status="failed", detail="missing shard result"))
        result = _normalize_path_result(source, relative_path, raw)
        results[relative_path] = result
        done += 1
        current = relative_path
        if result.status in {"failed", "timed_out"}:
            failed += 1
        else:
            ok += 1
        _emit_progress(
            f"pdb_mmcif shards: {done}/{total} done; ok {ok}; failed {failed}; current {current}",
            enabled=runtime_progress,
            inline=True,
        )
    _emit_progress(
        f"pdb_mmcif shards: {done}/{total} done; ok {ok}; failed {failed}; current {current}",
        enabled=runtime_progress,
        inline=True,
        final=True,
    )
    return results


async def run_rsync_operation(
    *,
    source: SourceDefinition,
    mirror: RsyncMirror,
    mirror_paths: tuple[str, ...] | None,
    force: bool,
    synthetic_results: JsonMapping,
    runtime_progress: bool,
) -> JsonObject:
    """Execute one rsync source operation and return structured transport evidence."""
    if mirror_paths:
        compact = source.id == "pdb_mmcif" and runtime_progress and not logger.isEnabledFor(logging.DEBUG)
        per_path = (
            await _run_compact_mmcif(
                source=source,
                mirror=mirror,
                mirror_paths=mirror_paths,
                force=force,
                synthetic_count=len(synthetic_results),
                runtime_progress=runtime_progress,
            )
            if compact
            else await mirror.update_paths(list(mirror_paths), force=force)
        )
        results: JsonObject = {}
        for relative_path, raw_result in per_path.items():
            results[relative_path] = _op_payload(_normalize_path_result(source, relative_path, raw_result))
        for relative_path, payload in synthetic_results.items():
            results[relative_path] = payload
        return results
    return {"update": _op_payload(await mirror.update(force=force))}


__all__ = [
    "prepare_rsync_paths",
    "rsync_command_for_source",
    "rsync_failure_detail",
    "rsync_results_ok",
    "run_rsync_operation",
]