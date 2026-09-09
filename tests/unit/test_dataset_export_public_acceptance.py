"""Acceptance of reproducible dataset handoff through the clean public API."""

from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import efloud.materialization as materialization_module
from efloud import DatasetManifest, DatasetSpec, Engine, HttpSource, Repository, RsyncSource, SyncRequest
from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    AdapterRegistry,
    HttpAcquisition,
    RsyncAcquisition,
)
from efloud.errors import DatasetConstraintError, DatasetError, ExportError
from efloud.transport.rsync_inventory import RsyncInventory, RsyncInventoryEntry

if TYPE_CHECKING:
    pass

pytestmark = [pytest.mark.component, pytest.mark.acceptance, pytest.mark.regression, pytest.mark.db, pytest.mark.medium]


@dataclass
class SequencedHttpAdapter:
    payloads: tuple[bytes, ...]
    calls: int = 0
    descriptor: AdapterDescriptor = field(
        default_factory=lambda: AdapterDescriptor(
            adapter_id="efloud:http",
            version="acceptance-1",
            capabilities=AdapterCapabilities(inventory=False, fetch=True),
        )
    )

    async def acquire(self, context: AdapterExecutionContext) -> HttpAcquisition:
        index = self.calls
        if index >= len(self.payloads):
            msg = "HTTP acceptance adapter exhausted"
            raise AssertionError(msg)
        self.calls += 1
        destination = context.runtime.http_root / f"{context.source.id}-{self.calls}.bin"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.payloads[index])
        await asyncio.sleep(0)
        return HttpAcquisition(
            source_id=context.source.id,
            status="succeeded",
            destination=destination,
            observed_at=float(self.calls),
            status_code=200,
            etag=f'"v{self.calls}"',
        )


@dataclass
class SequencedRsyncAdapter:
    acquisitions: tuple[RsyncAcquisition, ...]
    calls: int = 0
    descriptor: AdapterDescriptor = field(
        default_factory=lambda: AdapterDescriptor(
            adapter_id="efloud:rsync",
            version="acceptance-1",
            capabilities=AdapterCapabilities(inventory=True, fetch=True),
        )
    )

    async def acquire(self, context: AdapterExecutionContext) -> RsyncAcquisition:
        if self.calls >= len(self.acquisitions):
            msg = "rsync acceptance adapter exhausted"
            raise AssertionError(msg)
        acquisition = self.acquisitions[self.calls]
        self.calls += 1
        assert acquisition.source_id == context.source.id
        await asyncio.sleep(0)
        return acquisition


def _http_source(*, role: str | None = None, tags: tuple[str, ...] = ()) -> HttpSource:
    return HttpSource(
        id="example",
        url="https://example.test/data.bin",
        role=role,
        tags=tags,
    )


def _sync_http(
    repository: Repository,
    adapter: SequencedHttpAdapter,
    source: HttpSource,
    *,
    refresh: bool = False,
) -> None:
    result = asyncio.run(
        Engine(repository, [source], adapters=AdapterRegistry((adapter,))).sync(SyncRequest(refresh=refresh))
    )
    assert result.ok


def _blob_path(root: Path, content_id: str) -> Path:
    digest = content_id.removeprefix("sha256:")
    return root / "objects" / "sha256" / digest[:2] / digest


