from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class EngineRuntime:
    """Advanced local runtime settings kept separate from sync intent."""

    root: Path
    http_dir: str = "http"
    cache_dir: str = "cache"
    mirrors_dir: str = "mirrors"
    rate_limits_dir: str = "rate_limits"
    http_cache_dir: str = "http_cache"
    runtime_progress: bool = False
    remove_empty_dirs_after_rsync: bool = True

    @classmethod
    def for_root(cls, root: Path) -> EngineRuntime:
        return cls(root=root.resolve())

    @property
    def http_root(self) -> Path:
        return self.root / self.http_dir

    @property
    def mirrors_root(self) -> Path:
        return self.root / self.mirrors_dir

    @property
    def http_cache_root(self) -> Path:
        return self.root / self.cache_dir / self.http_cache_dir

    @property
    def rate_limits_root(self) -> Path:
        return self.root / self.rate_limits_dir


__all__ = ["EngineRuntime"]
