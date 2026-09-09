"""Deprecated alpha sync entry point isolated behind compatibility conversion."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from efloud.compat.engine import legacy_request, legacy_runtime, legacy_sources
from efloud.compat.outputs import project_execution
from efloud.engine import Engine
from efloud.repository import Repository

if TYPE_CHECKING:
    from efloud.models import EngineConfig, SyncResult


async def sync(cfg: EngineConfig) -> SyncResult:
    """Run an alpha EngineConfig through the canonical engine, then project legacy output."""
    warnings.warn(
        "sync(cfg) is deprecated; use Repository + Engine + SyncRequest",
        DeprecationWarning,
        stacklevel=2,
    )
    sources = legacy_sources(cfg)
    with Repository(cfg.root) as repository:
        engine = Engine(
            repository,
            sources,
            runtime=legacy_runtime(cfg),
            policy=cfg.sync_policy,
        )
        result = await engine.sync(legacy_request(cfg))
        return project_execution(repository, config=cfg, result=result).sync_result
