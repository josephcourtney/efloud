from __future__ import annotations

import functools
import shutil
import stat
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from efloud.content.git_annex import GitAnnexCommandError, GitAnnexContentStore, GitAnnexError
from efloud.git_commands import run_git

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.skipif(shutil.which("git-annex") is None, reason="git-annex is not installed"),
]


@contextmanager
def _http_file_server(root: Path) -> Iterator[str]:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=root.as_posix())
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@contextmanager
def _interruptible_http_file_server(root: Path) -> Iterator[tuple[str, Callable[[], None]]]:
    state = {"interrupt": True}

    class InterruptingHandler(SimpleHTTPRequestHandler):
        def copyfile(self, source: object, outputfile: object) -> None:
            if state["interrupt"]:
                chunk = source.read(8)  # type: ignore[attr-defined]
                outputfile.write(chunk)  # type: ignore[attr-defined]
                outputfile.flush()  # type: ignore[attr-defined]
                self.close_connection = True
                return
            shutil.copyfileobj(source, outputfile)  # type: ignore[arg-type]

    handler = functools.partial(InterruptingHandler, directory=root.as_posix())
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def allow_complete_downloads() -> None:
        state["interrupt"] = False

    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}", allow_complete_downloads
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _annex_object_path(store: GitAnnexContentStore, key: object) -> Path:
    completed = run_git(store.root, "annex", "contentlocation", str(key))
    relative = completed.stdout.strip()
    assert relative
    return store.root / relative


