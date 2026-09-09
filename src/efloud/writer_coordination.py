"""Local repository writer lease, released by the OS after a crash."""

from __future__ import annotations

import fcntl
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class RepositoryBusyError(RuntimeError):
    """Another writer or maintenance operation owns the repository."""


class WriterLease:
    def __init__(self, root: Path) -> None:
        self._descriptor: int | None = os.open(root / ".writer.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(self._descriptor)
            self._descriptor = None
            msg = f"Repository already has an active writer: {root.as_posix()}"
            raise RepositoryBusyError(msg) from error

    def require_active(self) -> None:
        if self._descriptor is None:
            msg = "Repository writer is closed"
            raise RuntimeError(msg)

    def close(self) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
