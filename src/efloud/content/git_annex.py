from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from efloud.content.protocol import AnnexKey
from efloud.git_commands import GitCommandError, GitError, GitUnavailableError, run_git

if TYPE_CHECKING:
    import subprocess
    from typing import BinaryIO

_DEFAULT_BACKEND = "SHA256"
_GIT_IDENTITY_NAME = "Efloud"
_GIT_IDENTITY_EMAIL = "efloud@localhost.invalid"


class GitAnnexError(RuntimeError):
    """Base failure for the internal Git/git-annex command boundary."""


class GitAnnexUnavailableError(GitAnnexError):
    """Git or git-annex is not available to the current process."""


class GitAnnexCommandError(GitAnnexError):
    """A Git or git-annex subprocess returned a non-zero exit status."""

    def __init__(self, command: tuple[str, ...], returncode: int, stderr: str) -> None:
        """Capture stable command diagnostics without exposing shell execution."""
        detail = stderr.strip() or "command failed without stderr"
        super().__init__(f"Command failed ({returncode}): {' '.join(command)}: {detail}")
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


def _run(
    root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return run_git(root, *args, check=check)
    except GitUnavailableError as error:
        raise GitAnnexUnavailableError(str(error)) from error
    except GitCommandError as error:
        if args[:2] == ("annex", "version") or "not a git command" in error.stderr:
            msg = "git-annex is not available through git"
            raise GitAnnexUnavailableError(msg) from error
        raise GitAnnexCommandError(error.command, error.returncode, error.stderr) from error
    except GitError as error:
        raise GitAnnexError(str(error)) from error


def _require_regular_file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        msg = f"Content input must be a regular file: {resolved}"
        raise ValueError(msg)
    return resolved


def _require_remote_name(remote: str) -> str:
    if not remote or "\n" in remote or "\r" in remote:
        msg = "git-annex remote names must be non-empty single-line strings"
        raise ValueError(msg)
    return remote


@dataclass(frozen=True, slots=True)
class GitAnnexContentStore:
    """Content custody backed directly by one Git/git-annex repository."""

    root: Path
    backend: str = _DEFAULT_BACKEND

    def __post_init__(self) -> None:
        """Normalize the repository root and reject an empty backend."""
        object.__setattr__(self, "root", self.root.resolve())
        if not self.backend:
            msg = "git-annex backend must not be empty"
            raise ValueError(msg)

    @classmethod
    def initialize(
        cls,
        root: Path,
        *,
        description: str = "efloud",
        backend: str = _DEFAULT_BACKEND,
    ) -> GitAnnexContentStore:
        """Create Git/git-annex state with a cryptographic content-only backend."""
        resolved = root.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        _run(resolved, "init", "--quiet")
        _run(resolved, "config", "user.name", _GIT_IDENTITY_NAME)
        _run(resolved, "config", "user.email", _GIT_IDENTITY_EMAIL)
        _run(resolved, "config", "annex.backend", backend)
        _run(resolved, "config", "annex.securehashesonly", "true")
        _run(resolved, "annex", "init", description)
        return cls(resolved, backend=backend)

    def check_available(self) -> None:
        """Fail explicitly if the repository cannot execute git-annex."""
        _run(self.root, "annex", "version")

    def calculate_key(self, path: Path) -> AnnexKey:
        """Calculate the configured annex key without ingesting bytes."""
        source = _require_regular_file(path)
        completed = _run(
            self.root,
            "annex",
            "calckey",
            f"--backend={self.backend}",
            source.as_posix(),
        )
        value = completed.stdout.strip()
        if not value:
            msg = "git-annex calckey returned an empty key"
            raise GitAnnexError(msg)
        return AnnexKey(value)

    def ingest_path(self, path: Path) -> AnnexKey:
        """Copy caller-owned bytes into git-annex without a persistent second store."""
        source = _require_regular_file(path)
        key = self.calculate_key(source)
        if self.has_content(key):
            return key
        fd, tmp_name = tempfile.mkstemp(prefix=".efloud-annex-", dir=self.root)
        os.close(fd)
        staged = Path(tmp_name)
        try:
            shutil.copyfile(source, staged)
            _run(self.root, "annex", "setkey", str(key), staged.as_posix())
        finally:
            staged.unlink(missing_ok=True)
        if not self.has_content(key):
            msg = f"git-annex did not retain ingested content for {key}"
            raise GitAnnexError(msg)
        return key

    def ingest_bytes(self, data: bytes) -> AnnexKey:
        """Write transient bytes once, then transfer their custody to git-annex."""
        fd, tmp_name = tempfile.mkstemp(prefix=".efloud-annex-", dir=self.root)
        staged = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            key = self.calculate_key(staged)
            if self.has_content(key):
                return key
            _run(self.root, "annex", "setkey", str(key), staged.as_posix())
            if not self.has_content(key):
                msg = f"git-annex did not retain ingested content for {key}"
                raise GitAnnexError(msg)
            return key
        finally:
            staged.unlink(missing_ok=True)

    def _content_location(self, key: AnnexKey) -> Path | None:
        completed = _run(self.root, "annex", "contentlocation", str(key), check=False)
        if completed.returncode != 0:
            return None
        value = completed.stdout.strip()
        if not value:
            return None
        location = Path(value)
        return location if location.is_absolute() else self.root / location

    def has_content(self, key: AnnexKey) -> bool:
        """Return whether the key's content is physically present in this annex."""
        location = self._content_location(key)
        return location is not None and location.is_file()

    def register_url(self, key: AnnexKey, url: str) -> None:
        """Delegate URL-location registration for an existing annex key."""
        _run(self.root, "annex", "registerurl", str(key), url, "--remote=web")

    def unregister_url(self, key: AnnexKey, url: str) -> None:
        """Remove a previously registered web location for an annex key."""
        _run(self.root, "annex", "unregisterurl", str(key), url)

    def get(self, key: AnnexKey, *, remote: str | None = None) -> None:
        """Reacquire a known key from configured annex remotes when needed."""
        if self.has_content(key):
            return
        args = ["annex", "get", f"--key={key}"]
        if remote is not None:
            args.append(f"--from={_require_remote_name(remote)}")
        _run(self.root, *args)
        if not self.has_content(key):
            msg = f"git-annex did not make reacquired content available for {key}"
            raise GitAnnexError(msg)

    def drop(self, key: AnnexKey) -> None:
        """Drop local content only when git-annex verifies another safe copy."""
        if not self.has_content(key):
            return
        _run(self.root, "annex", "drop", f"--key={key}")
        if self.has_content(key):
            msg = f"git-annex reported success but retained local content for {key}"
            raise GitAnnexError(msg)

    def open(self, key: AnnexKey) -> BinaryIO:
        """Open locally present content without exposing its annex object path."""
        location = self._content_location(key)
        if location is None or not location.is_file():
            raise FileNotFoundError(str(key))
        return location.open("rb")

    def verify(self, key: AnnexKey) -> bool:
        """Delegate byte-integrity verification to git-annex, ignoring copy policy."""
        if not self.has_content(key):
            return False
        completed = _run(
            self.root,
            "annex",
            "fsck",
            f"--key={key}",
            "--numcopies=1",
            "--json",
            "--json-error-messages",
            check=False,
        )
        return completed.returncode == 0


__all__ = [
    "GitAnnexCommandError",
    "GitAnnexContentStore",
    "GitAnnexError",
    "GitAnnexUnavailableError",
]