def test_annex_ingest_uses_content_only_key_and_preserves_source(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")
    first = tmp_path / "first.dat"
    second = tmp_path / "different-name.bin"
    first.write_bytes(b"payload")
    second.write_bytes(b"payload")

    first_key = store.ingest_path(first)
    second_key = store.ingest_path(second)

    assert first_key == second_key
    assert str(first_key).startswith("SHA256-")
    assert first.read_bytes() == b"payload"
    assert second.read_bytes() == b"payload"
    assert store.has_content(first_key)
    assert store.verify(first_key)
    with store.open(first_key) as stream:
        assert stream.read() == b"payload"


def test_annex_ingest_path_handles_unusual_filename_without_affecting_identity(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")
    source_dir = tmp_path / "directory with spaces"
    source_dir.mkdir()
    source = source_dir / "--odd [name] #δ—file.bin"
    source.write_bytes(b"portable payload")

    path_key = store.ingest_path(source)
    bytes_key = store.ingest_bytes(b"portable payload")

    assert path_key == bytes_key
    assert source.read_bytes() == b"portable payload"
    assert store.has_content(path_key)
    assert store.verify(path_key)


def test_annex_ingest_bytes_deduplicates(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")

    first_key = store.ingest_bytes(b"payload")
    duplicate_key = store.ingest_bytes(b"payload")
    assert duplicate_key == first_key

    assert store.has_content(first_key)
    assert store.verify(first_key)


def test_annex_verify_detects_corrupted_local_content(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")
    key = store.ingest_bytes(b"expected content")
    object_path = _annex_object_path(store, key)

    original_mode = object_path.stat().st_mode
    object_path.chmod(original_mode | stat.S_IWUSR)
    try:
        object_path.write_bytes(b"corrupted content")
    finally:
        if object_path.exists():
            object_path.chmod(original_mode)

    assert not store.verify(key)
    assert str(key).startswith("SHA256-")


def test_annex_drop_fails_closed_without_verified_other_copy(tmp_path: Path) -> None:
    store = GitAnnexContentStore.initialize(tmp_path / "repository")
    key = store.ingest_bytes(b"only copy")

    with pytest.raises(GitAnnexCommandError):
        store.drop(key)

    assert store.has_content(key)
    assert store.verify(key)


def test_annex_drop_and_reacquire_preserve_key_identity(tmp_path: Path) -> None:
    primary = GitAnnexContentStore.initialize(tmp_path / "primary", description="primary")
    backup = GitAnnexContentStore.initialize(tmp_path / "backup", description="backup")
    run_git(primary.root, "remote", "add", "backup", backup.root.as_posix())
    run_git(backup.root, "remote", "add", "primary", primary.root.as_posix())

    key = primary.ingest_bytes(b"portable payload")
    run_git(primary.root, "annex", "copy", "--to=backup", f"--key={key}")
    assert backup.has_content(key)

    primary.drop(key)
    assert not primary.has_content(key)
    with pytest.raises(FileNotFoundError):
        primary.open(key)

    primary.get(key)
    assert primary.has_content(key)
    assert primary.verify(key)
    with primary.open(key) as stream:
        recovered_bytes = stream.read()
    assert recovered_bytes == b"portable payload"

    recovered = tmp_path / "recovered.dat"
    recovered.write_bytes(recovered_bytes)
    assert primary.calculate_key(recovered) == key


def test_annex_registered_web_url_reacquires_same_key(tmp_path: Path) -> None:
    primary = GitAnnexContentStore.initialize(tmp_path / "primary", description="primary")
    backup = GitAnnexContentStore.initialize(tmp_path / "backup", description="backup")
    run_git(primary.root, "remote", "add", "backup", backup.root.as_posix())
    run_git(backup.root, "remote", "add", "primary", primary.root.as_posix())
    run_git(primary.root, "config", "annex.security.allowed-ip-addresses", "127.0.0.1")

    payload = b"payload from registered URL"
    web_root = tmp_path / "web"
    web_root.mkdir()
    served = web_root / "payload.bin"
    served.write_bytes(payload)

    key = primary.ingest_bytes(payload)
    run_git(primary.root, "annex", "copy", "--to=backup", f"--key={key}")

    with _http_file_server(web_root) as base_url:
        url = f"{base_url}/payload.bin"
        primary.register_url(key, url)
        primary.drop(key)
        assert not primary.has_content(key)

        primary.get(key, remote="web")
        assert primary.has_content(key)
        assert primary.verify(key)
        with primary.open(key) as stream:
            recovered_bytes = stream.read()
        assert recovered_bytes == payload

        recovered = tmp_path / "recovered-from-web.dat"
        recovered.write_bytes(recovered_bytes)
        assert primary.calculate_key(recovered) == key

        primary.unregister_url(key, url)
        primary.drop(key)
        assert not primary.has_content(key)
        with pytest.raises(GitAnnexError):
            primary.get(key, remote="web")


def test_annex_interrupted_web_get_can_be_retried_without_false_presence(tmp_path: Path) -> None:
    primary = GitAnnexContentStore.initialize(tmp_path / "primary", description="primary")
    backup = GitAnnexContentStore.initialize(tmp_path / "backup", description="backup")
    run_git(primary.root, "remote", "add", "backup", backup.root.as_posix())
    run_git(backup.root, "remote", "add", "primary", primary.root.as_posix())
    run_git(primary.root, "config", "annex.security.allowed-ip-addresses", "127.0.0.1")

    payload = b"interrupted transfer payload" * 4096
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "payload.bin").write_bytes(payload)

    key = primary.ingest_bytes(payload)
    run_git(primary.root, "annex", "copy", "--to=backup", f"--key={key}")

    with _interruptible_http_file_server(web_root) as (base_url, allow_complete_downloads):
        primary.register_url(key, f"{base_url}/payload.bin")
        primary.drop(key)
        assert not primary.has_content(key)

        with pytest.raises(GitAnnexError):
            primary.get(key, remote="web")
        assert not primary.has_content(key)
        assert not primary.verify(key)

        allow_complete_downloads()
        primary.get(key, remote="web")
        assert primary.has_content(key)
        assert primary.verify(key)
        with primary.open(key) as stream:
            recovered = stream.read()
        assert recovered == payload

        recovered_path = tmp_path / "retried.dat"
        recovered_path.write_bytes(recovered)
        assert primary.calculate_key(recovered_path) == key
