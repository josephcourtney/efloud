from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

GitFileMode = Literal["100644", "100755", "120000"]


@dataclass(frozen=True, slots=True)
class GitTreeId:
    """Opaque Git tree object identity used only at the infrastructure boundary."""

    value: str

    def __post_init__(self) -> None:
        """Reject empty or whitespace-containing tree object IDs."""
        if not self.value or any(char.isspace() for char in self.value):
            msg = "Git tree IDs must be non-empty single tokens"
            raise ValueError(msg)

    def __str__(self) -> str:
        """Return the underlying Git tree object ID."""
        return self.value


@dataclass(frozen=True, slots=True)
class GitCommitId:
    """Opaque Git commit object identity used only at the infrastructure boundary."""

    value: str

    def __post_init__(self) -> None:
        """Reject empty or whitespace-containing commit object IDs."""
        if not self.value or any(char.isspace() for char in self.value):
            msg = "Git commit IDs must be non-empty single tokens"
            raise ValueError(msg)

    def __str__(self) -> str:
        """Return the underlying Git commit object ID."""
        return self.value


@dataclass(frozen=True, slots=True)
class TreeBlob:
    """One small Git-tree payload; durable bulk content remains owned by git-annex."""

    relative_path: str
    data: bytes
    mode: GitFileMode = "100644"

    def __post_init__(self) -> None:
        """Reject paths that cannot represent one safe repository-relative Git entry."""
        parts = self.relative_path.split("/")
        if (
            not self.relative_path
            or self.relative_path.startswith("/")
            or "\x00" in self.relative_path
            or any(part in {"", ".", ".."} for part in parts)
        ):
            msg = f"Invalid Git tree path: {self.relative_path!r}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GitTreeEntry:
    """One recursively listed Git tree entry."""

    relative_path: str
    mode: str
    object_type: str
    object_id: str


class TreeStore(Protocol):
    """Narrow Git tree/history port, separate from semantic dataset identity."""

    def write_tree(self, entries: tuple[TreeBlob, ...]) -> GitTreeId: ...

    def list_tree(self, treeish: GitTreeId | GitCommitId | str) -> tuple[GitTreeEntry, ...]: ...

    def read_blob(self, object_id: str) -> bytes: ...

    def commit_tree(
        self,
        tree: GitTreeId,
        *,
        ref: str,
        message: str,
    ) -> GitCommitId: ...


__all__ = [
    "GitCommitId",
    "GitFileMode",
    "GitTreeEntry",
    "GitTreeId",
    "TreeBlob",
    "TreeStore",
]
