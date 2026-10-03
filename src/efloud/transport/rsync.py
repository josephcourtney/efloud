from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import re
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import] - rsync transport intentionally shells out to the local rsync executable.
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_TRANSIENT_RSYNC_RETURN_CODES = frozenset({10, 30, 35})
_RSYNC_DAEMON_PORT = 873
_PREFLIGHT_TIMEOUT_SECONDS = 3.0
_BYTES_PER_KIBIBYTE = 1024
_FILE_LIST_COUNT_RE = re.compile(r"(?P<count>\d[\d,]*)\s+files\.\.\.", re.IGNORECASE)
_TRANSFER_PROGRESS_RE = re.compile(
    r"(?P<bytes>\d[\d,]*)\s+\d+%\s+(?P<rate>\S+/s)\s+\S+\s+\(xfr#(?P<xfr>\d+),\s+to-chk=(?P<remaining>\d+)/(?P<total>\d+)\)",
    re.IGNORECASE,
)

OpStatus = Literal["success", "failed", "timed_out"]


@dataclass(frozen=True)
class OpResult:
    status: OpStatus
    detail: str = ""
    returncode: int | None = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    updated: list[str] | None = None
    phase: str | None = None
    attempt_count: int = 1
    max_attempts: int = 1
    attempt_errors: list[str] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


@dataclass(frozen=True)
class RsyncCommandConfig:
    rsync_bin: str = "rsync"
    archive: bool = True
    compress: bool = True
    copy_links: bool = True
    delay_updates: bool = True
    itemize_changes: bool = True
    prune_empty_dirs: bool = False
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class RsyncMirrorConfig:
    name: str
    remote: str
    local: Path
    port: int | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    timeout_seconds: float = 1200.0
    delete: bool = False
    verbose: bool = False
    progress: bool = False
    dry_run: bool = False
    retry_attempts: int = 3
    retry_wait_min_seconds: float = 5.0
    retry_wait_max_seconds: float = 30.0
    retry_backoff_multiplier: float = 4.0
    cmd: RsyncCommandConfig = RsyncCommandConfig()


def _uses_daemon_protocol(remote: str) -> bool:
    return "::" in remote


def _emit_stderr(text: str) -> None:
    with contextlib.suppress(OSError):
        sys.stderr.write(text)
        sys.stderr.flush()


def _emit_runtime_message(cfg: RsyncMirrorConfig, text: str) -> None:
    if cfg.progress or cfg.verbose:
        _emit_stderr(f"{text}\n")


def _remote_host_and_port(remote: str, *, configured_port: int | None = None) -> tuple[str | None, int]:
    if "::" in remote:
        return remote.split("::", 1)[0] or None, configured_port or _RSYNC_DAEMON_PORT
    if remote.startswith("rsync://"):
        host_part = remote.removeprefix("rsync://").split("/", 1)[0]
        if ":" in host_part:
            host, port_text = host_part.rsplit(":", 1)
            if port_text.isdigit():
                return host or None, int(port_text)
        return host_part or None, configured_port or _RSYNC_DAEMON_PORT
    return None, _RSYNC_DAEMON_PORT


def _preflight_connectivity(cfg: RsyncMirrorConfig, *, remote: str) -> None:
    host, port = _remote_host_and_port(remote, configured_port=cfg.port)
    if host is None:
        return
    timeout = min(float(cfg.timeout_seconds), _PREFLIGHT_TIMEOUT_SECONDS)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        logger.debug("rsync preflight failed for %s:%s: %s", host, port, exc)


def _base_rsync_args(cfg: RsyncCommandConfig) -> list[str]:
    flags = (
        (cfg.archive, "--archive"),
        (cfg.compress, "--compress"),
        (cfg.copy_links, "--copy-links"),
        (cfg.delay_updates, "--delay-updates"),
        (cfg.itemize_changes, "--itemize-changes"),
        (cfg.prune_empty_dirs, "--prune-empty-dirs"),
    )
    return [flag for enabled, flag in flags if enabled]


def _timeout_args(remote: str, *, timeout_seconds: int) -> list[str]:
    args = [f"--timeout={timeout_seconds}"]
    if _uses_daemon_protocol(remote):
        args.insert(0, f"--contimeout={timeout_seconds}")
    return args


