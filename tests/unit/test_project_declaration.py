from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from efloud import Repository
from efloud.collections import CollectionDefinition, CollectionInventory
from efloud.lockfile import LockfileError, ProjectLock, SignaturePolicy
from efloud.project import (
    CollectionProvider,
    DeclaredSource,
    Project,
    ProjectError,
    ProjectSchemaError,
    ProviderResolutionError,
)
from efloud.sources import CollectionSource, LocalSource

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


PROJECT_TOML = """
schema_version = 1

[sync]
include_derived = true
dry_run = false
max_concurrency = 3
refresh = false
refresh_source_ids = []

[[sources]]
id = "analysis-input"
adapter = "efloud:local"
adapter_version = "1"
role = "analysis-input"
tags = ["configuration"]

[sources.config]
path = "inputs/analysis.json"
artifact_key = "analysis:input"
media_type = "application/json"

[[datasets]]
name = "analysis"
metadata = { purpose = "test" }
constraints = { complete_snapshots = true }

[[datasets.selections]]
kind = "latest"
artifact_key = "analysis:input"
role = "configuration"
"""


@dataclass
class EmptyCollectionProvider:
    provider_id: str = "test:empty-collection"
    version: str = "2"
    seen_parameters: dict[str, object] | None = None

    def build(
        self,
        *,
        source: CollectionSource,
        parameters: dict[str, object],
        base_dir: Path,
    ) -> CollectionDefinition:
        self.seen_parameters = dict(parameters)
        assert base_dir.is_absolute()

        async def enumerate_empty(*, context: object) -> CollectionInventory:
            del context
            return CollectionInventory((), complete=True, upstream_identity="empty")

        return CollectionDefinition(source_id=source.id, enumerator=enumerate_empty)


