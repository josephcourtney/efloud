from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from efloud.dataset_export import DetachedDatasetManifest
from efloud.errors import EfloudError
from efloud.fs import atomic_write_bytes
from efloud.json_types import JsonObject, is_json_object
from efloud.metadata_envelopes import source_definition_revision_id
from efloud.repository_models import canonical_json_bytes, stable_id

LOCK_VERSION = 1
_DEFAULT_FILENAME = "efloud.lock"


class LockfileError(EfloudError):
    """A project lock is malformed, inconsistent, or unsupported."""


class SignatureError(LockfileError):
    """A project-lock signing or signature-verification operation failed."""


@dataclass(frozen=True, slots=True)
class LockSignature:
    """Detached authentication evidence over the canonical unsigned lock payload."""

    algorithm: str
    key_id: str
    value: str

    def __post_init__(self) -> None:
        if self.algorithm != "ed25519":
            raise SignatureError(f"Unsupported lock signature algorithm: {self.algorithm!r}")
        if not self.key_id.strip():
            raise SignatureError("Lock signature key_id must not be empty")
        try:
            raw = base64.b64decode(self.value, validate=True)
        except ValueError as exc:
            raise SignatureError("Lock signature is not valid base64") from exc
        if len(raw) != 64:
            raise SignatureError("Ed25519 lock signatures must be 64 bytes")

    def to_dict(self) -> JsonObject:
        return {"algorithm": self.algorithm, "key_id": self.key_id, "value": self.value}

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> LockSignature:
        unknown = sorted(set(value) - {"algorithm", "key_id", "value"})
        if unknown:
            raise SignatureError(f"Unsupported signature keys: {unknown}")
        algorithm = value.get("algorithm")
        key_id = value.get("key_id")
        signature = value.get("value")
        if not all(isinstance(item, str) for item in (algorithm, key_id, signature)):
            raise SignatureError("Lock signature fields must be strings")
        return cls(algorithm, key_id, signature)


