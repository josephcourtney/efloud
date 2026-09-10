from __future__ import annotations

import base64
import importlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from efloud.dataset_export import DetachedDatasetManifest
from efloud.errors import EfloudError
from efloud.fs import atomic_write_bytes
from efloud.json_types import JsonObject, is_json_object
from efloud.metadata_envelopes import source_definition_revision_id
from efloud.repository_models import canonical_json_bytes, stable_id

if TYPE_CHECKING:
    from typing import NoReturn

LOCK_VERSION = 1
_DEFAULT_FILENAME = "efloud.lock"
_ED25519_SIGNATURE_BYTES = 64


class LockfileError(EfloudError):
    """A project lock is malformed, inconsistent, or unsupported."""


class SignatureError(LockfileError):
    """A project-lock signing or signature-verification operation failed."""


class _SigningBackend(Protocol):
    def sign_ed25519(self, private_key: bytes, message: bytes) -> bytes: ...

    def verify_ed25519(self, public_key: bytes, message: bytes, signature: bytes) -> bool: ...


def _lock_failure(message: str) -> NoReturn:
    raise LockfileError(message)


def _signature_failure(message: str) -> NoReturn:
    raise SignatureError(message)


@dataclass(frozen=True, slots=True)
class LockSignature:
    """Detached authentication evidence over the canonical unsigned lock payload."""

    algorithm: str
    key_id: str
    value: str

    def __post_init__(self) -> None:
        """Validate one serialized signature envelope."""
        if self.algorithm != "ed25519":
            _signature_failure(f"Unsupported lock signature algorithm: {self.algorithm!r}")
        if not self.key_id.strip():
            _signature_failure("Lock signature key_id must not be empty")
        try:
            raw = base64.b64decode(self.value, validate=True)
        except ValueError as exc:
            msg = "Lock signature is not valid base64"
            raise SignatureError(msg) from exc
        if len(raw) != _ED25519_SIGNATURE_BYTES:
            _signature_failure("Ed25519 lock signatures must be 64 bytes")

    def to_dict(self) -> JsonObject:
        return {"algorithm": self.algorithm, "key_id": self.key_id, "value": self.value}

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> LockSignature:
        unknown = sorted(set(value) - {"algorithm", "key_id", "value"})
        if unknown:
            _signature_failure(f"Unsupported signature keys: {unknown}")
        algorithm = value.get("algorithm")
        key_id = value.get("key_id")
        signature = value.get("value")
        if not all(isinstance(item, str) for item in (algorithm, key_id, signature)):
            _signature_failure("Lock signature fields must be strings")
        return cls(algorithm, key_id, signature)


