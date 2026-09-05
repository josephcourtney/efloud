from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import re
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import] - rsync transport intentionally shells out to the local rsync executable.
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

import click
from smartratelimit import RateLimiter

from efloud.fs import atomic_write_text
from efloud.json_types import JsonArray, JsonObject, JsonValue, json_object_or_none

if TYPE_CHECKING:
    import io
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

logger = logging.getLogger(__name__)

_TRANSIENT_RSYNC_RETURN_CODES = frozenset({10, 30, 35})
_RETRY_COUNTDOWN_FINE_GRAIN_SECONDS = 10
_RSYNC_DAEMON_PORT = 873
_PREFLIGHT_TIMEOUT_SECONDS = 3.0
_CONNECT_HEARTBEAT_SECONDS = 1.0
_FILE_LIST_STALL_WARNING_SECONDS = 30.0
_FILE_LIST_PROGRESS_MESSAGE_SECONDS = 15.0
_FILE_LIST_PROGRESS_MIN_IDLE_SECONDS = 5.0
_BYTES_PER_KIBIBYTE = 1024
_FILE_LIST_COUNT_RE = re.compile(r"(?P<count>\d[\d,]*)\s+files\.\.\.", re.IGNORECASE)
_TRANSFER_PROGRESS_RE = re.compile(
    r"(?P<bytes>\d[\d,]*)\s+\d+%\s+(?P<rate>\S+/s)\s+\S+\s+\(xfr#(?P<xfr>\d+),\s+to-chk=(?P<remaining>\d+)/(?P<total>\d+)\)",
    re.IGNORECASE,
)
_MAX_PROGRESS_TAIL_CHARS = 2048

OpStatus = Literal["success", "skipped_fresh", "skipped_rate_limited", "failed", "timed_out"]


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
        # per your requirement: "success should only be communicated via returned result/manifest"
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
    # If multiple mirrors share the same local root (e.g. pdb_structures_all with per-path specs),
    # they must not share the same meta file or freshness tracking will be corrupted.
    meta_path: Path | None = None

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    timeout_seconds: float = 1200.0
    delete: bool = False
    verbose: bool = False
    progress: bool = False
    dry_run: bool = False

    update_interval_seconds: float | None = None

    rate_limit_storage: str = "memory"
    rate_limit_scope: str | None = None
    raise_on_rate_limit: bool = False
    retry_attempts: int = 3
    retry_wait_min_seconds: float = 5.0
    retry_wait_max_seconds: float = 30.0
    retry_backoff_multiplier: float = 4.0

    cmd: RsyncCommandConfig = RsyncCommandConfig()


@dataclass
class RsyncMirrorMeta:
    """
    Stored at: <local>/.mirror_meta.json.

    Schema:
      {
        "version": 1,
        "paths": {
          ".": {"updated_at_unix": 123, "updated": ["..."]},
          "sub/dir": {"updated_at_unix": 124, "updated": ["..."]}
        }
      }
    """

    version: int = 1
    paths: dict[str, JsonObject] | None = None

    def to_json(self) -> JsonObject:
        payload: JsonObject = {"version": self.version, "paths": {}}
        payload["paths"] = dict((self.paths or {}).items())
        return payload

    @staticmethod
    # Stored metadata is read from disk and can contain arbitrary payloads.
    def from_json(obj: Any) -> RsyncMirrorMeta:  # ruff: ignore[any-type]
        json_obj = json_object_or_none(obj)
        if json_obj is None:
            return RsyncMirrorMeta()
        version_value = json_obj.get("version")
        version = int(version_value) if isinstance(version_value, int | float) else 1
        paths_v = json_object_or_none(json_obj.get("paths"))
        paths: dict[str, JsonObject] = {}
        if paths_v is not None:
            for k, v in paths_v.items():
                path_payload = json_object_or_none(v)
                if path_payload is not None:
                    paths[k] = dict(path_payload.items())
        return RsyncMirrorMeta(version=version, paths=paths)


def read_rsync_mirror_meta(root: Path) -> RsyncMirrorMeta | None:
    meta_path = root / ".mirror_meta.json"
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return RsyncMirrorMeta.from_json(data)


