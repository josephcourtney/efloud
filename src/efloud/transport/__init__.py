from __future__ import annotations

from efloud.transport.http_utils import HttpFetchResult, cache_group_name, dest_for_http_source
from efloud.transport.rsync import OpResult, RsyncCommandConfig, RsyncMirror, RsyncMirrorConfig

__all__ = [
    "HttpFetchResult",
    "OpResult",
    "RsyncCommandConfig",
    "RsyncMirror",
    "RsyncMirrorConfig",
    "cache_group_name",
    "dest_for_http_source",
]