def test_resolve_is_read_only_while_freeze_persists_same_identity(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    adapter = SequencedHttpAdapter((b"payload",))
    with Repository.create(root) as repository:
        _sync_http(repository, adapter, _http_source())

    before_resolve = (root / "metadata.sqlite").read_bytes()
    spec = DatasetSpec.latest("source:example").with_metadata(purpose="acceptance")
    with Repository.open(root, mode="r") as repository:
        resolved = repository.datasets.resolve(spec)
        assert resolved.verify()
        resolved_id = resolved.id
        resolved_specification_id = resolved.specification_id
        resolved_content_identity = resolved.content_identity
        with pytest.raises(DatasetError):
            repository.datasets.get(resolved.id)
    assert (root / "metadata.sqlite").read_bytes() == before_resolve

    with Repository.open(root, mode="rw") as repository:
        frozen = repository.datasets.freeze(spec)
        assert frozen.id == resolved_id
        assert frozen.specification_id == resolved_specification_id
        assert frozen.content_identity == resolved_content_identity
        frozen_members = frozen.members()
    assert (root / "metadata.sqlite").read_bytes() != before_resolve

    with Repository.open(root, mode="r") as repository:
        reopened = repository.datasets.get(resolved_id)
        assert reopened.members() == frozen_members
        assert reopened.specification_id == resolved_specification_id
        assert reopened.content_identity == resolved_content_identity


def test_freeze_export_manifest_reopens_and_verifies_after_repository_is_gone(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    export = tmp_path / "export"
    elsewhere = tmp_path / "elsewhere"
    adapter = SequencedHttpAdapter((b"payload",))
    with Repository.create(root) as repository:
        _sync_http(repository, adapter, _http_source(role="reference"))
        dataset = repository.datasets.freeze(DatasetSpec.latest_source_snapshot("example"))
        manifest = dataset.export(export, paths={"source:example": "catalog/example.bin"}, strategy="copy")
        dataset_id = dataset.id
        serialized = manifest.to_bytes()

    assert (export / "dataset-manifest.json").read_bytes() == serialized
    shutil.copytree(export, elsewhere)
    shutil.rmtree(root)
    reopened = DatasetManifest.from_bytes(serialized)
    assert reopened.dataset_id == dataset_id
    assert reopened.verify(elsewhere)
    assert not (elsewhere / "metadata.sqlite").exists()


def test_frozen_membership_and_detached_evidence_ignore_later_source_changes(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    adapter = SequencedHttpAdapter((b"first", b"second"))
    old_source = _http_source(role="reference", tags=("stable",))
    new_source = _http_source(role="current", tags=("changed",))
    spec = DatasetSpec.latest("source:example")

    with Repository.create(root) as repository:
        _sync_http(repository, adapter, old_source)
        frozen = repository.datasets.freeze(spec)
        frozen_id = frozen.id
        frozen_members = frozen.members()
        frozen_manifest = frozen.manifest(paths={"source:example": "data/example.bin"}).to_bytes()

        _sync_http(repository, adapter, new_source, refresh=True)
        current = repository.datasets.resolve(spec)
        assert current.id != frozen_id
        with current.open("source:example") as stream:
            assert stream.read() == b"second"
        assert frozen.id == frozen_id
        assert frozen.members() == frozen_members
        with frozen.open("source:example") as stream:
            assert stream.read() == b"first"
        assert frozen.manifest(paths={"source:example": "data/example.bin"}).to_bytes() == frozen_manifest

    detached = json.loads(frozen_manifest)
    assert detached["members"][0]["source_revision"]["definition"]["role"] == "reference"
    assert detached["members"][0]["source_revision"]["definition"]["tags"] == ["stable"]


def test_incomplete_source_snapshot_never_implies_absence_or_reproducibility(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "item.txt").write_bytes(b"first")
    source = RsyncSource(id="mirror", url="rsync://example.test/module")
    complete_inventory = RsyncInventory(
        entries=(
            RsyncInventoryEntry(
                relative_path="item.txt",
                kind="file",
                byte_size=5,
                modified="2026-09-09 00:00:00",
            ),
        ),
        complete=True,
    )
    incomplete_inventory = RsyncInventory(entries=(), complete=False, error="injected incomplete coverage")
    adapter = SequencedRsyncAdapter((
        RsyncAcquisition(
            source_id="mirror",
            status="succeeded",
            local_root=mirror,
            scope=(),
            observed_at=1.0,
            inventory=complete_inventory,
            updated_paths=("item.txt",),
        ),
        RsyncAcquisition(
            source_id="mirror",
            status="succeeded",
            local_root=mirror,
            scope=(),
            observed_at=2.0,
            inventory=incomplete_inventory,
            updated_paths=(),
        ),
    ))

    with Repository.create(root) as repository:
        engine = Engine(repository, [source], adapters=AdapterRegistry((adapter,)))
        assert asyncio.run(engine.sync()).ok
        assert asyncio.run(engine.sync(SyncRequest(refresh=True))).ok
        snapshots = repository.sources.snapshots("mirror", limit=None)
        assert snapshots[0].complete is False
        assert snapshots[1].complete is True

        latest = repository.datasets.resolve(DatasetSpec.latest("source:mirror:path:item.txt"))
        with latest.open("source:mirror:path:item.txt") as stream:
            assert stream.read() == b"first"

        with pytest.raises(DatasetError, match="complete membership"):
            repository.datasets.resolve(DatasetSpec.source_snapshot(str(snapshots[0].snapshot_id)))

        prior_complete = repository.datasets.resolve(DatasetSpec.latest_source_snapshot("mirror"))
        assert prior_complete.members() == latest.members()

        with pytest.raises(DatasetConstraintError):
            repository.datasets.resolve(DatasetSpec.source("missing").require(complete_snapshots=True))


def test_missing_and_corrupt_content_fail_verification_without_repository_mutation(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    export = tmp_path / "export"
    adapter = SequencedHttpAdapter((b"payload",))
    with Repository.create(root) as repository:
        _sync_http(repository, adapter, _http_source())
        dataset = repository.datasets.freeze(DatasetSpec.latest("source:example"))
        dataset_id = dataset.id
        content_id = dataset.member("source:example").content_id
        manifest = dataset.export(export, strategy="copy")

    metadata_before = (root / "metadata.sqlite").read_bytes()
    assert DatasetManifest.from_bytes(manifest.to_bytes()).verify(tmp_path / "missing-export") is False
    exported_member = export / json.loads(manifest.to_bytes())["members"][0]["path"]
    exported_member.write_bytes(b"corrupt export")
    assert manifest.verify(export) is False
    exported_member.unlink()
    assert manifest.verify(export) is False
    assert (root / "metadata.sqlite").read_bytes() == metadata_before

    blob = _blob_path(root, content_id)
    blob.write_bytes(b"corrupt repository content")
    with Repository.open(root, mode="r") as repository:
        reopened = repository.datasets.get(dataset_id)
        assert reopened.verify() is False
        with pytest.raises(ExportError, match="verification"):
            reopened.export(tmp_path / "corrupt-export", strategy="copy")
        assert not (tmp_path / "corrupt-export").exists()
    assert (root / "metadata.sqlite").read_bytes() == metadata_before

    blob.unlink()
    with Repository.open(root, mode="r") as repository:
        reopened = repository.datasets.get(dataset_id)
        assert reopened.verify() is False
        with pytest.raises(DatasetError):
            reopened.open("source:example")
    assert (root / "metadata.sqlite").read_bytes() == metadata_before


def test_public_export_rejects_unsafe_collision_and_destination_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    adapter = SequencedHttpAdapter((b"payload",))
    with Repository.create(root) as repository:
        _sync_http(repository, adapter, _http_source())
        dataset = repository.datasets.freeze(DatasetSpec.latest("source:example"))

        with pytest.raises(ExportError, match="Unsafe logical export path"):
            dataset.export(tmp_path / "escape", paths={"source:example": "../escape"}, strategy="copy")
        with pytest.raises(ExportError, match="Unsafe logical export path"):
            dataset.export(tmp_path / "dot", paths={"source:example": "."}, strategy="copy")
        with pytest.raises(ExportError, match="collision"):
            dataset.export(
                tmp_path / "collision",
                paths={"source:example": "dataset-manifest.json"},
                strategy="copy",
            )

        destination = tmp_path / "raced"
        publish = materialization_module._publish_directory

        def race(staging: Path, target: Path) -> None:
            target.mkdir()
            (target / "keep").write_bytes(b"other writer")
            publish(staging, target)

        monkeypatch.setattr(materialization_module, "_publish_directory", race)
        with pytest.raises(ExportError):
            dataset.export(destination, strategy="copy")
        assert (destination / "keep").read_bytes() == b"other writer"
        assert not (destination / "dataset-manifest.json").exists()


def test_exported_symlinks_are_private_and_cannot_mutate_repository_content(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    destination = tmp_path / "export"
    adapter = SequencedHttpAdapter((b"payload",))
    with Repository.create(root) as repository:
        _sync_http(repository, adapter, _http_source())
        dataset = repository.datasets.freeze(DatasetSpec.latest("source:example"))
        manifest = dataset.export(destination, strategy="symlink")
        member_path = json.loads(manifest.to_bytes())["members"][0]["path"]
        exported = destination / member_path
        assert exported.is_symlink()
        resolved = exported.resolve(strict=True)
        assert resolved.is_relative_to((destination / ".content").resolve(strict=True))
        exported.write_bytes(b"changed export")
        assert manifest.verify(destination) is False
        assert dataset.verify()
        with dataset.open("source:example") as stream:
            assert stream.read() == b"payload"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-specific renameat2 acceptance")
def test_linux_atomic_no_replace_publication_preserves_existing_destination(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    destination = tmp_path / "destination"
    staging.mkdir()
    destination.mkdir()
    (staging / "new").write_bytes(b"new")
    (destination / "keep").write_bytes(b"old")

    with pytest.raises(FileExistsError):
        materialization_module._publish_directory(staging, destination)

    assert (staging / "new").read_bytes() == b"new"
    assert (destination / "keep").read_bytes() == b"old"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-specific FICLONE acceptance")
def test_linux_reflink_path_invokes_ficlone_without_copy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"reflink payload")
    calls: list[tuple[int, int, int]] = []

    def emulate_ficlone(output_fd: int, request: int, input_fd: int) -> int:
        calls.append((output_fd, request, input_fd))
        os.lseek(input_fd, 0, os.SEEK_SET)
        os.write(output_fd, os.read(input_fd, 1024))
        return 0

    monkeypatch.setattr(materialization_module.fcntl, "ioctl", emulate_ficlone)
    with source.open("rb") as stream:
        materialization_module._clone(stream, destination)

    assert len(calls) == 1
    assert calls[0][1] == 0x40049409
    assert destination.read_bytes() == b"reflink payload"


def test_linux_native_reflink_public_export_on_required_cow_filesystem() -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux-specific native reflink acceptance")
    configured = os.environ.get("EFLOUD_NATIVE_COW_TEST_ROOT")
    if configured is None:
        pytest.skip("dedicated reflink-capable filesystem was not requested")
    workspace = Path(configured) / f"efloud-acceptance-{os.getpid()}"
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir()
    try:
        adapter = SequencedHttpAdapter((b"native reflink payload",))
        with Repository.create(workspace / "repository") as repository:
            _sync_http(repository, adapter, _http_source())
            dataset = repository.datasets.freeze(DatasetSpec.latest("source:example"))
            manifest = dataset.export(workspace / "export", strategy="reflink")
            assert manifest.verify(workspace / "export")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_generic_standard_library_consumer_validates_manifest_and_bytes(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    destination = tmp_path / "export"
    adapter = SequencedHttpAdapter((b"payload",))
    with Repository.create(root) as repository:
        _sync_http(repository, adapter, _http_source(role="reference"))
        dataset = repository.datasets.freeze(DatasetSpec.latest_source_snapshot("example"))
        manifest = dataset.export(destination, paths={"source:example": "catalog/example.bin"}, strategy="copy")

    script = r"""
import hashlib
import json
import sys
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def stable(prefix, value):
    return prefix + ":" + hashlib.sha256(canonical(value)).hexdigest()


root = Path(sys.argv[1]).resolve(strict=True)
manifest = json.loads((root / "dataset-manifest.json").read_bytes())
manifest_id = manifest.pop("manifest_id")
assert manifest_id == stable("dataset-manifest-v1", manifest)
assert manifest["version"] == 1
assert manifest["specification_id"] == stable("dataset-specification", manifest["definition"])
exact = [
    {"artifact_key": item["artifact_key"], "observation_id": item["observation_id"], "role": item["role"]}
    for item in manifest["members"]
]
content = [
    {"artifact_key": item["artifact_key"], "content_id": item["content_id"], "role": item["role"]}
    for item in manifest["members"]
]
assert manifest["dataset_id"] == stable("dataset", exact)
assert manifest["content_identity"] == stable("dataset-content", content)
for member in manifest["members"]:
    path = (root / member["path"]).resolve(strict=True)
    assert path.is_relative_to(root)
    data = path.read_bytes()
    assert len(data) == member["byte_size"]
    assert "sha256:" + hashlib.sha256(data).hexdigest() == member["content_id"]
    observation = member["observation"]
    obs_payload = {
        "kind": "content",
        "artifact_key": member["artifact_key"],
        "content_id": member["content_id"],
        "run_id": observation["run_id"],
        "operation_id": observation["operation_id"],
        "observed_at": observation["observed_at"],
        "source_path": observation.get("source_path"),
        "upstream_locator": observation.get("upstream_locator"),
    }
    assert member["observation_id"] == stable("obs", obs_payload)
    revision = member["source_revision"]
    if revision is not None:
        revision_payload = {"source_id": observation["source_id"], "definition": revision["definition"]}
        assert revision["revision_id"] == stable("source-definition", revision_payload)
assert manifest["resolution"]["snapshots"][0]["complete"] is True
print(manifest["dataset_id"])
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(destination)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == manifest.dataset_id
