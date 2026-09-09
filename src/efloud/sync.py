"""Compatibility entry point delegating to canonical Engine orchestration."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from efloud.compat.outputs import project_execution
from efloud.engine import Engine

if TYPE_CHECKING:
    from efloud.models import EngineConfig, SyncResult


async def sync(cfg: EngineConfig) -> SyncResult:
    warnings.warn("sync(cfg) is deprecated; use Engine.from_config(cfg).sync()", DeprecationWarning, stacklevel=2)
    with Engine.from_config(cfg) as engine:
        result = await engine.sync()
        return project_execution(engine.repository, config=cfg, result=result).sync_result