def test_project_round_trips_semantic_toml_and_anchors_local_paths(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project = Project.from_toml(PROJECT_TOML, base_dir=project_dir)

    assert project.declaration_id == Project.from_toml(project.to_toml(), base_dir=project_dir).declaration_id
    assert project.sync_request.max_concurrency == 3
    assert project.dataset("analysis")._definition().to_dict() == {  # noqa: SLF001 - verifies public model parity.
        "selections": [{"kind": "latest", "artifact_key": "analysis:input", "role": "configuration"}],
        "metadata": {"purpose": "test"},
        "constraints": {
            "same_run": False,
            "max_observation_skew": None,
            "complete_snapshots": True,
            "validations": [],
        },
    }

    sources, collections = project.materialize()
    assert collections == ()
    assert len(sources) == 1
    source = sources[0]
    assert isinstance(source, LocalSource)
    assert Path(source.path) == (project_dir / "inputs" / "analysis.json").resolve()


def test_project_file_path_resolution_is_independent_of_process_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    declaration = project_dir / "efloud.toml"
    declaration.write_text(PROJECT_TOML, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    project = Project.load(declaration)
    sources, _ = project.materialize()
    source = sources[0]
    assert isinstance(source, LocalSource)
    assert Path(source.path) == (project_dir / "inputs" / "analysis.json").resolve()


def test_project_rejects_unknown_and_historical_schema() -> None:
    with pytest.raises(ProjectSchemaError, match="schema version"):
        Project.from_toml("schema_version = 0\n")
    with pytest.raises(ProjectSchemaError, match="Unsupported project keys"):
        Project.from_toml("schema_version = 1\nunknown = true\n")


def test_unknown_namespaced_adapter_remains_open_declarative_source() -> None:
    project = Project.from_toml(
        """
        schema_version = 1
        [[sources]]
        id = "custom"
        adapter = "example:custom"
        [sources.config]
        endpoint = "urn:example"
        """
    )
    sources, _ = project.materialize()
    assert len(sources) == 1
    source = sources[0]
    assert isinstance(source, DeclaredSource)
    assert source.adapter_id == "example:custom"
    assert source.definition()["endpoint"] == "urn:example"


def test_collection_provider_is_declarative_versioned_and_not_serialized_as_callback(tmp_path: Path) -> None:
    project = Project.from_toml(
        """
        schema_version = 1
        [[sources]]
        id = "entries"
        adapter = "efloud:collection"
        [sources.config]
        url = "https://example.invalid/entry"
        [sources.provider]
        id = "test:empty-collection"
        version = "2"
        parameters = { holdings_source = "holdings" }
        """,
        base_dir=tmp_path,
    )
    provider = EmptyCollectionProvider()
    providers: dict[str, CollectionProvider] = {provider.provider_id: provider}
    sources, collections = project.materialize(providers=providers)

    assert len(collections) == 1
    assert provider.seen_parameters == {"holdings_source": "holdings"}
    source = sources[0]
    assert isinstance(source, CollectionSource)
    assert "provider" not in source.definition()
    assert source.definition()["url"] == "https://example.invalid/entry"
    serialized = project.to_toml()
    assert "test:empty-collection" in serialized
    assert "callback" not in serialized


def test_collection_provider_version_mismatch_fails_closed() -> None:
    project = Project.from_toml(
        """
        schema_version = 1
        [[sources]]
        id = "entries"
        adapter = "efloud:collection"
        [sources.config]
        url = "https://example.invalid/entry"
        [sources.provider]
        id = "test:empty-collection"
        version = "999"
        """
    )
    provider = EmptyCollectionProvider()
    with pytest.raises(ProviderResolutionError, match="version mismatch"):
        project.materialize(providers={provider.provider_id: provider})


def test_dataset_declaration_accepts_all_selector_shapes_and_normalizes_time() -> None:
    project = Project.from_toml(
        """
        schema_version = 1
        [[datasets]]
        name = "all-selectors"
        constraints = { same_run = true, max_observation_skew = 15.5, validations = [["v", "1"]] }
        [[datasets.selections]]
        kind = "exact"
        observation_id = "obs:1"
        [[datasets.selections]]
        kind = "latest"
        artifact_key = "a"
        [[datasets.selections]]
        kind = "latest-before"
        artifact_key = "b"
        timestamp = 2026-09-10T12:00:00Z
        [[datasets.selections]]
        kind = "latest-all"
        before = "2026-09-10T12:00:00+00:00"
        [[datasets.selections]]
        kind = "source-selection"
        source_id = "source"
        role_filter = "catalog"
        tags = ["x"]
        prefix = "source:"
        after = 0.0
        before = 1.0
        role = "member"
        [[datasets.selections]]
        kind = "source-snapshot"
        snapshot_id = "snapshot:1"
        [[datasets.selections]]
        kind = "latest-complete-source-snapshot"
        source_id = "source"
        """
    )
    definition = project.datasets[0].to_dict()
    selections = definition["selections"]
    assert isinstance(selections, list)
    assert selections[2]["timestamp"] == 1789041600.0
    assert selections[3]["before"] == 1789041600.0
    assert Project.from_toml(project.to_toml()).datasets[0].specification_id == project.datasets[0].specification_id


def test_project_sync_lock_roundtrip_and_detached_source_resolution(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    input_dir = project_dir / "inputs"
    input_dir.mkdir(parents=True)
    input_path = input_dir / "analysis.json"
    input_path.write_bytes(b'{"value": 1}\n')
    declaration_path = project_dir / "efloud.toml"
    declaration_path.write_text(PROJECT_TOML, encoding="utf-8")
    project = Project.load(declaration_path)

    repository_root = tmp_path / "repository"
    with Repository.create(repository_root) as repository:
        result = asyncio.run(project.sync(repository))
        assert result.ok
        lock = project.lock(repository)

    assert lock.complete
    assert lock.declaration_id == project.declaration_id
    assert len(lock.sources) == 1
    assert lock.sources[0]["adapter"] == {"id": "efloud:local", "version": "1"}
    source_resolution = lock.sources[0]["resolution"]
    assert isinstance(source_resolution, dict)
    members = source_resolution["members"]
    assert isinstance(members, list)
    assert members[0]["artifact_key"] == "analysis:input"
    assert len(lock.datasets) == 1
    assert lock.datasets[0]["name"] == "analysis"

    lock_path = tmp_path / "efloud.lock"
    lock.write(lock_path)
    loaded = ProjectLock.load(lock_path)
    assert loaded.lock_id == lock.lock_id
    assert loaded.to_bytes() == lock.to_bytes()


def test_lock_detects_tampering() -> None:
    lock = ProjectLock.create(
        declaration={"schema_version": 1, "sync": {}, "sources": [], "datasets": []},
        sources=(),
        datasets=(),
    )
    payload = json.loads(lock.to_bytes())
    payload["declaration_id"] = "damaged"
    with pytest.raises(LockfileError, match="declaration identity"):
        ProjectLock.from_bytes(json.dumps(payload).encode())


def test_lock_ed25519_signature_uses_external_trust_key() -> None:
    lock = ProjectLock.create(
        declaration={"schema_version": 1, "sync": {}, "sources": [], "datasets": []},
        sources=(),
        datasets=(),
    )
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    signed = lock.sign_ed25519(private_raw, key_id="release")
    required = SignaturePolicy(require_signed=True, required_key_ids=("release",))

    assert signed.lock_id == lock.lock_id
    assert signed.verify_signatures({"release": public_raw}, policy=required)
    assert not signed.verify_signatures({}, policy=required)
    other = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    assert not signed.verify_signatures({"release": other}, policy=required)
    assert ProjectLock.from_bytes(signed.to_bytes()).verify_signatures({"release": public_raw}, policy=required)


def test_lock_requires_current_source_definition_and_complete_snapshot(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    inputs = project_dir / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "analysis.json").write_text("{}", encoding="utf-8")
    project = Project.from_toml(PROJECT_TOML, base_dir=project_dir)

    with Repository.create(tmp_path / "repository") as repository:
        with pytest.raises(ProjectError, match="current definition|no resolved snapshot"):
            project.lock(repository)
