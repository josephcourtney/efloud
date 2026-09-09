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
    CollectionAcquisition,
    CollectionItemAcquisition,
    HttpAcquisition,
)
from efloud.collection_recording import record_collection_acquisition
from efloud.engine import Engine
from efloud.inventory import (
    IntegrityExpectation,
    InventoryCoverage,
    InventoryItem,
    SourceInventory,
)
from efloud.repository import Repository
from efloud.repository_models import ArtifactKey, ContentId, SourceId
from efloud.sources import HttpSource, RestSource
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

pytestmark = [
    pytest.mark.unit,
    pytest.mark.db,
    pytest.mark.regression,
    pytest.mark.medium,
]


@dataclass
class CountingValidator:
    descriptor: ValidatorDescriptor
    calls: int = 0

    def applies_to(self, target: ValidationTarget) -> bool:
        del target
        return True

    def validate(
        self,
        target: ValidationTarget,
        stream: BinaryIO,
    ) -> ValidationOutcome:
        del target
        self.calls += 1
        assert stream.read() == b"payload"
        return ValidationOutcome(
            status="passed",
            details={"fixture": True},
        )


@dataclass(frozen=True, slots=True)
class FixtureHttpAdapter:
    descriptor: AdapterDescriptor
    destination: Path
    media_type: str | None = None
    propagate_expectations: bool = True

    async def acquire(
        self,
        context: AdapterExecutionContext,
    ) -> HttpAcquisition:
        await asyncio.sleep(0)

        source = context.source
        if not isinstance(source, HttpSource | RestSource):
            msg = f"Fixture HTTP adapter cannot acquire {type(source).__name__}."
            raise TypeError(msg)

        expectations = source.expected_integrity if self.propagate_expectations else ()

        return HttpAcquisition(
            source_id=source.id,
            status="succeeded",
            destination=self.destination,
            observed_at=100.0,
            status_code=200,
            media_type=self.media_type,
            expected_integrity=expectations,
        )


def _adapter(
    adapter_id: str,
    destination: Path,
    *,
    media_type: str | None = None,
    propagate_expectations: bool = True,
) -> FixtureHttpAdapter:
    return FixtureHttpAdapter(
        descriptor=AdapterDescriptor(
            adapter_id=adapter_id,
            version="1",
            capabilities=AdapterCapabilities(
                inventory=False,
                fetch=True,
            ),
        ),
        destination=destination,
        media_type=media_type,
        propagate_expectations=propagate_expectations,
    )