def _port_args(remote: str, *, port: int | None) -> list[str]:
    if port is None or port <= 0:
        return []
    if _uses_daemon_protocol(remote) or remote.startswith("rsync://"):
        return [f"--port={port}"]
    return []


def _pattern_args(flag: str, patterns: tuple[str, ...]) -> list[str]:
    return [part for pattern in patterns for part in (flag, pattern)]


def _runtime_rsync_args(cfg: RsyncMirrorConfig) -> list[str]:
    args: list[str] = []
    if cfg.delete:
        args.append("--delete")
    if cfg.verbose:
        args.append("--verbose")
    if cfg.progress:
        args.extend(("--progress", "--info=progress2"))
    if cfg.dry_run:
        args.append("--dry-run")
    return args


def _build_rsync_cmd(cfg: RsyncMirrorConfig, *, remote: str, local: Path) -> list[str]:
    timeout = max(1, math.ceil(cfg.timeout_seconds))
    return [
        cfg.cmd.rsync_bin,
        *_base_rsync_args(cfg.cmd),
        *_timeout_args(remote, timeout_seconds=timeout),
        *_port_args(remote, port=cfg.port),
        *_runtime_rsync_args(cfg),
        *_pattern_args("--include", cfg.include),
        *_pattern_args("--exclude", cfg.exclude),
        *cfg.cmd.extra_args,
        remote,
        str(local),
    ]


def _parse_itemize_changes(stdout: str) -> list[str]:
    updated: list[str] = []
    for line in stdout.splitlines():
        if line and line[0] in {">", "<", "*", "c"}:
            parts = line.split(maxsplit=1)
            if len(parts) > 1:
                updated.append(parts[1])
    return updated


def _result_phase(result: OpResult) -> str:
    text = " ".join(part for part in (result.stdout, result.stderr, result.detail) if part).lower()
    if any(marker in text for marker in ("failed to connect", "timed out", "connection refused", "no route to host")):
        return "connecting"
    if any(marker in text for marker in ("to-check=", "xfr#", "speedup is", ">f", "<f", "created directory")):
        return "transferring files"
    if "receiving file list" in text:
        return "receiving file list"
    return "completed" if result.status == "success" else "checking remote state"


def _format_clock_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _parse_file_list_count(text: str) -> int | None:
    matches = list(_FILE_LIST_COUNT_RE.finditer(text))
    return int(matches[-1].group("count").replace(",", "")) if matches else None


def _format_transfer_bytes(byte_count: int) -> str:
    if byte_count < _BYTES_PER_KIBIBYTE:
        return f"{byte_count} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(byte_count)
    unit = "B"
    for unit in units:
        value /= _BYTES_PER_KIBIBYTE
        if value < _BYTES_PER_KIBIBYTE or unit == units[-1]:
            break
    return f"{value:.1f} {unit}"


def _parse_transfer_progress(text: str) -> dict[str, int | str] | None:
    matches = list(_TRANSFER_PROGRESS_RE.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    remaining = int(match.group("remaining"))
    total = int(match.group("total"))
    return {
        "transfer_total_files": total,
        "transfer_remaining_files": remaining,
        "transfer_transferred_files": int(match.group("xfr")),
        "transfer_handled_files": max(0, total - remaining),
        "transfer_bytes": int(match.group("bytes").replace(",", "")),
        "transfer_rate": match.group("rate"),
    }


def _should_quote_shell_arg(arg: str) -> bool:
    return not arg or "://" in arg or "::" in arg or "/" in arg


def _single_quote_shell_arg(arg: str) -> str:
    return "'" + arg.replace("'", "'\"'\"'") + "'"


def _render_shell_arg(arg: str) -> str:
    return _single_quote_shell_arg(arg) if _should_quote_shell_arg(arg) else arg


def _render_shell_command(cmd: list[str]) -> str:
    return " ".join(_render_shell_arg(part) for part in cmd)


def _join_remote_path(remote_base: str, relative_path: str) -> str:
    return f"{remote_base.rstrip('/')}/{relative_path.lstrip('/')}"


def _looks_like_file_path(rel: str) -> bool:
    return "." in rel.rsplit("/", 1)[-1] and not rel.endswith("/")


def _remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(str(item)), reverse=True):
        with contextlib.suppress(OSError):
            path.rmdir()