@dataclass(frozen=True, slots=True)
class SignaturePolicy:
    """Authentication requirements kept separate from hash-based lock integrity."""

    require_signed: bool = False
    required_key_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not value.strip() for value in self.required_key_ids):
            raise SignatureError("Required signature key ids must not be empty")
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
        object.__setattr__(self, "declaration", dict(self.declaration))
        object.__setattr__(self, "sources", tuple(dict(item) for item in self.sources))
        object.__setattr__(self, "datasets", tuple(dict(item) for item in self.datasets))
        ordered = tuple(sorted(self.signatures, key=lambda item: item.key_id))
        if len({item.key_id for item in ordered}) != len(ordered):
            raise SignatureError("A lock may contain at most one signature per key_id")
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
        for source in self.sources:
            snapshot = source.get("snapshot")
            if not isinstance(snapshot, dict) or snapshot.get("complete") is not True or source.get("resolution") is None:
                return False
        return True

    def _unsigned_payload(self) -> JsonObject:
        return {
            "version": LOCK_VERSION,
            "declaration_id": self.declaration_id,
            "declaration": dict(self.declaration),
            "sources": [dict(item) for item in self.sources],
            "datasets": [dict(item) for item in self.datasets],
        }

    def signing_bytes(self) -> bytes:
        """Canonical bytes authenticated by every signature in this lock."""
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
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LockfileError("efloud.lock is not valid UTF-8 JSON") from exc
        if not is_json_object(value):
            raise LockfileError("efloud.lock must contain a JSON object")
        allowed = {
            "version",
            "lock_id",
            "declaration_id",
            "declaration",
            "sources",
            "datasets",
            "signatures",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise LockfileError(f"Unsupported lock keys: {unknown}")
        if value.get("version") != LOCK_VERSION:
            raise LockfileError(
                f"Unsupported efloud.lock version: {value.get('version')!r}; expected {LOCK_VERSION}"
            )
        declaration = value.get("declaration")
        raw_sources = value.get("sources")
        raw_datasets = value.get("datasets")
        raw_signatures = value.get("signatures", [])
        if not is_json_object(declaration):
            raise LockfileError("lock declaration must be a JSON object")
        if not isinstance(raw_sources, list) or not all(is_json_object(item) for item in raw_sources):
            raise LockfileError("lock sources must be an array of JSON objects")
        if not isinstance(raw_datasets, list) or not all(is_json_object(item) for item in raw_datasets):
            raise LockfileError("lock datasets must be an array of JSON objects")
        if not isinstance(raw_signatures, list) or not all(isinstance(item, Mapping) for item in raw_signatures):
            raise LockfileError("lock signatures must be an array of objects")
        declaration_id = value.get("declaration_id")
        lock_id = value.get("lock_id")
        if not isinstance(declaration_id, str) or not isinstance(lock_id, str):
            raise LockfileError("lock identities must be strings")
        result = cls(
            declaration_id,
            dict(declaration),
            tuple(dict(item) for item in raw_sources),
            tuple(dict(item) for item in raw_datasets),
            tuple(LockSignature.from_mapping(item) for item in raw_signatures),
        )
        if result.lock_id != lock_id:
            raise LockfileError("Project lock identity mismatch")
        return result

    def validate(self) -> None:
        expected_declaration = stable_id("project-declaration-v1", self.declaration)
        if self.declaration_id != expected_declaration:
            raise LockfileError("Project declaration identity mismatch")
        source_ids: set[str] = set()
        for source in self.sources:
            source_id = _required_text(source, "source_id", context="lock source")
            if source_id in source_ids:
                raise LockfileError(f"Duplicate locked source: {source_id}")
            source_ids.add(source_id)
            definition = source.get("definition")
            if not is_json_object(definition):
                raise LockfileError(f"Locked source {source_id!r} has no valid definition")
            definition_id = _required_text(source, "definition_id", context=f"source {source_id}")
            if definition_id != str(source_definition_revision_id(source_id, definition)):
                raise LockfileError(f"Source definition identity mismatch: {source_id}")
            adapter = source.get("adapter")
            if not is_json_object(adapter):
                raise LockfileError(f"Locked source {source_id!r} has no adapter identity")
            _required_text(adapter, "id", context=f"source {source_id} adapter")
            _required_text(adapter, "version", context=f"source {source_id} adapter")
            snapshot = source.get("snapshot")
            if not is_json_object(snapshot) or snapshot.get("source_id") != source_id:
                raise LockfileError(f"Locked source snapshot disagrees with source {source_id!r}")
            if type(snapshot.get("complete")) is not bool:
                raise LockfileError(f"Locked source {source_id!r} snapshot completeness is invalid")
            resolution = source.get("resolution")
            if resolution is not None:
                _validate_manifest(resolution, context=f"source {source_id} resolution")
        dataset_names: set[str] = set()
        for dataset in self.datasets:
            name = _required_text(dataset, "name", context="lock dataset")
            if name in dataset_names:
                raise LockfileError(f"Duplicate locked dataset: {name}")
            dataset_names.add(name)
            manifest = dataset.get("manifest")
            parsed = _validate_manifest(manifest, context=f"dataset {name}")
            for key, expected in (
                ("specification_id", str(parsed.to_dict().get("specification_id"))),
                ("dataset_id", parsed.dataset_id),
                ("content_identity", parsed.content_identity),
            ):
                if dataset.get(key) != expected:
                    raise LockfileError(f"Locked dataset {name!r} {key} mismatch")

    def sign_ed25519(self, private_key: bytes, *, key_id: str) -> ProjectLock:
        """Return a new lock signed by one externally managed raw Ed25519 private key."""
        if not key_id.strip():
            raise SignatureError("Signing key_id must not be empty")
        Ed25519PrivateKey, _Ed25519PublicKey, _InvalidSignature = _cryptography_ed25519()
        try:
            signer = Ed25519PrivateKey.from_private_bytes(private_key)
            raw_signature = signer.sign(self.signing_bytes())
        except ValueError as exc:
            raise SignatureError("Ed25519 private keys must be 32 raw bytes") from exc
        signature = LockSignature("ed25519", key_id, base64.b64encode(raw_signature).decode("ascii"))
        retained = tuple(item for item in self.signatures if item.key_id != key_id)
        return replace(self, signatures=(*retained, signature))

    def verify_signatures(
        self,
        public_keys: Mapping[str, bytes],
        *,
        policy: SignaturePolicy = SignaturePolicy(),
    ) -> bool:
        """Verify authentication policy using externally trusted raw Ed25519 public keys."""
        self.validate()
        if not self.signatures:
            return not policy.require_signed and not policy.required_key_ids
        _Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature = _cryptography_ed25519()
        valid: set[str] = set()
        for signature in self.signatures:
            raw_key = public_keys.get(signature.key_id)
            if raw_key is None:
                continue
            try:
                verifier = Ed25519PublicKey.from_public_bytes(raw_key)
                verifier.verify(base64.b64decode(signature.value), self.signing_bytes())
            except (InvalidSignature, ValueError):
                continue
            valid.add(signature.key_id)
        if not set(policy.required_key_ids).issubset(valid):
            return False
        if policy.require_signed and not valid:
            return False
        return True


def _validate_manifest(value: object, *, context: str) -> DetachedDatasetManifest:
    if not is_json_object(value):
        raise LockfileError(f"{context} must contain a detached dataset manifest")
    try:
        return DetachedDatasetManifest.from_bytes(canonical_json_bytes(value))
    except (KeyError, TypeError, ValueError) as exc:
        raise LockfileError(f"Invalid {context}: {exc}") from exc


def _required_text(value: Mapping[str, object], key: str, *, context: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise LockfileError(f"{context}.{key} must be a non-empty string")
    return item


def _source_sort_key(value: JsonObject) -> str:
    return _required_text(value, "source_id", context="lock source")


def _dataset_sort_key(value: JsonObject) -> str:
    return _required_text(value, "name", context="lock dataset")


def _cryptography_ed25519() -> tuple[type, type, type[Exception]]:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as exc:
        raise SignatureError("Ed25519 signing requires the optional 'efloud[signing]' dependency") from exc
    return Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature


__all__ = [
    "LOCK_VERSION",
    "LockSignature",
    "LockfileError",
    "ProjectLock",
    "SignatureError",
    "SignaturePolicy",
]
