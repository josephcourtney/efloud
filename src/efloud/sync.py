"""Compatibility entry point delegating to canonical Engine orchestration."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from efloud.engine import Engine

if TYPE_CHECKING:
    from efloud.models import EngineConfig, SyncResult


async def sync(cfg: EngineConfig) -> SyncResult:
    warnings.warn("sync(cfg) is deprecated; use Engine.from_config(cfg).sync()", DeprecationWarning, stacklevel=2)
    with Engine.from_config(cfg) as engine:
        return (await engine.sync()).compatibility.sync_result
