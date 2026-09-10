from __future__ import annotations

import asyncio
import contextlib
import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    LocalAcquisition,
    SourceAdapter,
)
from efloud.sources import LocalSource

_LOCAL_DESCRIPTOR = AdapterDescriptor(
    adapter_id="efloud:local",
    version="1",
    capabilities=AdapterCapabilities(inventory=False, fetch=True),
)


def _source(
    context: AdapterExecutionContext,
    descriptor: AdapterDescriptor,
) -> LocalSource:
    source = context.source
    if (
        not isinstance(source, LocalSource)
        or source.adapter_id != descriptor.adapter_id
        or context.operation.producer != descriptor.producer
    ):
        msg = f"Adapter {descriptor.adapter_id!r} cannot acquire {type(source).__name__}."
        raise TypeError(msg)
    return source


def _staging_path(context: AdapterExecutionContext, source: LocalSource) -> Path:
    identity = hashlib.sha256(source.id.encode("utf-8")).hexdigest()
    suffix = Path(source.path).suffix
    return context.runtime.staging_root / "local" / f"{identity}{suffix}"


def _copy_stable_source(source_path: Path, destination: Path) -> tuple[float, int]:
    resolved = source_path.resolve(strict=True)
    before = resolved.stat()
    if not resolved.is_file():
        msg = f"Local source is not a regular file: {resolved}"
        raise ValueError(msg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        shutil.copyfile(resolved, temporary)
        after = resolved.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            msg = f"Local source changed while being imported: {resolved}"
            raise RuntimeError(msg)
        temporary.replace(destination)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    return before.st_mtime, before.st_size


@dataclass(frozen=True, slots=True)
class LocalSourceAdapter:
    descriptor: AdapterDescriptor = _LOCAL_DESCRIPTOR

    async def acquire(self, context: AdapterExecutionContext) -> LocalAcquisition:
        source = _source(context, self.descriptor)
        source_path = Path(source.path)
        destination = _staging_path(context, source)
        try:
            modified_at, size_bytes = await asyncio.to_thread(
                _copy_stable_source,
                source_path,
                destination,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return LocalAcquisition(
                source_id=source.id,
                status="failed",
                destination=None,
                observed_at=time.time(),
                media_type=source.media_type,
                expected_integrity=source.expected_integrity,
                error=f"{type(exc).__name__}: {exc}",
            )
        return LocalAcquisition(
            source_id=source.id,
            status="succeeded",
            destination=destination,
            observed_at=time.time(),
            source_modified_at=modified_at,
            size_bytes=size_bytes,
            media_type=source.media_type,
            expected_integrity=source.expected_integrity,
        )


def local_source_adapter() -> SourceAdapter:
    return LocalSourceAdapter()


__all__ = ["LocalSourceAdapter", "local_source_adapter"]