def _is_transient_rsync_failure(result: OpResult) -> bool:
    if result.status not in {"failed", "timed_out"}:
        return False
    text = " ".join(part for part in (result.detail, result.stderr) if part).lower()
    if any(marker in text for marker in ("host key verification failed", "unknown module", "permission denied", "no such file or directory")):
        return False
    return result.returncode in _TRANSIENT_RSYNC_RETURN_CODES or any(
        marker in text
        for marker in (
            "failed to connect",
            "timed out",
            "connection reset",
            "no route to host",
            "network is unreachable",
            "temporarily unavailable",
            "connection refused",
        )
    )


def _retry_wait_seconds(cfg: RsyncMirrorConfig, *, retry_index: int) -> float:
    wait = cfg.retry_wait_min_seconds * (cfg.retry_backoff_multiplier ** max(0, retry_index - 1))
    return min(cfg.retry_wait_max_seconds, wait)


def _run_rsync_process_once(cfg: RsyncMirrorConfig, *, cmd: list[str], remote: str, local: Path) -> OpResult:
    del remote, local
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - structured argv; no shell parsing.
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if cfg.progress or cfg.verbose:
        _emit_stderr(completed.stderr)
    status: OpStatus = "success" if completed.returncode == 0 else "failed"
    result = OpResult(
        status=status,
        detail="ok" if completed.returncode == 0 else "rsync failed",
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        updated=_parse_itemize_changes(completed.stdout) if completed.returncode == 0 else [],
    )
    return OpResult(
        status=result.status,
        detail=result.detail,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        updated=result.updated,
        phase=_result_phase(result),
    )


def _run_rsync_process(cfg: RsyncMirrorConfig, *, cmd: list[str], remote: str, local: Path) -> OpResult:
    max_attempts = max(1, cfg.retry_attempts)
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        _preflight_connectivity(cfg, remote=remote)
        result = _run_rsync_process_once(cfg, cmd=cmd, remote=remote, local=local)
        if result.status == "success" or attempt >= max_attempts or not _is_transient_rsync_failure(result):
            return OpResult(
                status=result.status,
                detail=result.detail if attempt == 1 else f"{result.detail} after {attempt} attempts",
                returncode=result.returncode,
                timed_out=result.timed_out,
                stdout=result.stdout,
                stderr=result.stderr,
                updated=result.updated,
                phase=result.phase,
                attempt_count=attempt,
                max_attempts=max_attempts,
                attempt_errors=errors,
            )
        errors.append(result.stderr.strip() or result.detail)
        wait = _retry_wait_seconds(cfg, retry_index=attempt)
        _emit_runtime_message(cfg, f"retry {attempt + 1}/{max_attempts} starts in {wait:.1f}s")
        time.sleep(wait)
    raise AssertionError("unreachable")


class RsyncMirror:
    """Stateless rsync executor; durable acquisition state belongs to the repository."""

    def __init__(self, cfg: RsyncMirrorConfig) -> None:
        self._cfg = cfg

    @property
    def name(self) -> str:
        return self._cfg.name

    @property
    def local_root(self) -> Path:
        return self._cfg.local

    async def update(self) -> OpResult:
        self._cfg.local.mkdir(parents=True, exist_ok=True)
        cmd = _build_rsync_cmd(self._cfg, remote=self._cfg.remote, local=self._cfg.local)
        return await asyncio.to_thread(
            _run_rsync_process,
            self._cfg,
            cmd=cmd,
            remote=self._cfg.remote,
            local=self._cfg.local,
        )

    async def update_paths(self, paths: list[str]) -> dict[str, OpResult]:
        self._cfg.local.mkdir(parents=True, exist_ok=True)
        if not paths:
            return {"": OpResult(status="failed", detail="No paths provided", stderr="No paths")}
        results: dict[str, OpResult] = {}
        for requested in paths:
            relative = requested.strip().lstrip("/")
            remote = _join_remote_path(self._cfg.remote, relative)
            target = self._cfg.local / relative
            local = target.parent if _looks_like_file_path(relative) else target
            local.mkdir(parents=True, exist_ok=True)
            cmd = _build_rsync_cmd(self._cfg, remote=remote, local=local)
            results[requested] = await asyncio.to_thread(
                _run_rsync_process,
                self._cfg,
                cmd=cmd,
                remote=remote,
                local=local,
            )
        return results

    async def prune_local_empty_dirs(self) -> None:
        await asyncio.to_thread(_remove_empty_dirs, self._cfg.local)
