from __future__ import annotations

import asyncio
import functools
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from efloud import Engine, HttpSource, Repository
from efloud.content.git_annex import GitAnnexContentStore
from efloud.git_commands import run_git

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.slow,
    pytest.mark.timeout(120),
    pytest.mark.skipif(shutil.which("git-annex") is None, reason="git-annex is not installed"),
]


def test_annex_ingest_uses_content_only_key_and_preserves_source(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")
    first = tmp_path / "first.dat"
    second = tmp_path / "different-name.bin"
    unusual = tmp_path / "directory with spaces" / "ümlaut-file.bin"
    unusual.parent.mkdir()
    first.write_bytes(b"payload")
    second.write_bytes(b"payload")
    unusual.write_bytes(b"payload")

    first_key = store.ingest_path(first)
    second_key = store.ingest_path(second)
    unusual_key = store.ingest_path(unusual)

    assert first_key == second_key == unusual_key
    assert str(first_key).startswith("SHA256-")
    content = store.content_ref(first_key, media_type="application/octet-stream")
    assert str(content.content_id).startswith("sha256:")
    assert content.byte_size == len(b"payload")
    assert content.custody_key == str(first_key)
    assert first.read_bytes() == b"payload"
    assert second.read_bytes() == b"payload"
    assert store.has_content(first_key)
    assert store.verify(first_key)
    with store.open(first_key) as stream:
        assert stream.read() == b"payload"


def test_annex_ingest_bytes_deduplicates(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")

    first_key = store.ingest_bytes(b"payload")
    duplicate_key = store.ingest_bytes(b"payload")
    assert duplicate_key == first_key

    assert store.has_content(first_key)
    assert store.verify(first_key)


def test_annex_ingest_url_keeps_only_annex_custody(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    payload = b"native url acquisition"
    source = source_dir / "payload.bin"
    source.write_bytes(payload)

    store = GitAnnexContentStore.initialize(repository)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(source_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        run_git(
            repository,
            "config",
            "annex.security.allowed-ip-addresses",
            f"[127.0.0.1]:{port}",
        )
        key = store.ingest_url(f"http://127.0.0.1:{port}/payload.bin")
        assert str(key).startswith("SHA256-")
        assert store.has_content(key)
        assert store.verify(key)
        with store.open(key) as stream:
            assert stream.read() == payload
        assert not any(path.name.startswith("efloud-url-") for path in repository.iterdir())
        assert not any(path.name.startswith(".efloud-url-index-") for path in repository.iterdir())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_repository_content_reference_survives_reopen(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    store = GitAnnexContentStore.open_or_initialize(root)
    key = store.ingest_bytes(b"payload")
    first = store.content_ref(key)
    reopened = GitAnnexContentStore.open_or_initialize(root)
    second = reopened.content_ref(key)
    assert second == first
    assert reopened.has_content(key)


def test_present_keys_and_drop_key_are_custody_operations(tmp_path: Path) -> None:
    store = GitAnnexContentStore.open_or_initialize(tmp_path)
    key = store.ingest_bytes(b"payload")
    assert key in store.present_keys()
    assert store.has_content(key)
    store.drop_key(key)
    assert key not in store.present_keys()
    assert not store.has_content(key)


def test_registered_url_reacquires_dropped_and_corrupt_content(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    payload = b"reacquire this content"
    source = source_dir / "payload.bin"
    source.write_bytes(payload)

    store = GitAnnexContentStore.initialize(repository)
    key = store.ingest_path(source)
    identity = store.content_ref(key)

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(source_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        run_git(
            repository,
            "config",
            "annex.security.allowed-ip-addresses",
            f"[127.0.0.1]:{port}",
        )
        store.register_url(key, f"http://127.0.0.1:{port}/payload.bin")

        location = store._content_location(key)
        assert location is not None
        location.chmod(0o644)
        try:
            location.write_bytes(b"corrupted")
        finally:
            location.chmod(0o444)
        assert not store.verify(key)

        store.drop_key(key)
        assert not store.has_content(key)
        store.get(key)

        assert store.has_content(key)
        assert store.verify(key)
        assert store.content_ref(key) == identity
        with store.open(key) as stream:
            assert stream.read() == payload
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_builtin_http_source_acquires_directly_into_annex_custody(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    payload = b"direct HTTP custody"
    (source_dir / "payload.bin").write_bytes(payload)

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(source_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/payload.bin"
        with Repository.create(repository_root) as repository:
            run_git(
                repository_root,
                "config",
                "annex.security.allowed-ip-addresses",
                f"[127.0.0.1]:{port}",
            )
            result = asyncio.run(Engine(repository, [HttpSource(id="direct", url=url)]).sync())
            assert result.ok

        with ReadOnlyRepository(repository_root) as repository:
            observation = repository.latest_observation("source:direct")
            assert observation is not None
            assert repository.verify_content(observation.content_id)
            with repository.open_content(observation.content_id) as stream:
                assert stream.read() == payload

        assert not (repository_root / ".efloud-runtime" / "staging" / "http").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
