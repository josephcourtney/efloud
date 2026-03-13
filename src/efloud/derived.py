from pathlib import Path
from typing import Protocol

from efloud.manifest import NormalizedManifest
from efloud.registry import SourceDefinition


class DerivedTask(Protocol):
    name: str

    async def run(
        self,
        *,
        sync_root: Path,
        manifest: NormalizedManifest,
        sources: tuple[SourceDefinition, ...],
    ) -> dict[str, object]: ...