@dataclass(frozen=True, slots=True)
class SignaturePolicy:
    """Authentication requirements kept separate from hash-based lock integrity."""

    require_signed: bool = False
    required_key_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Normalize the externally supplied signature policy."""
        if any(not value.strip() for value in self.required_key_ids):
            _signature_failure("Required signature key ids must not be empty")
        object.__setattr__(self, "required_key_ids", tuple(sorted(set(self.required_key_ids))))


@dataclass(frozen=True, slots=True)
class ProjectLock:
    """Canonical exact resolution of one declarative Efloud project."""

    declaration_id: str
    declaration: JsonObject
    sources: tuple[JsonObject, ...]
    datasets: tuple[JsonObject, ...]
    signatures: tuple[LockSignature, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize ordering and validate all integrity-bearing lock evidence."""
        object.__setattr__(self, "declaration", dict(self.declaration))
        object.__setattr__(self, "sources", tuple(dict(item) for item in self.sources))
        object.__setattr__(self, "datasets", tuple(dict(item) for item in self.datasets))
        ordered = tuple(sorted(self.signatures, key=lambda item: item.key_id))
        if len({item.key_id for item in ordered}) != len(ordered):
            _signature_failure("A lock may contain at most one signature per key_id")
        object.__setattr__(self, "signatures", ordered)
        self.validate()

    @classmethod
    def create(
        cls,
        *,
        declaration: JsonObject,
        sources: Sequence[JsonObject],
        datasets: Sequence[JsonObject],
    ) -> ProjectLock:
        declaration_copy = dict(declaration)
        declaration_id = stable_id("project-declaration-v1", declaration_copy)
        ordered_sources = tuple(sorted((dict(item) for item in sources), key=_source_sort_key))
        ordered_datasets = tuple(sorted((dict(item) for item in datasets), key=_dataset_sort_key))
        return cls(declaration_id, declaration_copy, ordered_sources, ordered_datasets)

    @property
    def lock_id(self) -> str:
        return stable_id("project-lock-v1", self._unsigned_payload())

    @property
    def complete(self) -> bool:
        return all(_source_resolution_complete(source) for source in self.sources)

    def _unsigned_payload(self) -> JsonObject:
        return {
            "version": LOCK_VERSION,
            "declaration_id": self.declaration_id,
            "declaration": dict(self.declaration),
            "sources": [dict(item) for item in self.sources],
            "datasets": [dict(item) for item in self.datasets],
        }

    def signing_bytes(self) -> bytes:
        """Return canonical bytes authenticated by every signature in this lock."""
        return canonical_json_bytes({**self._unsigned_payload(), "lock_id": self.lock_id})

    def to_dict(self) -> JsonObject:
        return {
            **self._unsigned_payload(),
            "lock_id": self.lock_id,
            "signatures": [item.to_dict() for item in self.signatures],
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"

    def write(self, path: str | Path = _DEFAULT_FILENAME) -> Path:
        destination = Path(path).expanduser().resolve(strict=False)
        atomic_write_bytes(destination, self.to_bytes())
        return destination

    @classmethod
    def load(cls, path: str | Path = _DEFAULT_FILENAME) -> ProjectLock:
        resolved = Path(path).expanduser().resolve(strict=True)
        try:
            return cls.from_bytes(resolved.read_bytes())
        except OSError as exc:
            raise LockfileError(str(exc)) from exc

    @classmethod
    def from_bytes(cls, data: bytes) -> ProjectLock:
        value = _decode_lock(data)
        declaration = _object(value.get("declaration"), context="lock declaration")
        sources = _object_array(value.get("sources"), context="lock sources")
        datasets = _object_array(value.get("datasets"), context="lock datasets")
        signatures = _signature_array(value.get("signatures", []))
        declaration_id = _required_text(value, "declaration_id", context="lock")
        lock_id = _required_text(value, "lock_id", context="lock")
        result = cls(declaration_id, declaration, sources, datasets, signatures)
        if result.lock_id != lock_id:
            _lock_failure("Project lock identity mismatch")
        return result

    def validate(self) -> None:
        """Recompute all lock identities and validate embedded exact evidence."""
        _validate_declaration(self.declaration_id, self.declaration)
        _validate_sources(self.sources)
        _validate_datasets(self.datasets)

    def sign_ed25519(self, private_key: bytes, *, key_id: str) -> ProjectLock:
        """Return a new lock signed by one externally managed raw Ed25519 private key."""
        if not key_id.strip():
            _signature_failure("Signing key_id must not be empty")
        try:
            raw_signature = _signing_backend().sign_ed25519(private_key, self.signing_bytes())
        except ValueError as exc:
            msg = "Ed25519 private keys must be 32 raw bytes"
            raise SignatureError(msg) from exc
        signature = LockSignature("ed25519", key_id, base64.b64encode(raw_signature).decode("ascii"))
        retained = tuple(item for item in self.signatures if item.key_id != key_id)
        return replace(self, signatures=(*retained, signature))

    def verify_signatures(
        self,
        public_keys: Mapping[str, bytes],
        *,
        policy: SignaturePolicy | None = None,
    ) -> bool:
        """Verify authentication policy using externally trusted raw Ed25519 public keys."""
        self.validate()
        effective_policy = SignaturePolicy() if policy is None else policy
        if not self.signatures:
            return not effective_policy.require_signed and not effective_policy.required_key_ids
        backend = _signing_backend()
        valid = {
            signature.key_id
            for signature in self.signatures
            if _signature_valid(backend, signature, public_keys, self.signing_bytes())
        }
        required = set(effective_policy.required_key_ids)
        return required.issubset(valid) and (not effective_policy.require_signed or bool(valid))


def _decode_lock(data: bytes) -> JsonObject:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = "efloud.lock is not valid UTF-8 JSON"
        raise LockfileError(msg) from exc
    result = _object(value, context="efloud.lock")
    allowed = {
        "version",
        "lock_id",
        "declaration_id",
        "declaration",
        "sources",
        "datasets",
        "signatures",
    }
    unknown = sorted(set(result) - allowed)
    if unknown:
        _lock_failure(f"Unsupported lock keys: {unknown}")
    if result.get("version") != LOCK_VERSION:
        _lock_failure(
            f"Unsupported efloud.lock version: {result.get('version')!r}; expected {LOCK_VERSION}"
        )
    return result


def _object(value: object, *, context: str) -> JsonObject:
    if not is_json_object(value):
        _lock_failure(f"{context} must be a JSON object")
    return dict(value)


def _object_array(value: object, *, context: str) -> tuple[JsonObject, ...]:
    if not isinstance(value, list) or not all(is_json_object(item) for item in value):
        _lock_failure(f"{context} must be an array of JSON objects")
    return tuple(dict(item) for item in value)


def _signature_array(value: object) -> tuple[LockSignature, ...]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        _lock_failure("lock signatures must be an array of objects")
    return tuple(LockSignature.from_mapping(item) for item in value)


def _source_resolution_complete(source: JsonObject) -> bool:
    snapshot = source.get("snapshot")
    return isinstance(snapshot, dict) and snapshot.get("complete") is True and source.get("resolution") is not None


def _validate_declaration(declaration_id: str, declaration: JsonObject) -> None:
    expected = stable_id("project-declaration-v1", declaration)
    if declaration_id != expected:
        _lock_failure("Project declaration identity mismatch")


def _validate_sources(sources: Sequence[JsonObject]) -> None:
    seen: set[str] = set()
    for source in sources:
        source_id = _required_text(source, "source_id", context="lock source")
        if source_id in seen:
            _lock_failure(f"Duplicate locked source: {source_id}")
        seen.add(source_id)
        _validate_source(source_id, source)


def _validate_source(source_id: str, source: JsonObject) -> None:
    definition = _object(source.get("definition"), context=f"source {source_id} definition")
    definition_id = _required_text(source, "definition_id", context=f"source {source_id}")
    if definition_id != str(source_definition_revision_id(source_id, definition)):
        _lock_failure(f"Source definition identity mismatch: {source_id}")
    adapter = _object(source.get("adapter"), context=f"source {source_id} adapter")
    _required_text(adapter, "id", context=f"source {source_id} adapter")
    _required_text(adapter, "version", context=f"source {source_id} adapter")
    snapshot = _object(source.get("snapshot"), context=f"source {source_id} snapshot")
    if snapshot.get("source_id") != source_id:
        _lock_failure(f"Locked source snapshot disagrees with source {source_id!r}")
    if type(snapshot.get("complete")) is not bool:
        _lock_failure(f"Locked source {source_id!r} snapshot completeness is invalid")
    resolution = source.get("resolution")
    if resolution is not None:
        _validate_manifest(resolution, context=f"source {source_id} resolution")


def _validate_datasets(datasets: Sequence[JsonObject]) -> None:
    seen: set[str] = set()
    for dataset in datasets:
        name = _required_text(dataset, "name", context="lock dataset")
        if name in seen:
            _lock_failure(f"Duplicate locked dataset: {name}")
        seen.add(name)
        _validate_dataset(name, dataset)


def _validate_dataset(name: str, dataset: JsonObject) -> None:
    parsed = _validate_manifest(dataset.get("manifest"), context=f"dataset {name}")
    expected = {
        "specification_id": str(parsed.to_dict().get("specification_id")),
        "dataset_id": parsed.dataset_id,
        "content_identity": parsed.content_identity,
    }
    for key, expected_value in expected.items():
        if dataset.get(key) != expected_value:
            _lock_failure(f"Locked dataset {name!r} {key} mismatch")


def _validate_manifest(value: object, *, context: str) -> DetachedDatasetManifest:
    if not is_json_object(value):
        _lock_failure(f"{context} must contain a detached dataset manifest")
    try:
        return DetachedDatasetManifest.from_bytes(canonical_json_bytes(value))
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"Invalid {context}: {exc}"
        raise LockfileError(msg) from exc


def _required_text(value: Mapping[str, object], key: str, *, context: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        _lock_failure(f"{context}.{key} must be a non-empty string")
    return item


def _source_sort_key(value: JsonObject) -> str:
    return _required_text(value, "source_id", context="lock source")


def _dataset_sort_key(value: JsonObject) -> str:
    return _required_text(value, "name", context="lock dataset")


def _signing_backend() -> _SigningBackend:
    try:
        module = importlib.import_module("efloud.signing")
    except ModuleNotFoundError as exc:
        msg = "Ed25519 signing requires the optional 'efloud[signing]' dependency"
        raise SignatureError(msg) from exc
    return cast("_SigningBackend", module)


def _signature_valid(
    backend: _SigningBackend,
    signature: LockSignature,
    public_keys: Mapping[str, bytes],
    message: bytes,
) -> bool:
    raw_key = public_keys.get(signature.key_id)
    if raw_key is None:
        return False
    return backend.verify_ed25519(raw_key, message, base64.b64decode(signature.value))


__all__ = [
    "LOCK_VERSION",
    "LockSignature",
    "LockfileError",
    "ProjectLock",
    "SignatureError",
    "SignaturePolicy",
]
