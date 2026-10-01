from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from efloud.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.skipif(shutil.which("git-annex") is None, reason="git-annex is not installed"),
]


def test_repository_ingest_uses_annex_custody_and_reopens(tmp_path: Path) -> None:
    root = tmp_path / "repository"

    with Repository(root) as repository:
        source = repository.register_source("test-source", {"kind": "test"})
        run = repository.start_run(source_ids=(source,), started_at=100.0)
        operation = repository.start_operation(
            run_id=run,
            source_id=source,
            kind="fetch",
            subject="artifact:a",
            started_at=100.0,
        )
        observation = repository.ingest_bytes(
            "artifact:a",
            b"payload",
            run_id=run,
            operation_id=operation,
            source_id=source,
            observed_at=101.0,
        )
        content = repository.content(observation.content_id)
        assert content is not None
        assert content.custody_key.startswith("SHA256-")
        assert repository.contains_content(observation.content_id)
        assert repository.verify_content(observation.content_id)

    with Repository(root) as reopened:
        assert reopened.contains_content(observation.content_id)
        with reopened.open_content(observation.content_id) as stream:
            assert stream.read() == b"payload"
