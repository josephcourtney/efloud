from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def sign_ed25519(private_key: bytes, message: bytes) -> bytes:
    """Sign canonical lock bytes with a raw 32-byte Ed25519 private key."""
    signer = Ed25519PrivateKey.from_private_bytes(private_key)
    return signer.sign(message)


def verify_ed25519(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify a raw Ed25519 public key and detached signature."""
    try:
        verifier = Ed25519PublicKey.from_public_bytes(public_key)
        verifier.verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


__all__ = ["sign_ed25519", "verify_ed25519"]