def _read_json(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8"))


def _uses_daemon_protocol(remote: str) -> bool:
    """Only rsync daemons (module-style ``host::module``) allow ``--contimeout``."""
    return "::" in remote


def _emit_stderr(text: str) -> None:
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except OSError:
        pass


def _emit_runtime_message(cfg: RsyncMirrorConfig, text: str) -> None:
    if not (cfg.progress or cfg.verbose):
        return
    _emit_stderr(f"{text}\n")


@dataclass
class _ProgressBarState:
    current_phase: str = "connecting"
    last_position: int | None = None
    file_list_count: int | None = None
    transfer_total_files: int | None = None
    transfer_remaining_files: int | None = None
    transfer_transferred_files: int | None = None
    transfer_handled_files: int | None = None
    transfer_bytes: int | None = None
    transfer_rate: str | None = None
    idle_seconds: float | None = None


class _ProgressBarLike(Protocol):
    label: str

    def update(self, n_steps: int) -> None: ...


def _connect_progress_label(
    *,
    remote: str,
    attempt: int,
    max_attempts: int,
    cfg: RsyncMirrorConfig,
    progress_bar: _ProgressBarState,
    elapsed_seconds: float = 0.0,
) -> str:
    target = _remote_display_target(remote, configured_port=cfg.port)
    progress_suffix = _progress_detail_suffix(progress_bar)
    remaining_seconds = max(0.0, cfg.timeout_seconds - elapsed_seconds)
    idle_suffix = _idle_suffix(progress_bar)
    return (
        f"rsync attempt {attempt}/{max_attempts}: {progress_bar.current_phase} {target}{progress_suffix} "
        f"{_format_clock_duration(remaining_seconds)} remaining "
        f"({_format_clock_duration(cfg.timeout_seconds)} timeout{idle_suffix})"
    )


def _connect_progress_context(
    cfg: RsyncMirrorConfig,
    *,
    remote: str,
    attempt: int,
    max_attempts: int,
    progress_bar: _ProgressBarState,
) -> AbstractContextManager[_ProgressBarLike | None]:
    if not (cfg.progress or cfg.verbose):
        return contextlib.nullcontext(None)
    return click.progressbar(
        length=max(1, math.ceil(cfg.timeout_seconds)),
        label=_connect_progress_label(
            remote=remote,
            attempt=attempt,
            max_attempts=max_attempts,
            cfg=cfg,
            progress_bar=progress_bar,
        ),
        file=sys.stderr,
        show_eta=False,
        show_percent=False,
        show_pos=False,
        update_min_steps=1,
    )


def _progress_updater(progress_bar: _ProgressBarLike) -> Callable[[int, str], None]:
    def _update_progress(delta: int, label: str) -> None:
        progress_bar.label = label
        progress_bar.update(delta)

    return _update_progress


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
        return host_part or None, configured_port or _RSYNC_DAEMON_PORT
    return None, _RSYNC_DAEMON_PORT


def _remote_display_target(remote: str, *, configured_port: int | None = None) -> str:
    host, port = _remote_host_and_port(remote, configured_port=configured_port)
    if host is None:
        return remote
    return f"{host}:{port}"


def _preflight_connectivity(cfg: RsyncMirrorConfig, *, remote: str) -> None:
    host, port = _remote_host_and_port(remote, configured_port=cfg.port)
    if host is None:
        return
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        _emit_runtime_message(cfg, f"preflight: could not resolve {host}:{port}: {exc}")
        return
    addresses = sorted({str(info[4][0]) for info in infos if info[4]})
    if addresses:
        _emit_runtime_message(cfg, f"preflight: resolved {host}:{port} -> {', '.join(addresses)}")
    probe_timeout = min(float(cfg.timeout_seconds), _PREFLIGHT_TIMEOUT_SECONDS)
    try:
        with socket.create_connection((host, port), timeout=probe_timeout):
            _emit_runtime_message(
                cfg,
                f"preflight: tcp connect to {host}:{port} succeeded within {_format_seconds(probe_timeout)}",
            )
    except OSError as exc:
        _emit_runtime_message(
            cfg,
            f"preflight: tcp connect to {host}:{port} failed within {_format_seconds(probe_timeout)}: {exc}",
        )


def _consume_pipe_chunk(
    chunk: bytes,
    buffer: list[str],
    emitter: Callable[[str], None] | None,
    observer: Callable[[str], None] | None,
) -> None:
    text = chunk.decode("utf-8", "replace")
    buffer.append(text)
    if observer is not None:
        observer(text)
    if emitter is not None:
        emitter(text)


def _stream_pipe(
    stream: io.BufferedReader,
    buffer: list[str],
    emitter: Callable[[str], None] | None = None,
    observer: Callable[[str], None] | None = None,
) -> None:
    read_fn = getattr(stream, "read1", stream.read)
    try:
        while True:
            chunk = read_fn(4096)
            if not chunk:
                break
            _consume_pipe_chunk(chunk, buffer, emitter, observer)
    except OSError:
        pass
    finally:
        with contextlib.suppress(Exception):
            stream.close()


def _build_rsync_cmd(cfg: RsyncMirrorConfig, *, remote: str, local: Path) -> list[str]:
    t = max(1, math.ceil(cfg.timeout_seconds))
    c = cfg.cmd

    cmd: list[str] = [c.rsync_bin]
    cmd.extend(_base_rsync_args(c))
    cmd.extend(_timeout_args(remote, timeout_seconds=t))
    cmd.extend(_port_args(remote, port=cfg.port))
    cmd.extend(_runtime_rsync_args(cfg))
    cmd.extend(_pattern_args("--include", cfg.include))
    cmd.extend(_pattern_args("--exclude", cfg.exclude))
    cmd.extend(c.extra_args)
    cmd.extend([remote, str(local)])
    rendered_cmd = _render_shell_command(cmd)
    logger.debug(
        "Prepared rsync command remote=%s local=%s argv=%s shell=%s",
        remote,
        local,
        cmd,
        rendered_cmd,
    )
    return cmd


def _base_rsync_args(cmd_cfg: RsyncCommandConfig) -> list[str]:
    option_flags = (
        (cmd_cfg.archive, "--archive"),
        (cmd_cfg.compress, "--compress"),
        (cmd_cfg.copy_links, "--copy-links"),
        (cmd_cfg.delay_updates, "--delay-updates"),
        (cmd_cfg.itemize_changes, "--itemize-changes"),
        (cmd_cfg.prune_empty_dirs, "--prune-empty-dirs"),
    )
    return [flag for enabled, flag in option_flags if enabled]


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


def _pattern_args(flag: str, patterns: tuple[str, ...]) -> list[str]:
    args: list[str] = []
    for pattern in patterns:
        args.extend([flag, pattern])
    return args


def _render_shell_arg(arg: str) -> str:
    if _should_quote_shell_arg(arg):
        return _single_quote_shell_arg(arg)
    return arg


def _should_quote_shell_arg(arg: str) -> bool:
    if not arg:
        return True
    if "://" in arg or "::" in arg:
        return True
    return "/" in arg


def _render_shell_command(cmd: list[str]) -> str:
    return " ".join(_render_shell_arg(part) for part in cmd)


def _single_quote_shell_arg(arg: str) -> str:
    return "'" + arg.replace("'", "'\"'\"'") + "'"


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
    if any(
        marker in text
        for marker in (
            "failed to connect",
            "operation timed out",
            "connection timed out",
            "connection refused",
            "no route to host",
            "name or service not known",
        )
    ):
        return "connecting"
    if any(marker in text for marker in ("to-check=", "xfr#", "speedup is", ">f", "<f", "cd", "created directory")):
        return "transferring files"
    if "receiving file list" in text:
        return "receiving file list"
    if result.status == "success":
        return "completed"
    return "checking remote state"


def _format_seconds(seconds: float) -> str:
    return f"{max(0.0, seconds):.1f}s"


def _format_clock_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _parse_file_list_count(text: str) -> int | None:
    matches = list(_FILE_LIST_COUNT_RE.finditer(text))
    if not matches:
        return None
    count_text = matches[-1].group("count").replace(",", "")
    return int(count_text)


def _file_list_count_suffix(progress_bar: _ProgressBarState) -> str:
    count = getattr(progress_bar, "file_list_count", None)
    if progress_bar.current_phase != "receiving file list" or not isinstance(count, int):
        return ""
    return f" ({count:,} files)"


def _file_list_progress_suffix(
    *,
    elapsed_seconds: float,
    idle_seconds: float | None,
    file_list_count: int | None,
) -> str:
    parts = [f"elapsed {_format_clock_duration(elapsed_seconds)}"]
    if isinstance(file_list_count, int):
        parts.append(f"discovered {file_list_count:,} files")
    if isinstance(idle_seconds, float):
        parts.append(f"last output {_format_clock_duration(idle_seconds)} ago")
    return "; ".join(parts)


def _should_emit_file_list_progress(
    *,
    elapsed_seconds: float,
    idle_seconds: float | None,
    phase_state: dict[str, str | float | bool | int],
) -> bool:
    if phase_state.get("phase") != "receiving file list":
        return False
    last_emit = phase_state.get("file_list_progress_emitted_at")
    if isinstance(last_emit, float) and elapsed_seconds - last_emit < _FILE_LIST_PROGRESS_MESSAGE_SECONDS:
        return False
    return not isinstance(idle_seconds, float) or idle_seconds >= _FILE_LIST_PROGRESS_MIN_IDLE_SECONDS


def _idle_suffix(progress_bar: _ProgressBarState) -> str:
    idle_seconds = getattr(progress_bar, "idle_seconds", None)
    if not isinstance(idle_seconds, float | int):
        return ""
    return f"; last output {_format_clock_duration(float(idle_seconds))} ago"


def _format_transfer_bytes(byte_count: int) -> str:
    if byte_count < _BYTES_PER_KIBIBYTE:
        return f"{byte_count} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(byte_count)
    unit = "B"
    for unit in units:
        value /= float(_BYTES_PER_KIBIBYTE)
        if value < float(_BYTES_PER_KIBIBYTE) or unit == units[-1]:
            break
    return f"{value:.1f} {unit}"


def _progress_detail_suffix(progress_bar: _ProgressBarState) -> str:
    if progress_bar.current_phase == "receiving file list":
        return _file_list_count_suffix(progress_bar)
    total = progress_bar.transfer_total_files
    handled = progress_bar.transfer_handled_files
    transferred = progress_bar.transfer_transferred_files
    byte_count = progress_bar.transfer_bytes
    rate = progress_bar.transfer_rate
    parts: list[str] = []
    if isinstance(total, int) and isinstance(handled, int):
        percent = (handled / total * 100.0) if total > 0 else 0.0
        parts.append(f"{handled:,}/{total:,} files handled ({percent:.1f}%)")
    if isinstance(transferred, int):
        parts.append(f"{transferred:,} transferred")
    if isinstance(byte_count, int):
        parts.append(_format_transfer_bytes(byte_count))
    if isinstance(rate, str) and rate:
        parts.append(rate)
    if not parts:
        return ""
    return " [" + "; ".join(parts) + "]"


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


def _emit_retry_countdown(
    cfg: RsyncMirrorConfig,
    *,
    next_attempt: int,
    max_attempts: int,
    wait_seconds: float,
) -> None:
    remaining = max(1, math.ceil(wait_seconds))
    for seconds_left in range(remaining, 0, -1):
        if seconds_left > _RETRY_COUNTDOWN_FINE_GRAIN_SECONDS and seconds_left % 5 != 0:
            continue
        _emit_runtime_message(
            cfg,
            f"retry {next_attempt}/{max_attempts} starts in {seconds_left}s",
        )
        time.sleep(1.0)


def _observe_runtime_phase(text: str, phase_state: dict[str, str | float | bool | int]) -> None:
    phase_state["last_output_at"] = time.perf_counter()
    tail = f"{phase_state.get('progress_tail', '')}{text}"
    phase_state["progress_tail"] = tail[-_MAX_PROGRESS_TAIL_CHARS:]
    file_list_count = _parse_file_list_count(text)
    if file_list_count is not None:
        phase_state["file_list_count"] = file_list_count
    transfer_stats = _parse_transfer_progress(str(phase_state["progress_tail"]))
    if transfer_stats is not None:
        phase_state.update(transfer_stats)
    lowered = text.lower()
    if "receiving file list" in lowered:
        phase_state["phase"] = "receiving file list"
        return
    if any(marker in lowered for marker in ("to-check=", "xfr#", "speedup is", ">f", "<f", "cd", "created directory")):
        phase_state["phase"] = "transferring files"


def _maybe_emit_file_list_stall_warning(
    cfg: RsyncMirrorConfig,
    *,
    attempt: int,
    max_attempts: int,
    elapsed_seconds: float,
    phase_state: dict[str, str | float | bool | int],
) -> None:
    if phase_state.get("phase") != "receiving file list":
        return
    if bool(phase_state.get("file_list_warning_emitted")):
        return
    if elapsed_seconds < _FILE_LIST_STALL_WARNING_SECONDS:
        return
    idle_seconds = None
    last_output_at = phase_state.get("last_output_at")
    if isinstance(last_output_at, float):
        idle_seconds = max(0.0, time.perf_counter() - last_output_at)
    idle_suffix = f"; last rsync output {_format_clock_duration(idle_seconds)} ago" if idle_seconds is not None else ""
    file_list_count = phase_state.get("file_list_count")
    count_suffix = f"; discovered {file_list_count:,} files" if isinstance(file_list_count, int) else ""
    _emit_runtime_message(
        cfg,
        (
            f"rsync attempt {attempt}/{max_attempts}: still receiving file list after "
            f"{_format_clock_duration(elapsed_seconds)} "
            f"({_format_clock_duration(cfg.timeout_seconds)} timeout)"
            f"{count_suffix}"
            f"{idle_suffix}"
        ),
    )
    phase_state["file_list_warning_emitted"] = True


def _maybe_emit_file_list_progress(
    cfg: RsyncMirrorConfig,
    *,
    remote: str,
    attempt: int,
    max_attempts: int,
    elapsed_seconds: float,
    phase_state: dict[str, str | float | bool | int],
) -> None:
    if phase_state.get("phase") != "receiving file list":
        return

    last_output_at = phase_state.get("last_output_at")
    idle_seconds: float | None = None
    if isinstance(last_output_at, float):
        idle_seconds = max(0.0, time.perf_counter() - last_output_at)

    if not _should_emit_file_list_progress(
        elapsed_seconds=elapsed_seconds,
        idle_seconds=idle_seconds,
        phase_state=phase_state,
    ):
        return

    file_list_count = phase_state.get("file_list_count")
    count_value = file_list_count if isinstance(file_list_count, int) else None
    target = _remote_display_target(remote, configured_port=cfg.port)
    detail = _file_list_progress_suffix(
        elapsed_seconds=elapsed_seconds,
        idle_seconds=idle_seconds,
        file_list_count=count_value,
    )
    _emit_runtime_message(
        cfg,
        f"rsync attempt {attempt}/{max_attempts}: indexing {target}; {detail}",
    )
    phase_state["file_list_progress_emitted_at"] = elapsed_seconds


def _emit_connect_heartbeat(
    cfg: RsyncMirrorConfig,
    *,
    remote: str,
    attempt: int,
    max_attempts: int,
    started_at: float,
    phase_state: dict[str, str | float | bool | int],
    stop_event: threading.Event,
    progress_bar: _ProgressBarState,
    progress_update: Callable[[int, str], None] | None = None,
) -> None:
    while not stop_event.wait(_CONNECT_HEARTBEAT_SECONDS):
        elapsed = time.perf_counter() - started_at
        phase = str(phase_state.get("phase", "connecting"))
        progress_bar.current_phase = phase
        file_list_count = phase_state.get("file_list_count")
        if isinstance(file_list_count, int):
            progress_bar.file_list_count = file_list_count
        for key in (
            "transfer_total_files",
            "transfer_remaining_files",
            "transfer_transferred_files",
            "transfer_handled_files",
            "transfer_bytes",
        ):
            value = phase_state.get(key)
            if isinstance(value, int):
                setattr(progress_bar, key, value)
        transfer_rate = phase_state.get("transfer_rate")
        if isinstance(transfer_rate, str):
            progress_bar.transfer_rate = transfer_rate
        last_output_at = phase_state.get("last_output_at")
        idle_seconds: float | None = None
        if isinstance(last_output_at, float):
            idle_seconds = max(0.0, time.perf_counter() - last_output_at)
        progress_bar.idle_seconds = idle_seconds
        _maybe_emit_file_list_stall_warning(
            cfg,
            attempt=attempt,
            max_attempts=max_attempts,
            elapsed_seconds=elapsed,
            phase_state=phase_state,
        )
        _maybe_emit_file_list_progress(
            cfg,
            remote=remote,
            attempt=attempt,
            max_attempts=max_attempts,
            elapsed_seconds=elapsed,
            phase_state=phase_state,
        )
        bar_length = max(1, math.ceil(cfg.timeout_seconds))
        remaining_position = min(max(0, math.ceil(cfg.timeout_seconds - elapsed)), bar_length)
        if progress_update is not None:
            if progress_bar.last_position is None:
                progress_update(
                    bar_length,
                    _connect_progress_label(
                        remote=remote,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        cfg=cfg,
                        progress_bar=progress_bar,
                        elapsed_seconds=0.0,
                    ),
                )
                progress_bar.last_position = bar_length
            delta = remaining_position - int(progress_bar.last_position)
            progress_update(
                delta,
                _connect_progress_label(
                    remote=remote,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    cfg=cfg,
                    progress_bar=progress_bar,
                    elapsed_seconds=elapsed,
                ),
            )
            progress_bar.last_position = remaining_position
        elif progress_update is None:
            progress_suffix = _progress_detail_suffix(progress_bar)
            last_output_suffix = _idle_suffix(progress_bar)
            _emit_runtime_message(
                cfg,
                (
                    f"rsync attempt {attempt}/{max_attempts}: {phase} "
                    f"{_remote_display_target(remote, configured_port=cfg.port)}{progress_suffix} "
                    f"{_format_clock_duration(elapsed)} "
                    f"({_format_clock_duration(cfg.timeout_seconds)} timeout{last_output_suffix})"
                ),
            )


def _run_rsync_process_once(
    cfg: RsyncMirrorConfig,
    *,
    cmd: list[str],
    remote: str,
    local: Path,
    attempt: int,
    max_attempts: int,
) -> OpResult:
    proc = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] - argv is assembled from structured config fields, not raw shell text.
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    stdout_buffer: list[str] = []
    stderr_buffer: list[str] = []
    phase_state: dict[str, str | float | bool | int] = {"phase": "connecting"}
    stop_event = threading.Event()
    progress_bar_state = _ProgressBarState()

    stdout_thread = threading.Thread(
        target=_stream_pipe,
        args=(proc.stdout, stdout_buffer, None, lambda text: _observe_runtime_phase(text, phase_state)),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_stream_pipe,
        args=(
            proc.stderr,
            stderr_buffer,
            _emit_stderr if cfg.progress or cfg.verbose else None,
            lambda text: _observe_runtime_phase(text, phase_state),
        ),
        daemon=True,
    )
    started_at = time.perf_counter()
    progress_update: Callable[[int, str], None] | None = None
    with _connect_progress_context(
        cfg,
        remote=remote,
        attempt=attempt,
        max_attempts=max_attempts,
        progress_bar=progress_bar_state,
    ) as progress_bar:
        if progress_bar is not None:
            progress_update = _progress_updater(progress_bar)
        heartbeat_thread = threading.Thread(
            target=_emit_connect_heartbeat,
            args=(cfg,),
            kwargs={
                "remote": remote,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "started_at": started_at,
                "phase_state": phase_state,
                "stop_event": stop_event,
                "progress_bar": progress_bar_state,
                "progress_update": progress_update,
            },
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        heartbeat_thread.start()

        try:
            # Do not wrap rsync in a hard timeout that kills the process; rely on rsync's own
            # timeouts (e.g., --timeout/--contimeout) and user-initiated cancellation.
            proc.wait()
        finally:
            stop_event.set()
            stdout_thread.join()
            stderr_thread.join()
            heartbeat_thread.join()

    rc = proc.returncode if proc.returncode is not None else -1
    out = "".join(stdout_buffer)
    err = "".join(stderr_buffer)

    updated = _parse_itemize_changes(out) if rc == 0 and out else []
    logger.info(
        "Completed rsync mirror %s remote=%s local=%s returncode=%s",
        cfg.name,
        remote,
        local,
        rc,
    )
    return OpResult(
        status="success" if rc == 0 else "failed",
        returncode=rc,
        timed_out=False,
        stdout=out,
        stderr=err,
        updated=updated,
        phase=_result_phase(
            OpResult(
                status="success" if rc == 0 else "failed",
                returncode=rc,
                timed_out=False,
                stdout=out,
                stderr=err,
                updated=updated,
                detail="ok" if rc == 0 else "rsync failed",
            )
        ),
        detail="ok" if rc == 0 else "rsync failed",
    )


def _result_error_summary(result: OpResult) -> str:
    for value in (result.stderr, result.detail):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return result.status


def _is_transient_rsync_failure(result: OpResult) -> bool:
    if result.status not in {"failed", "timed_out"}:
        return False
    text = " ".join(part for part in (result.detail, result.stderr) if part).lower()
    permanent_markers = (
        "host key verification failed",
        "unknown module",
        "@error:",
        'change_dir "',
        "no such file or directory",
        "permission denied",
        "protocol version mismatch",
    )
    if any(marker in text for marker in permanent_markers):
        return False
    if result.returncode in _TRANSIENT_RSYNC_RETURN_CODES:
        return True
    transient_markers = (
        "failed to connect",
        "operation timed out",
        "connection timed out",
        "connection reset",
        "socket io",
        "no route to host",
        "network is unreachable",
        "temporary failure",
        "temporarily unavailable",
        "name or service not known",
        "connection refused",
    )
    return any(marker in text for marker in transient_markers)


def _retry_wait_seconds(cfg: RsyncMirrorConfig, *, retry_index: int) -> float:
    wait = cfg.retry_wait_min_seconds * (cfg.retry_backoff_multiplier ** max(0, retry_index - 1))
    return min(cfg.retry_wait_max_seconds, wait)


def _run_rsync_process(
    cfg: RsyncMirrorConfig,
    *,
    cmd: list[str],
    remote: str,
    local: Path,
) -> OpResult:
    max_attempts = max(1, int(cfg.retry_attempts))
    attempt_errors: list[str] = []

    for attempt in range(1, max_attempts + 1):
        _preflight_connectivity(cfg, remote=remote)
        _emit_runtime_message(
            cfg,
            (
                f"rsync attempt {attempt}/{max_attempts}: connecting to {remote} "
                f"(timeout {_format_seconds(cfg.timeout_seconds)})"
            ),
        )
        attempt_started = time.perf_counter()
        result = _run_rsync_process_once(
            cfg,
            cmd=cmd,
            remote=remote,
            local=local,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        elapsed_seconds = time.perf_counter() - attempt_started
        phase = result.phase or _result_phase(result)
        error_summary = _result_error_summary(result)
        if attempt == 1 and result.status == "success":
            _emit_runtime_message(
                cfg,
                f"rsync attempt {attempt}/{max_attempts}: completed in {_format_seconds(elapsed_seconds)}",
            )
            return OpResult(
                status=result.status,
                detail=result.detail,
                returncode=result.returncode,
                timed_out=result.timed_out,
                stdout=result.stdout,
                stderr=result.stderr,
                updated=result.updated,
                phase=phase,
                attempt_count=attempt,
                max_attempts=max_attempts,
                attempt_errors=list(attempt_errors),
            )
        if result.status == "success":
            _emit_runtime_message(
                cfg,
                (
                    f"rsync attempt {attempt}/{max_attempts}: completed in "
                    f"{_format_seconds(elapsed_seconds)} after retry"
                ),
            )
            return OpResult(
                status=result.status,
                detail=result.detail,
                returncode=result.returncode,
                timed_out=result.timed_out,
                stdout=result.stdout,
                stderr=result.stderr,
                updated=result.updated,
                phase=phase,
                attempt_count=attempt,
                max_attempts=max_attempts,
                attempt_errors=list(attempt_errors),
            )
        _emit_runtime_message(
            cfg,
            (
                f"rsync attempt {attempt}/{max_attempts}: failed while {phase} after "
                f"{_format_seconds(elapsed_seconds)}: {error_summary}"
            ),
        )
        attempt_errors.append(error_summary)
        if attempt >= max_attempts or not _is_transient_rsync_failure(result):
            detail = result.detail
            if attempt > 1:
                detail = f"{detail} after {attempt} attempts"
            return OpResult(
                status=result.status,
                detail=detail,
                returncode=result.returncode,
                timed_out=result.timed_out,
                stdout=result.stdout,
                stderr=result.stderr,
                updated=result.updated,
                phase=phase,
                attempt_count=attempt,
                max_attempts=max_attempts,
                attempt_errors=list(attempt_errors),
            )
        wait_seconds = _retry_wait_seconds(cfg, retry_index=attempt)
        logger.warning(
            "Retrying rsync mirror %s after transient failure (attempt %s/%s, wait %.1fs): %s",
            cfg.name,
            attempt + 1,
            max_attempts,
            wait_seconds,
            error_summary,
        )
        _emit_retry_countdown(
            cfg,
            next_attempt=attempt + 1,
            max_attempts=max_attempts,
            wait_seconds=wait_seconds,
        )

    return OpResult(
        status="failed",
        detail="rsync failed",
        phase="checking remote state",
        attempt_count=max_attempts,
        max_attempts=max_attempts,
    )


def _join_remote_path(remote_base: str, relative_path: str) -> str:
    return f"{remote_base.rstrip('/')}/{relative_path.lstrip('/')}"


def _looks_like_file_path(rel: str) -> bool:
    tail = rel.rsplit("/", 1)[-1]
    return "." in tail and not rel.endswith("/")


def _remove_empty_dirs(root: Path) -> None:
    # Remove empty dirs bottom-up
    if not root.exists():
        return
    for p in sorted((x for x in root.rglob("*") if x.is_dir()), key=lambda x: len(str(x)), reverse=True):
        with contextlib.suppress(OSError):
            p.rmdir()


def _updated_paths(value: Any) -> list[str]:  # ruff: ignore[any-type] - persisted metadata may contain arbitrary values
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


class RsyncMirror:
    def __init__(self, cfg: RsyncMirrorConfig) -> None:
        self._cfg = cfg
        self._meta_path = cfg.meta_path or (cfg.local / ".mirror_meta.json")

        self._rate_limiter = RateLimiter(
            storage=cfg.rate_limit_storage,
            raise_on_limit=cfg.raise_on_rate_limit,
        )
        self._rate_scope = cfg.rate_limit_scope or f"fs:{cfg.name}"

    @property
    def name(self) -> str:
        return self._cfg.name

    @property
    def local_root(self) -> Path:
        return self._cfg.local

    def _meta_load(self) -> RsyncMirrorMeta:
        if not self._meta_path.exists():
            return RsyncMirrorMeta(paths={})
        try:
            obj = _read_json(self._meta_path)
            return RsyncMirrorMeta.from_json(obj)
        except (OSError, json.JSONDecodeError):
            return RsyncMirrorMeta(paths={})

    def _meta_write(self, meta: RsyncMirrorMeta) -> None:
        atomic_write_text(self._meta_path, json.dumps(meta.to_json(), indent=2, sort_keys=True))

    def _meta_get_path(self, rel: str) -> JsonObject | None:
        meta = self._meta_load()
        paths = meta.paths or {}
        return paths.get(rel)

    def _meta_set_path(self, rel: str, updated: list[str]) -> None:
        meta = self._meta_load()
        if meta.paths is None:
            meta.paths = {}
        updated_values: JsonArray = list(updated)
        record: JsonObject = {"updated_at_unix": int(time.time()), "updated": updated_values}
        meta.paths[rel] = record
        self._meta_write(meta)

    def _is_fresh(self, rel: str) -> bool:
        if self._cfg.update_interval_seconds is None:
            return False
        rec = self._meta_get_path(rel)
        ts = rec.get("updated_at_unix") if isinstance(rec, dict) else None
        if not isinstance(ts, (int, float)):
            return False
        return (time.time() - float(ts)) < float(self._cfg.update_interval_seconds)

    def _acquire_rate_slot(self) -> bool:
        acquire = getattr(self._rate_limiter, "acquire", None)
        if not callable(acquire):
            return True
        try:
            return bool(acquire(scope=self._rate_scope))
        except TypeError:
            return bool(acquire(self._rate_scope))

    def _skip_result(self, rel: str, *, status: OpStatus, detail: str) -> OpResult:
        rec = self._meta_get_path(rel) or {}
        updated = rec.get("updated", [])
        return OpResult(
            status=status,
            detail=detail,
            returncode=0,
            stdout=detail,
            updated=_updated_paths(updated),
        )

    async def update(self, *, force: bool = False) -> OpResult:
        """
        Full mirror update.

        Freshness key: "."
        """
        self._cfg.local.mkdir(parents=True, exist_ok=True)

        if (not force) and self._is_fresh("."):
            logger.info("Mirror %s is fresh; skipping full update", self._cfg.name)
            return self._skip_result(".", status="skipped_fresh", detail="Skipped: fresh")

        if not self._acquire_rate_slot():
            logger.warning("Mirror %s rate limited; skipping update", self._cfg.name)
            return self._skip_result(".", status="skipped_rate_limited", detail="Skipped: rate-limited")

        logger.info(
            "Starting rsync mirror %s remote=%s local=%s timeout=%.1fs",
            self._cfg.name,
            self._cfg.remote,
            self._cfg.local,
            self._cfg.timeout_seconds,
        )
        cmd = _build_rsync_cmd(self._cfg, remote=self._cfg.remote, local=self._cfg.local)
        res = await asyncio.to_thread(
            _run_rsync_process,
            self._cfg,
            cmd=cmd,
            remote=self._cfg.remote,
            local=self._cfg.local,
        )
        if res.status == "success":
            self._meta_set_path(".", res.updated or [])
        return res

    async def update_paths(self, paths: list[str], *, force: bool = False) -> dict[str, OpResult]:
        """
        Update each subpath beneath remote/local roots.

        Returns per-path results for every requested path.
        """
        self._cfg.local.mkdir(parents=True, exist_ok=True)

        if not paths:
            return {"": OpResult(status="failed", detail="No paths provided", stderr="No paths")}

        out: dict[str, OpResult] = {}

        for rel in paths:
            rel_norm = rel.strip().lstrip("/")

            if (not force) and self._is_fresh(rel_norm):
                logger.info("Mirror path %s is fresh; skipping update", rel_norm)
                out[rel] = self._skip_result(rel_norm, status="skipped_fresh", detail="Skipped: fresh")
                continue

            if not self._acquire_rate_slot():
                logger.warning("Mirror path %s rate limited; skipping update", rel_norm)
                out[rel] = self._skip_result(
                    rel_norm,
                    status="skipped_rate_limited",
                    detail="Skipped: rate-limited",
                )
                continue

            remote = _join_remote_path(self._cfg.remote, rel_norm)
            local_target = self._cfg.local / rel_norm
            local = local_target.parent if _looks_like_file_path(rel_norm) else local_target
            local.mkdir(parents=True, exist_ok=True)

            logger.info(
                "Starting rsync mirror path=%s remote=%s local=%s timeout=%.1fs",
                rel_norm,
                remote,
                local,
                self._cfg.timeout_seconds,
            )
            cmd = _build_rsync_cmd(self._cfg, remote=remote, local=local)
            res = await asyncio.to_thread(
                _run_rsync_process,
                self._cfg,
                cmd=cmd,
                remote=remote,
                local=local,
            )

            if res.status == "success":
                self._meta_set_path(rel_norm, res.updated or [])

            out[rel] = res

        return out

    async def prune_local_empty_dirs(self) -> None:
        await asyncio.to_thread(_remove_empty_dirs, self._cfg.local)
