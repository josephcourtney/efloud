from __future__ import annotations

import gzip
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from efloud.repository_models import ValidationResult, ValidationStatus

if TYPE_CHECKING:
    from typing import BinaryIO

    from efloud.inventory import IntegrityExpectation
    from efloud.json_types import JsonArray, JsonObject
    from efloud.repository import Repository
    from efloud.repository_models import ContentRef


@dataclass(frozen=True, slots=True)
class ValidatorDescriptor:
    """Stable identity/version and advancement policy for one validator."""

    validator_id: str
    version: str
    required: bool = True

    def __post_init__(self) -> None:
        """Reject invalid validator identities and empty versions."""
        namespace, separator, name = self.validator_id.partition(":")
        if not namespace or not separator or not name:
            msg = f"Validator identifiers must be namespaced: {self.validator_id!r}"
            raise ValueError(msg)
        if not self.version:
            msg = "Validator version must not be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ValidationTarget:
    """Semantic content plus optional source-facing name used for applicability."""

    content: ContentRef
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    status: ValidationStatus
    details: JsonObject = field(default_factory=dict)


class ContentValidator(Protocol):
    @property
    def descriptor(self) -> ValidatorDescriptor: ...

    def applies_to(self, target: ValidationTarget) -> bool: ...

    def validate(self, target: ValidationTarget, stream: BinaryIO) -> ValidationOutcome: ...


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    result: ValidationResult
    required: bool
    reused: bool

    def to_dict(self) -> JsonObject:
        payload = self.result.to_dict()
        payload["required"] = self.required
        payload["reused"] = self.reused
        return payload


@dataclass(frozen=True, slots=True)
class ValidationBatch:
    checks: tuple[ValidationCheck, ...]

    @property
    def ok(self) -> bool:
        return all(not check.required or check.result.status == "passed" for check in self.checks)

    def to_dict(self) -> JsonObject:
        serialized: JsonArray = []
        serialized.extend(check.to_dict() for check in self.checks)
        return {"ok": self.ok, "checks": serialized}


class ValidationRegistry:
    """Direct registry of active content validators keyed by stable identity."""

    def __init__(self, validators: tuple[ContentValidator, ...] = ()) -> None:
        self._validators: dict[str, ContentValidator] = {}
        for validator in validators:
            self.register(validator)

    def register(self, validator: ContentValidator) -> None:
        validator_id = validator.descriptor.validator_id
        if validator_id in self._validators:
            msg = f"Validator already registered: {validator_id!r}"
            raise ValueError(msg)
        self._validators[validator_id] = validator

    def applicable(self, target: ValidationTarget) -> tuple[ContentValidator, ...]:
        return tuple(validator for validator in self._validators.values() if validator.applies_to(target))

    def descriptors(self) -> tuple[ValidatorDescriptor, ...]:
        return tuple(
            validator.descriptor
            for validator in sorted(
                self._validators.values(),
                key=lambda item: item.descriptor.validator_id,
            )
        )


@dataclass(frozen=True, slots=True)
class StorageIntegrityValidator:
    descriptor: ValidatorDescriptor = ValidatorDescriptor(
        validator_id="efloud:storage-integrity",
        version="1",
        required=True,
    )

    @staticmethod
    def applies_to(target: ValidationTarget) -> bool:
        del target
        return True

    @staticmethod
    def validate(target: ValidationTarget, stream: BinaryIO) -> ValidationOutcome:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        actual = f"sha256:{digest.hexdigest()}"
        expected = str(target.content.content_id)
        return ValidationOutcome(
            status="passed" if actual == expected else "failed",
            details={"expected_content_id": expected, "actual_content_id": actual},
        )


@dataclass(frozen=True, slots=True)
class GzipValidator:
    descriptor: ValidatorDescriptor = ValidatorDescriptor(
        validator_id="efloud:gzip",
        version="1",
        required=True,
    )

    @staticmethod
    def applies_to(target: ValidationTarget) -> bool:
        media_type = (target.content.media_type or "").lower()
        name = (target.name or "").lower()
        return media_type in {"application/gzip", "application/x-gzip"} or name.endswith(".gz")

    @staticmethod
    def validate(target: ValidationTarget, stream: BinaryIO) -> ValidationOutcome:
        del target
        try:
            with gzip.GzipFile(fileobj=stream, mode="rb") as archive:
                for _chunk in iter(lambda: archive.read(1024 * 1024), b""):
                    pass
        except (EOFError, OSError) as exc:
            return ValidationOutcome(status="failed", details={"error": f"{type(exc).__name__}: {exc}"})
        return ValidationOutcome(status="passed")


