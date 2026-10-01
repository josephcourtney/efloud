from __future__ import annotations

import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] - argv-only subprocesses are the Git integration boundary.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class GitError(RuntimeError):
    """Base failure for the internal Git command boundary."""


class GitUnavailableError(GitError):
    """Git is not available to the current process."""


class GitCommandError(GitError):
    """A Git subprocess returned a non-zero exit status."""

    def __init__(self, command: tuple[str, ...], returncode: int, stderr: str) -> None:
        detail = stderr.strip() or "command failed without stderr"
        super().__init__(f"Command failed ({returncode}): {' '.join(command)}: {detail}")
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


def _git_command(root: Path, args: tuple[str, ...], env: Mapping[str, str] | None) -> tuple[tuple[str, ...], dict[str, str]]:
    if not root.is_dir():
        msg = f"Git working directory does not exist: {root}"
        raise GitError(msg)
    git = shutil.which("git")
    if git is None:
        msg = "git is not available on PATH"
        raise GitUnavailableError(msg)
    process_env = os.environ.copy()
    if env is not None:
        process_env.update(env)
    return (git, *args), process_env


def run_git(
    root: Path,
    *args: str,
    check: bool = True,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Git without a shell from one explicit repository working directory."""
    command, process_env = _git_command(root, args, env)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - no shell; argv is passed directly to Git.
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
        env=process_env,
    )
    if check and completed.returncode != 0:
        raise GitCommandError(command, completed.returncode, completed.stderr)
    return completed


def run_git_bytes(
    root: Path,
    *args: str,
    check: bool = True,
    env: Mapping[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run Git with binary stdin/stdout for object-database operations."""
    command, process_env = _git_command(root, args, env)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - no shell; argv is passed directly to Git.
        command,
        cwd=root,
        check=False,
        capture_output=True,
        input=input_bytes,
        env=process_env,
    )
    if check and completed.returncode != 0:
        raise GitCommandError(command, completed.returncode, completed.stderr.decode("utf-8", errors="replace"))
    return completed


__all__ = ["GitCommandError", "GitError", "GitUnavailableError", "run_git", "run_git_bytes"]
