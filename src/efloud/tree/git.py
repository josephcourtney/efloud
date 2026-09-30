from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from efloud.git_commands import run_git
from efloud.tree.protocol import GitCommitId, GitTreeEntry, GitTreeId, TreeBlob

_GIT_IDENTITY_NAME = "Efloud"
_GIT_IDENTITY_EMAIL = "efloud@localhost.invalid"


@dataclass(frozen=True, slots=True)
class GitTreeStore:
    """Git object-database implementation of Efloud's internal tree/history port."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())

    @classmethod
    def initialize(cls, root: Path) -> GitTreeStore:
        """Initialize ordinary Git state without changing Efloud semantic identity."""
        resolved = root.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        run_git(resolved, "init", "--quiet")
        run_git(resolved, "config", "user.name", _GIT_IDENTITY_NAME)
        run_git(resolved, "config", "user.email", _GIT_IDENTITY_EMAIL)
        return cls(resolved)

    def check_available(self) -> None:
        """Fail explicitly when the configured root is not an accessible Git repository."""
        run_git(self.root, "rev-parse", "--git-dir")

    def _write_blob(self, data: bytes) -> str:
        fd, tmp_name = tempfile.mkstemp(prefix=".efloud-tree-blob-", dir=self.root)
        path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            completed = run_git(self.root, "hash-object", "-w", path.as_posix())
            object_id = completed.stdout.strip()
            if not object_id:
                msg = "git hash-object returned an empty object ID"
                raise RuntimeError(msg)
            return object_id
        finally:
            path.unlink(missing_ok=True)

    def write_tree(self, entries: tuple[TreeBlob, ...]) -> GitTreeId:
        """Write a canonical tree using an isolated temporary Git index."""
        paths = [entry.relative_path for entry in entries]
        if len(paths) != len(set(paths)):
            msg = "Git tree entries must have unique paths"
            raise ValueError(msg)

        fd, index_name = tempfile.mkstemp(prefix=".efloud-tree-index-", dir=self.root)
        os.close(fd)
        index_path = Path(index_name)
        index_path.unlink()
        environment = {"GIT_INDEX_FILE": index_path.as_posix()}
        try:
            for entry in entries:
                object_id = self._write_blob(entry.data)
                run_git(
                    self.root,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    entry.mode,
                    object_id,
                    entry.relative_path,
                    env=environment,
                )
            completed = run_git(self.root, "write-tree", env=environment)
            tree_id = completed.stdout.strip()
            if not tree_id:
                msg = "git write-tree returned an empty tree ID"
                raise RuntimeError(msg)
            return GitTreeId(tree_id)
        finally:
            index_path.unlink(missing_ok=True)

    def list_tree(self, treeish: GitTreeId | GitCommitId | str) -> tuple[GitTreeEntry, ...]:
        """List recursive leaf entries without consulting the working tree."""
        completed = run_git(
            self.root,
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            str(treeish),
        )
        entries: list[GitTreeEntry] = []
        for record in completed.stdout.split("\x00"):
            if not record:
                continue
            metadata, relative_path = record.split("\t", 1)
            mode, object_type, object_id = metadata.split(" ", 2)
            entries.append(
                GitTreeEntry(
                    relative_path=relative_path,
                    mode=mode,
                    object_type=object_type,
                    object_id=object_id,
                )
            )
        return tuple(entries)

    def commit_tree(
        self,
        tree: GitTreeId,
        *,
        ref: str,
        message: str,
    ) -> GitCommitId:
        """Commit a tree onto one explicit retained Git ref, preserving linear history."""
        if not ref.startswith("refs/"):
            msg = f"Git history refs must be fully qualified: {ref!r}"
            raise ValueError(msg)
        run_git(self.root, "check-ref-format", ref)

        parent_result = run_git(
            self.root,
            "rev-parse",
            "--verify",
            "--quiet",
            f"{ref}^{{commit}}",
            check=False,
        )
        command = ["commit-tree", str(tree)]
        parent = parent_result.stdout.strip() if parent_result.returncode == 0 else ""
        if parent:
            command.extend(("-p", parent))
        command.extend(("-m", message))
        completed = run_git(self.root, *command)
        commit_id = completed.stdout.strip()
        if not commit_id:
            msg = "git commit-tree returned an empty commit ID"
            raise RuntimeError(msg)
        if parent:
            run_git(self.root, "update-ref", ref, commit_id, parent)
        else:
            run_git(self.root, "update-ref", ref, commit_id)
        return GitCommitId(commit_id)


__all__ = ["GitTreeStore"]
