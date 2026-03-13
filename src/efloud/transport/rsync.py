from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import subprocess  # noqa: S404
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from smartratelimit import RateLimiter

from efloud.fs import atomic_write_text

if TYPE_CHECKING:
    import io
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

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
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class RsyncMirrorConfig:
    name: str
    remote: str
    local: Path
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

    rate_limit_storage: str = "sqlite:///mirror_rate_limits.sqlite"
    rate_limit_scope: str | None = None
    raise_on_rate_limit: bool = False

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
    paths: dict[str, dict[str, object]] | None = None

    def to_json(self) -> dict[str, object]:
        return {"version": self.version, "paths": self.paths or {}}

    @staticmethod
    def from_json(obj: object) -> RsyncMirrorMeta:
        if not isinstance(obj, dict):
            return RsyncMirrorMeta()
        version = int(obj.get("version", 1)) if isinstance(obj.get("version", 1), (int, float)) else 1
        paths_v = obj.get("paths")
        paths: dict[str, dict[str, object]] = {}
        if isinstance(paths_v, dict):
            for k, v in paths_v.items():
                if isinstance(k, str) and isinstance(v, dict):
                    paths[k] = dict(v)
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


def _read_json(path: Path) -> object:
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


def _stream_pipe(
    stream: io.BufferedReader,
    buffer: list[str],
    emitter: Callable[[str], None] | None = None,
) -> None:
    read_fn = getattr(stream, "read1", stream.read)
    try:
        while True:
            chunk = read_fn(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", "replace")
            buffer.append(text)
            if emitter is not None:
                emitter(text)
    except OSError:
        pass
    finally:
        with contextlib.suppress(Exception):
            stream.close()


def _build_rsync_cmd(cfg: RsyncMirrorConfig, *, remote: str, local: Path) -> list[str]:
    t = max(1, math.ceil(cfg.timeout_seconds))
    c = cfg.cmd

    cmd: list[str] = [c.rsync_bin]

    if c.archive:
        cmd.append("--archive")
    if c.compress:
        cmd.append("--compress")
    if c.copy_links:
        cmd.append("--copy-links")
    if c.delay_updates:
        cmd.append("--delay-updates")
    if c.itemize_changes:
        cmd.append("--itemize-changes")

    if _uses_daemon_protocol(remote):
        cmd.append(f"--contimeout={t}")
    cmd.append(f"--timeout={t}")

    if cfg.delete:
        cmd.append("--delete")
    if cfg.verbose:
        cmd.append("--verbose")
    if cfg.progress:
        cmd.extend(("--progress", "--info=progress2"))
    if cfg.dry_run:
        cmd.extend(("--dry-run",))

    for pattern in cfg.include:
        cmd.extend(["--include", pattern])
    for pattern in cfg.exclude:
        cmd.extend(["--exclude", pattern])

    cmd.extend(c.extra_args)
    cmd.extend([remote, str(local)])
    logger.debug(
        "Prepared rsync command remote=%s local=%s options=%s",
        remote,
        local,
        cmd,
    )
    logger.debug(" ".join(cmd))
    return cmd


def _parse_itemize_changes(stdout: str) -> list[str]:
    updated: list[str] = []
    for line in stdout.splitlines():
        if line and line[0] in {">", "<", "*", "c"}:
            parts = line.split(maxsplit=1)
            if len(parts) > 1:
                updated.append(parts[1])
    return updated


def _run_rsync_process(cfg: RsyncMirrorConfig, *, cmd: list[str]) -> OpResult:
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    stdout_buffer: list[str] = []
    stderr_buffer: list[str] = []
    stderr_emitter = _emit_stderr if cfg.progress or cfg.verbose else None

    stdout_thread = threading.Thread(
        target=_stream_pipe,
        args=(proc.stdout, stdout_buffer, None),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_stream_pipe,
        args=(proc.stderr, stderr_buffer, stderr_emitter),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    try:
        # Do not wrap rsync in a hard timeout that kills the process; rely on rsync's own
        # timeouts (e.g., --timeout/--contimeout) and user-initiated cancellation.
        proc.wait()
    finally:
        stdout_thread.join()
        stderr_thread.join()

    rc = proc.returncode if proc.returncode is not None else -1
    out = "".join(stdout_buffer)
    err = "".join(stderr_buffer)

    updated = _parse_itemize_changes(out) if rc == 0 and out else []
    logger.info(
        "Completed rsync mirror %s remote=%s local=%s returncode=%s",
        cfg.name,
        cfg.remote,
        cfg.local,
        rc,
    )
    return OpResult(
        status="success" if rc == 0 else "failed",
        returncode=rc,
        timed_out=False,
        stdout=out,
        stderr=err,
        updated=updated,
        detail="ok" if rc == 0 else "rsync failed",
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

    def _meta_get_path(self, rel: str) -> dict[str, object] | None:
        meta = self._meta_load()
        paths = meta.paths or {}
        v = paths.get(rel)
        return v if isinstance(v, dict) else None

    def _meta_set_path(self, rel: str, updated: list[str]) -> None:
        meta = self._meta_load()
        if meta.paths is None:
            meta.paths = {}
        meta.paths[rel] = {"updated_at_unix": int(time.time()), "updated": updated}
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
            updated=updated if isinstance(updated, list) else [],
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
        res = await asyncio.to_thread(_run_rsync_process, self._cfg, cmd=cmd)
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
            res = await asyncio.to_thread(_run_rsync_process, self._cfg, cmd=cmd)

            if res.status == "success":
                self._meta_set_path(rel_norm, res.updated or [])

            out[rel] = res

        return out

    async def prune_local_empty_dirs(self) -> None:
        await asyncio.to_thread(_remove_empty_dirs, self._cfg.local)
