# efloud

`efloud` is a Python library for building local mirrors of remote data.

It is designed for projects that need to pull data from a mix of upstream sources, keep the results on disk in a stable layout, and record enough metadata to inspect what was fetched, when it was fetched, and where the materialized artifacts live.

## What It Does

`efloud` syncs external sources into a single local root and keeps a small set of machine-readable records alongside the fetched data.

Current source patterns:

- `HTTP` and `REST` sources fetched into local files
- `RSYNC` sources mirrored into local directories
- derived `REST_BASE` fanout tasks that expand one API surface into many per-item files

It also maintains:

- a canonical merged sync manifest
- timestamped per-run manifests
- a mirror-state file with a hash tree for mirrored directories
- persistent HTTP cache and rate-limit state
- query and status helpers for downstream tooling

## Use Cases

`efloud` is a good fit when you want a reproducible local cache of upstream data instead of issuing ad hoc network requests throughout an application or pipeline.

Typical use cases:

- build a local mirror of reference datasets used by analysis or ETL jobs
- combine `rsync` mirrors and HTTP API fetches under one managed cache root
- materialize remote API resources into stable on-disk files for offline or repeatable processing
- expose sync status, health, and manifest metadata to other automation or observability tools
- maintain derived per-item artifacts from a base API endpoint

It is not a generic file-sync desktop app. The current implementation is library-first and oriented toward embedding in Python workflows.

## Current Scope

The repository is still in alpha. The public surface today is centered on Python APIs such as:

- `efloud.sync()` to perform a sync run
- `EngineConfig` and `SourceDefinition` to describe the mirror root and upstream sources
- `query_target()`, `root_payload()`, `store_payload()`, and `source_payload()` to inspect cached artifacts
- `collect_status_payload()` and `build_summary()` to summarize sync outcomes
- `RestBaseFanoutTask` for derived fanout materialization

`pyproject.toml` currently declares an `efloud` console script, but the repository does not yet contain a documented CLI entrypoint. The stable thing to rely on today is the Python API.

## Core Concepts

### Engine Root

Each sync run writes into one configured root directory. Under that root, `efloud` uses conventional subdirectories for:

- `http/` for HTTP and REST artifacts
- `mirrors/` for `rsync` mirrors
- `cache/http_cache/` for persistent HTTP cache state
- `rate_limits/` for rate-limit and retry state
- `log/` for sync manifests
- `mirror-state.json` for filesystem hash-tree state

### Sources

Each upstream is modeled as a `SourceDefinition` with:

- a stable `id`
- a human-readable `description`
- a `url`
- a `SourceKind`

`RSYNC` sources can also specify:

- `local_subpath`
- `mirror_mode`
- `mirror_paths`

### Manifest

Every run produces a manifest with:

- run timestamps
- effective sync configuration
- per-source HTTP results
- per-source `rsync` results
- derived task results
- run-level errors

The canonical manifest is merged across runs so targeted syncs do not discard older source results for untouched sources.

### Derived Tasks

Derived tasks run after transport sync phases and can materialize additional artifacts based on the fetched data. The built-in `RestBaseFanoutTask` supports enumerating item identifiers and writing each fetched response into a bucketed file layout.

## Example

The example below shows the current library-oriented usage pattern.

```python
from pathlib import Path
import asyncio

from efloud import EngineConfig, SourceDefinition, SourceKind, sync


async def main() -> None:
    cfg = EngineConfig(
        root=Path("./mirror-root"),
        sources=[
            SourceDefinition(
                id="example-json",
                description="Example JSON payload",
                url="https://example.test/data.json",
                kind=SourceKind.HTTP,
            ),
            SourceDefinition(
                id="example-rsync",
                description="Example rsync mirror",
                url="rsync.example.test::module",
                kind=SourceKind.RSYNC,
                local_subpath="reference/module",
            ),
        ],
    )

    result = await sync(cfg)
    print(result.ok)
    print(result.manifest_path)


asyncio.run(main())
```

After a successful run, downstream code can inspect the cached state without re-fetching upstream data.

```python
from pathlib import Path

from efloud import EngineConfig, SourceDefinition, SourceKind, query_target

cfg = EngineConfig(
    root=Path("./mirror-root"),
    sources=[
        SourceDefinition(
            id="example-json",
            description="Example JSON payload",
            url="https://example.test/data.json",
            kind=SourceKind.HTTP,
        )
    ],
)

payload = query_target("source:example-json", cfg=cfg)
print(payload["local_path"])
```

## Query and Status Helpers

The query helpers treat the mirror root as a small inspectable data store.

Supported target shapes include:

- `root`
- `source:<source-id>`
- `store:sync_manifest`
- `store:mirror_state`
- `index:<index-id>`
- `source:<source-id>#/json/pointer`

These return structured payloads suitable for programmatic inspection rather than human-formatted terminal output.

## Installation

This project uses `uv` for dependency management in development.

To work on the repository locally:

```bash
uv sync
```

To run the validation commands used by the project:

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format src/ tests/
.venv/bin/ty check src/ tests/
.venv/bin/pytest
```

## Project Status

The implementation is ahead of the written docs. Several repository documents are still placeholders, so the most accurate description of current behavior is in the source and tests.

For the most relevant code paths, start with:

- `src/efloud/sync.py`
- `src/efloud/query.py`
- `src/efloud/status.py`
- `src/efloud/fanout.py`
- `tests/unit/test_fanout_and_sync.py`
- `tests/unit/test_summary_health_status_query.py`
