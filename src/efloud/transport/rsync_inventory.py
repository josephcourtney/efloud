from __future__ import annotations

import math
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] - structured rsync argv is executed without a shell.
from dataclasses import dataclass
from typing import Literal

from efloud.transport.rsync import RsyncMirrorConfig

InventoryKind = Literal["file", "directory", "symlink"]
_MODE_RE = re.compile(r"^[bcdlps-][rwxstST-]{9}$")


@dataclass(frozen=True, slots=True)
class RsyncInventoryEntry:
    relative_path: str
    kind: InventoryKind
    byte_size: int | None = None
    modified: str | None = None
    target: str | None = None


@dataclass(frozen=True, slots=True)
class RsyncInventory:
    entries: tuple[RsyncInventoryEntry, ...]
    scope: tuple[str, ...] = ()
    complete: bool = True
    error: str | None = None


def _normalize_relative_path(value: str) -> str | None:
    normalized = value.strip().replace("\\", "/").strip("/")
    if not normalized or normalized == ".":
        return None
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _parse_list_line(line: str, *, prefix: str = "") -> RsyncInventoryEntry | None:
    parts = line.strip().split(maxsplit=4)
    if len(parts) != 5 or _MODE_RE.fullmatch(parts[0]) is None:
        return None
    mode, size_text, date_text, time_text, raw_path = parts
    target: str | None = None
    if mode.startswith("l") and " -> " in raw_path:
        raw_path, target = raw_path.split(" -> ", 1)
    relative_path = _normalize_relative_path(raw_path)
    if relative_path is None:
        return None
    normalized_prefix = _normalize_relative_path(prefix)
    if normalized_prefix is not None:
        relative_path = f"{normalized_prefix}/{relative_path}"

    kind: InventoryKind
    if mode.startswith("d"):
        kind = "directory"
    elif mode.startswith("l"):
        kind = "symlink"
    elif mode.startswith("-"):
        kind = "file"
    else:
        return None

    byte_size: int | None = None
    if kind == "file":
        normalized_size = size_text.replace(",", "")
        if not normalized_size.isdigit():
            return None
        byte_size = int(normalized_size)
    return RsyncInventoryEntry(
        relative_path=relative_path,
        kind=kind,
        byte_size=byte_size,
        modified=f"{date_text} {time_text}",
        target=target,
    )


def parse_rsync_list_only(text: str, *, prefix: str = "") -> tuple[RsyncInventoryEntry, ...]:
    entries = [entry for line in text.splitlines() if (entry := _parse_list_line(line, prefix=prefix))]
    by_path = {entry.relative_path: entry for entry in entries}
    return tuple(by_path[path] for path in sorted(by_path))


def _uses_daemon_protocol(remote: str) -> bool:
    return "::" in remote


def _port_args(remote: str, port: int | None) -> list[str]:
    if port is None or port <= 0:
        return []
    if _uses_daemon_protocol(remote) or remote.startswith("rsync://"):
        return [f"--port={port}"]
    return []


def _inventory_command(cfg: RsyncMirrorConfig, remote: str) -> list[str]:
    timeout = max(1, math.ceil(cfg.timeout_seconds))
    command = [cfg.cmd.rsync_bin, "--list-only", "--recursive", "--no-motd"]
    if _uses_daemon_protocol(remote):
        command.append(f"--contimeout={timeout}")
    command.append(f"--timeout={timeout}")
    command.extend(_port_args(remote, cfg.port))
    for pattern in cfg.include:
        command.extend(("--include", pattern))
    for pattern in cfg.exclude:
        command.extend(("--exclude", pattern))
    command.extend(cfg.cmd.extra_args)
    command.append(remote)
    return command


def _scoped_remote(remote: str, scope: str) -> str:
    normalized = scope.strip().strip("/")
    if not normalized:
        return remote
    return f"{remote.rstrip('/')}/{normalized}/"


def enumerate_rsync(
    cfg: RsyncMirrorConfig,
    *,
    scope: tuple[str, ...] = (),
) -> RsyncInventory:
    scopes = tuple(sorted({item.strip().strip("/") + "/" for item in scope if item.strip().strip("/")}))
    requests = scopes or ("",)
    entries: dict[str, RsyncInventoryEntry] = {}
    errors: list[str] = []
    for requested_scope in requests:
        remote = _scoped_remote(cfg.remote, requested_scope)
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - argv is structured and shell=False is the default.
            _inventory_command(cfg, remote),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"rsync exited {completed.returncode}"
            errors.append(f"{requested_scope or '.'}: {detail}")
            continue
        prefix = requested_scope.rstrip("/")
        for entry in parse_rsync_list_only(completed.stdout, prefix=prefix):
            entries[entry.relative_path] = entry

    if errors:
        return RsyncInventory(
            entries=tuple(entries[path] for path in sorted(entries)),
            scope=scopes,
            complete=False,
            error="; ".join(errors),
        )
    return RsyncInventory(
        entries=tuple(entries[path] for path in sorted(entries)),
        scope=scopes,
        complete=True,
    )


__all__ = [
    "RsyncInventory",
    "RsyncInventoryEntry",
    "enumerate_rsync",
    "parse_rsync_list_only",
]