def test_validation_reuses_content_and_validator_version_evidence(
    tmp_path: Path,
) -> None:
    version_one = CountingValidator(ValidatorDescriptor("test:domain", "1"))

    with Repository(tmp_path) as repository:
        content = repository.store_bytes_content(
            b"payload",
            media_type="application/octet-stream",
        )
        service = ValidationService(
            repository,
            ValidationRegistry((version_one,)),
        )

        first = service.validate_content(
            content,
            checked_at=100.0,
        )
        second = service.validate_content(
            content,
            checked_at=200.0,
        )

        assert first.ok
        assert second.ok
        assert version_one.calls == 1
        assert first.checks[0].reused is False
        assert second.checks[0].reused is True
        assert second.checks[0].result.checked_at == pytest.approx(100.0)

        version_two = CountingValidator(ValidatorDescriptor("test:domain", "2"))
        third = ValidationService(
            repository,
            ValidationRegistry((version_two,)),
        ).validate_content(
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


def test_required_http_integrity_failure_does_not_advance_source(
    tmp_path: Path,
) -> None:
    payload = b"actual bytes"
    destination = tmp_path / "download.bin"
    destination.write_bytes(payload)

    wrong_digest = "0" * 64
    source = HttpSource(
        id="bad",
        description="Bad integrity",
        url="https://example.test/download.bin",
        expected_integrity=(IntegrityExpectation.sha256(wrong_digest),),
    )

    adapters = AdapterRegistry((
        _adapter(
            source.adapter_id,
            destination,
            propagate_expectations=False,
        ),
    ))

    with Repository(tmp_path) as repository:
        engine = Engine(
            repository,
            (source,),
            adapters=adapters,
        )
        result = asyncio.run(engine.sync())

        assert result.ok is False
        assert repository.latest_observation("source:bad") is None
        assert repository.latest_source_snapshot("bad") is None

        actual_id = ContentId(f"sha256:{hashlib.sha256(payload).hexdigest()}")
        content = repository.content(actual_id)

        assert content is not None

        with repository.open_content(actual_id) as stream:
            assert stream.read() == payload

        validations = repository.validations_for(actual_id)
        statuses = {item.validator: item.status for item in validations}

        assert statuses["efloud:storage-integrity"] == "passed"
        assert statuses[f"efloud:source-integrity:sha256:{wrong_digest}"] == "failed"
        assert result.execution.operations[0].details["content_id"] == str(actual_id)

        source_record = repository.source(SourceId("bad"))
        assert source_record is not None
        assert source_record.definition["expected_integrity"] == [source.expected_integrity[0].to_dict()]


def test_invalid_json_fails_validation_without_mutating_content(
    tmp_path: Path,
) -> None:
    payload = b"{not valid json"
    destination = tmp_path / "invalid.json"
    destination.write_bytes(payload)

    source = RestSource(
        id="json",
        description="JSON",
        url="https://example.test/invalid.json",
    )

    adapters = AdapterRegistry((
        _adapter(
            source.adapter_id,
            destination,
            media_type="application/json",
        ),
    ))

    with Repository(tmp_path) as repository:
        engine = Engine(
            repository,
            (source,),
            adapters=adapters,
        )
        result = asyncio.run(engine.sync())

        actual_id = ContentId(f"sha256:{hashlib.sha256(payload).hexdigest()}")

        assert result.ok is False
        assert repository.latest_observation("source:json") is None
        assert repository.latest_source_snapshot("json") is None

        json_validation = repository.validation(
            actual_id,
            "efloud:json",
            "1",
        )
        assert json_validation is not None
        assert json_validation.status == "failed"

        with repository.open_content(actual_id) as stream:
            assert stream.read() == payload


def test_invalid_gzip_is_reusable_validation_evidence(
    tmp_path: Path,
) -> None:
    payload = gzip.compress(b"payload")[:-4]

    with Repository(tmp_path) as repository:
        content = repository.store_bytes_content(
            payload,
            media_type="application/gzip",
        )
        service = ValidationService(
            repository,
            builtin_validation_registry(),
        )

        first = service.validate_content(
            content,
            name="payload.gz",
            checked_at=100.0,
        )
        second = service.validate_content(
            content,
            name="payload.gz",
            checked_at=200.0,
        )

        assert first.ok is False
        assert second.ok is False

        gzip_first = next(check for check in first.checks if check.result.validator == "efloud:gzip")
        gzip_second = next(check for check in second.checks if check.result.validator == "efloud:gzip")

        assert gzip_first.result.status == "failed"
        assert gzip_first.reused is False
        assert gzip_second.reused is True

        with repository.open_content(content.content_id) as stream:
            assert stream.read() == payload


def test_collection_item_integrity_failure_is_unresolved_not_observed(
    tmp_path: Path,
) -> None:
    item_path = tmp_path / "item.json"
    item_path.write_text(
        '{"id":"alpha"}',
        encoding="utf-8",
    )

    wrong_digest = "f" * 64
    source_id = SourceId("collection")

    inventory = SourceInventory(
        source_id=source_id,
        observed_at=100.0,
        coverage=InventoryCoverage(
            complete=True,
        ),
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

    acquisition = CollectionAcquisition(
        source_id=str(source_id),
        status="succeeded",
        observed_at=100.0,
        inventory=inventory,
        items=(
            CollectionItemAcquisition(
                item_id="alpha",
                status="ok",
                destination=item_path,
            ),
        ),
        media_type="application/json",
    )

    with Repository(tmp_path) as repository:
        repository.register_source(
            source_id,
            {
                "adapter_id": "efloud:collection",
                "protocol": "collection",
            },
        )

        run_id = repository.start_run(
            source_ids=(source_id,),
            started_at=90.0,
        )
        operation_id = repository.start_operation(
            run_id=run_id,
            source_id=source_id,
            kind="collection",
            subject="fanout",
            started_at=91.0,
        )

        result = record_collection_acquisition(
            repository,
            ValidationService(
                repository,
                builtin_validation_registry(),
            ),
            acquisition=acquisition,
            run_id=run_id,
            operation_id=operation_id,
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
