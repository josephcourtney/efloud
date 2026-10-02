from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class EngineRuntime:
    """Advanced local runtime settings for non-authoritative transport state."""

    root: Path
    operational_dir: str = ".efloud-runtime"
    runtime_progress: bool = False
    remove_empty_dirs_after_rsync: bool = True

    @classmethod
    def for_root(cls, root: Path) -> EngineRuntime:
        return cls(root=root.resolve())

    @property
    def operational_root(self) -> Path:
        return self.root / self.operational_dir

    @property
    def staging_root(self) -> Path:
        return self.operational_root / "staging"

    @property
    def http_root(self) -> Path:
        return self.staging_root / "http"

    @property
    def rsync_root(self) -> Path:
        return self.staging_root / "rsync"


__all__ = ["EngineRuntime"]
