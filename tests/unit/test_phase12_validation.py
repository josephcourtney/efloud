from __future__ import annotations

import asyncio
import gzip
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from efloud.adapters import (
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterExecutionContext,
    AdapterRegistry,
    HttpAcquisition,
)
from efloud.collection_recording import record_collection_acquisition
from efloud.engine import Engine
from efloud.inventory import IntegrityExpectation, InventoryCoverage, InventoryItem, SourceInventory
from efloud.registry import SourceDefinition, SourceKind
from efloud.repository import Repository
from efloud.repository_models import ArtifactKey, ContentId, SourceId
from efloud.repository_query import RepositoryQueryService
from efloud.validation import (
    ValidationOutcome,
    ValidationRegistry,
    ValidationService,
    ValidationTarget,
    ValidatorDescriptor,
    builtin_validation_registry,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

    from efloud.json_types import JsonObject

pytestmark = [pytest.mark.unit, pytest.mark.db, pytest.mark.regression, pytest.mark.medium]


@dataclass
class CountingValidator:
    descriptor: ValidatorDescriptor
    calls: int = 0

    def applies_to(self, target: ValidationTarget) -> bool:
        del target
        return True

    def validate(self, target: ValidationTarget, stream: BinaryIO) -> ValidationOutcome:
        del target
        self.calls += 1
        assert stream.read() == b"payload"
        return ValidationOutcome(status="passed", details={"fixture": True})


@dataclass(frozen=True, slots=True)
class FixtureHttpAdapter:
    descriptor: AdapterDescriptor
    destination: Path
    media_type: str | None = None
    propagate_expectations: bool = True

    async def acquire(self, context: AdapterExecutionContext) -> HttpAcquisition:
        await asyncio.sleep(0)
        expectations = context.source.expected_integrity if self.propagate_expectations else ()
        return HttpAcquisition(
            source_id=context.source.id,
            status="succeeded",
            destination=self.destination,
            observed_at=100.0,
            status_code=200,
            media_type=self.media_type,
            expected_integrity=expectations,
        )


def _adapter(
    kind: SourceKind,
    destination: Path,
    *,
    media_type: str | None = None,
    propagate_expectations: bool = True,
) -> FixtureHttpAdapter:
    return FixtureHttpAdapter(
        descriptor=AdapterDescriptor(
            adapter_id=f"test:{kind.value.lower()}",
            version="1",
            source_kinds=(kind,),
            capabilities=AdapterCapabilities(inventory=False, fetch=True),
        ),
        destination=destination,
        media_type=media_type,
        propagate_expectations=propagate_expectations,
    )


def test_validation_reuses_content_and_validator_version_evidence(tmp_path: Path) -> None:
    version_one = CountingValidator(ValidatorDescriptor("test:domain", "1"))
    with Repository(tmp_path) as repository:
        content = repository.store_bytes_content(b"payload", media_type="application/octet-stream")
        service = ValidationService(repository, ValidationRegistry((version_one,)))

        first = service.validate_content(content, checked_at=100.0)
        second = service.validate_content(content, checked_at=200.0)

        assert first.ok
        assert second.ok
        assert version_one.calls == 1
        assert first.checks[0].reused is False
        assert second.checks[0].reused is True
        assert second.checks[0].result.checked_at == pytest.approx(100.0)

        version_two = CountingValidator(ValidatorDescriptor("test:domain", "2"))
        third = ValidationService(repository, ValidationRegistry((version_two,))).validate_content(
            content,
            checked_at=300.0,
        )
        assert third.ok
        assert version_two.calls == 1
        assert third.checks[0].reused is False

        validations = repository.validations_for(content.content_id)
        assert [(item.validator, item.validator_version) for item in validations] == [
            ("test:domain", "1"),
            ("test:domain", "2"),
        ]
        payload = RepositoryQueryService(repository).query(f"content:{content.content_id}")
        assert payload["available"] is True
        serialized_validations = payload["validations"]
        assert isinstance(serialized_validations, list)
        assert len(serialized_validations) == 2


def test_required_http_integrity_failure_does_not_advance_source(tmp_path: Path) -> None:
    payload = b"actual bytes"
    destination = tmp_path / "download.bin"
    destination.write_bytes(payload)
    wrong_digest = "0" * 64
    source = SourceDefinition(
        "bad",
        "Bad integrity",
        "https://example.test/download.bin",
        SourceKind.HTTP,
        expected_integrity=(IntegrityExpectation.sha256(wrong_digest),),
    )
    adapters = AdapterRegistry((_adapter(SourceKind.HTTP, destination, propagate_expectations=False),))

    with Engine(tmp_path, [source], adapters=adapters) as engine:
        result = asyncio.run(engine.sync())
        assert result.ok is False
        assert engine.repository.latest_observation("source:bad") is None
        assert engine.repository.latest_source_snapshot("bad") is None

        actual_id = ContentId(f"sha256:{hashlib.sha256(payload).hexdigest()}")
        content = engine.repository.content(actual_id)
        assert content is not None
        with engine.repository.open_content(actual_id) as stream:
            assert stream.read() == payload

        validations = engine.repository.validations_for(actual_id)
        statuses = {item.validator: item.status for item in validations}
        assert statuses["efloud:storage-integrity"] == "passed"
        assert statuses[f"efloud:source-integrity:sha256:{wrong_digest}"] == "failed"
        assert result.execution.operations[0].details["content_id"] == str(actual_id)

        source_record = engine.repository.metadata.source(SourceId("bad"))
        assert source_record is not None
        assert source_record.definition["expected_integrity"] == [source.expected_integrity[0].to_dict()]


def test_invalid_json_fails_validation_without_mutating_content(tmp_path: Path) -> None:
    payload = b"{not valid json"
    destination = tmp_path / "invalid.json"
    destination.write_bytes(payload)
    source = SourceDefinition(
        "json",
        "JSON",
        "https://example.test/invalid.json",
        SourceKind.REST,
    )
    adapters = AdapterRegistry((_adapter(SourceKind.REST, destination, media_type="application/json"),))

    with Engine(tmp_path, [source], adapters=adapters) as engine:
        result = asyncio.run(engine.sync())
        actual_id = ContentId(f"sha256:{hashlib.sha256(payload).hexdigest()}")

        assert result.ok is False
        assert engine.repository.latest_observation("source:json") is None
        assert engine.repository.latest_source_snapshot("json") is None
        json_validation = engine.repository.validation(actual_id, "efloud:json", "1")
        assert json_validation is not None
        assert json_validation.status == "failed"
        with engine.repository.open_content(actual_id) as stream:
            assert stream.read() == payload


def test_invalid_gzip_is_reusable_validation_evidence(tmp_path: Path) -> None:
    payload = gzip.compress(b"payload")[:-4]
    with Repository(tmp_path) as repository:
        content = repository.store_bytes_content(payload, media_type="application/gzip")
        service = ValidationService(repository, builtin_validation_registry())
        first = service.validate_content(content, name="payload.gz", checked_at=100.0)
        second = service.validate_content(content, name="payload.gz", checked_at=200.0)

        assert first.ok is False
        assert second.ok is False
        gzip_first = next(check for check in first.checks if check.result.validator == "efloud:gzip")
        gzip_second = next(check for check in second.checks if check.result.validator == "efloud:gzip")
        assert gzip_first.result.status == "failed"
        assert gzip_first.reused is False
        assert gzip_second.reused is True
        with repository.open_content(content.content_id) as stream:
            assert stream.read() == payload


def test_collection_item_integrity_failure_is_unresolved_not_observed(tmp_path: Path) -> None:
    item_path = tmp_path / "item.json"
    item_path.write_text('{"id":"alpha"}', encoding="utf-8")
    wrong_digest = "f" * 64
    source_id = SourceId("collection")
    inventory = SourceInventory(
        source_id=source_id,
        observed_at=100.0,
        coverage=InventoryCoverage(complete=True),
        items=(
            InventoryItem(
                item_id="alpha",
                artifact_key=ArtifactKey("source:collection:item:alpha"),
                locator="https://example.test/items/alpha",
                source_path="alpha.json",
                expected_integrity=(IntegrityExpectation.sha256(wrong_digest),),
            ),
        ),
    )
    payload: JsonObject = {
        "request": {"response_mode": "json"},
        "inventory": inventory.to_dict(),
        "entries": {
            "alpha": {
                "status": "ok",
                "item_id": "alpha",
                "dest": str(item_path),
                "request": {"fanout_path": "alpha.json"},
                "metadata": {},
            }
        },
        "ok": 1,
        "err": 0,
    }

    with Repository(tmp_path) as repository:
        repository.register_source(source_id, {"kind": SourceKind.REST_BASE.value})
        run_id = repository.start_run(source_ids=(source_id,), started_at=90.0)
        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source_id,
            kind="collection",
            subject="fanout",
            started_at=91.0,
        )
        result = record_collection_acquisition(
            repository,
            ValidationService(repository, builtin_validation_registry()),
            source_id=source_id,
            task_name="fanout",
            payload=payload,
            run_id=run_id,
            operation_id=operation_id,
            observed_at=100.0,
        )

        assert result.unresolved_count == 1
        assert result.content_count == 0
        assert repository.latest_observation("source:collection:item:alpha") is None
        snapshot = repository.latest_source_snapshot(source_id)
        assert snapshot is not None
        assert snapshot.complete is False
        assert snapshot.tree_id is not None
        entry = repository.tree_entries(snapshot.tree_id)[0]
        assert entry.kind == "unresolved"
        assert entry.content_id is not None
        expectation = repository.validation(
            entry.content_id,
            f"efloud:source-integrity:sha256:{wrong_digest}",
            "1",
        )
        assert expectation is not None
        assert expectation.status == "failed"