@dataclass(frozen=True, slots=True)
class JsonValidator:
    descriptor: ValidatorDescriptor = ValidatorDescriptor(
        validator_id="efloud:json",
        version="1",
        required=True,
    )

    @staticmethod
    def applies_to(target: ValidationTarget) -> bool:
        media_type = (target.content.media_type or "").lower()
        name = (target.name or "").lower()
        return "json" in media_type or name.endswith((".json", ".json.gz"))

    @staticmethod
    def validate(target: ValidationTarget, stream: BinaryIO) -> ValidationOutcome:
        try:
            data = stream.read()
            if (target.name or "").lower().endswith(".gz"):
                data = gzip.decompress(data)
            decoded = json.loads(data)
        except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return ValidationOutcome(status="failed", details={"error": f"{type(exc).__name__}: {exc}"})
        return ValidationOutcome(status="passed", details={"json_type": type(decoded).__name__})


@dataclass(frozen=True, slots=True)
class IntegrityExpectationValidator:
    expectation: IntegrityExpectation

    @property
    def descriptor(self) -> ValidatorDescriptor:
        algorithm = self.expectation.algorithm.lower()
        digest = self.expectation.digest.lower()
        return ValidatorDescriptor(
            validator_id=f"efloud:source-integrity:{algorithm}:{digest}",
            version="1",
            required=self.expectation.required,
        )

    @staticmethod
    def applies_to(target: ValidationTarget) -> bool:
        del target
        return True

    def validate(self, target: ValidationTarget, stream: BinaryIO) -> ValidationOutcome:
        del stream
        expected = self.expectation.expected_content_id
        passed = expected is not None and expected == target.content.content_id
        details: JsonObject = {
            "algorithm": self.expectation.algorithm,
            "digest": self.expectation.digest,
            "actual_content_id": str(target.content.content_id),
        }
        if expected is not None:
            details["expected_content_id"] = str(expected)
        else:
            details["error"] = "unsupported integrity expectation algorithm"
        return ValidationOutcome(status="passed" if passed else "failed", details=details)


class ValidationService:
    """Execute validators against immutable content and reuse repository evidence."""

    def __init__(self, repository: Repository, registry: ValidationRegistry) -> None:
        self.repository = repository
        self.registry = registry

    def _validate_one(
        self,
        target: ValidationTarget,
        validator: ContentValidator,
        *,
        checked_at: float | None,
    ) -> ValidationCheck:
        descriptor = validator.descriptor
        existing = self.repository.validation(
            target.content.content_id,
            descriptor.validator_id,
            descriptor.version,
        )
        if existing is not None:
            return ValidationCheck(existing, required=descriptor.required, reused=True)

        try:
            with self.repository.open_content(target.content.content_id) as stream:
                outcome = validator.validate(target, stream)
        except Exception as exc:  # ruff: ignore[blind-except] - domain validators are isolated evidence producers.
            outcome = ValidationOutcome(status="error", details={"error": f"{type(exc).__name__}: {exc}"})
        result = ValidationResult(
            content_id=target.content.content_id,
            validator=descriptor.validator_id,
            validator_version=descriptor.version,
            checked_at=time.time() if checked_at is None else checked_at,
            status=outcome.status,
            details=outcome.details,
        )
        self.repository.record_validation(result)
        return ValidationCheck(result, required=descriptor.required, reused=False)

    def validate_content(
        self,
        content: ContentRef,
        *,
        name: str | None = None,
        expectations: tuple[IntegrityExpectation, ...] = (),
        checked_at: float | None = None,
    ) -> ValidationBatch:
        target = ValidationTarget(content=content, name=name)
        validators = (
            *self.registry.applicable(target),
            *(IntegrityExpectationValidator(expectation) for expectation in expectations),
        )
        checks = tuple(
            self._validate_one(target, validator, checked_at=checked_at)
            for validator in validators
        )
        return ValidationBatch(checks)


def builtin_validation_registry() -> ValidationRegistry:
    return ValidationRegistry((StorageIntegrityValidator(), GzipValidator(), JsonValidator()))


__all__ = [
    "ContentValidator",
    "GzipValidator",
    "IntegrityExpectationValidator",
    "JsonValidator",
    "StorageIntegrityValidator",
    "ValidationBatch",
    "ValidationCheck",
    "ValidationOutcome",
    "ValidationRegistry",
    "ValidationService",
    "ValidationStatus",
    "ValidationTarget",
    "ValidatorDescriptor",
    "builtin_validation_registry",
]
