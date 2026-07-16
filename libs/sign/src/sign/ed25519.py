"""Ed25519 detached signatures over digests, with domain separation.

The provenance-arc signing primitive (loops delta 2: tick signing). A distinct
surface from sign.keys/sign.jwt — those mint RSA JWTs over claims documents;
this signs already-computed digests with deterministic Ed25519 (RFC 8032).
Determinism is the load-bearing property for tamper-evidence: the same
commitment always yields the same signature, so re-signing never produces
spurious diffs and signature equality is meaningful.

Domain separation is mandatory: every signature binds a caller-supplied domain
prefix (e.g. ``myapp-tick-v1``) so a signature minted for one surface can
never be replayed as a commitment on another. The prefix constant belongs to
the COMPOSING layer (apps/loops), not here — this library stays loops-agnostic.

Public-key wire format is raw-32-byte base64 (~44 chars) — small enough to
inline in a declaration file. ``load_or_generate`` writes the same string to
``ed25519.pub``, so the registry value is copy-identical to the file on disk.

Designed for namespaced import (``from sign import ed25519``): function names
deliberately mirror ``sign.keys`` (``load_or_generate``) and are therefore not
re-exported flat from the package root.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

__all__ = [
    "Keypair",
    "load_or_generate",
    "public_key_b64",
    "public_key_from_b64",
    "sign",
    "verify",
]

log = logging.getLogger(__name__)

_KEY_FILE = "ed25519.key"
_PUB_FILE = "ed25519.pub"


@dataclass(frozen=True)
class Keypair:
    """An Ed25519 signing keypair loaded from (or generated into) a key dir."""

    private: Ed25519PrivateKey
    public: Ed25519PublicKey

    @property
    def public_b64(self) -> str:
        """Raw-32-byte base64 of the public key — the registry/wire format."""
        return public_key_b64(self.public)


def _message(domain: str, digest: bytes) -> bytes:
    if not domain:
        raise ValueError("domain separation prefix must be non-empty")
    return domain.encode() + b":" + digest


def public_key_b64(public: Ed25519PublicKey) -> str:
    """Encode a public key as raw-32-byte base64 (the inline registry format)."""
    raw = public.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode()


def public_key_from_b64(data: str) -> Ed25519PublicKey:
    """Decode the inline registry format back to a public key.

    Raises ValueError on malformed base64 or wrong key length.
    """
    try:
        raw = base64.b64decode(data, validate=True)
    except binascii.Error as exc:
        raise ValueError(f"malformed base64 public key: {exc}") from exc
    if len(raw) != 32:
        raise ValueError(f"expected 32-byte Ed25519 public key, got {len(raw)} bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def _generate(key_dir: Path) -> None:
    log.info("generating Ed25519 signing key in %s", key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    key_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_path = key_dir / _KEY_FILE
    key_path.write_bytes(key_pem)
    key_path.chmod(0o600)
    (key_dir / _PUB_FILE).write_text(public_key_b64(private.public_key()) + "\n")


def load_or_generate(key_dir: str | Path) -> Keypair:
    """Ensure an Ed25519 keypair exists in ``key_dir``, then load and return it."""
    key_dir = Path(key_dir)
    key_path = key_dir / _KEY_FILE
    if not key_path.exists():
        _generate(key_dir)
    private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        kind = type(private).__name__
        raise ValueError(f"expected Ed25519 private key in {key_path}, got {kind}")
    return Keypair(private=private, public=private.public_key())


def sign(keypair: Keypair, digest: bytes, *, domain: str) -> str:
    """Sign a digest under a domain prefix; returns the signature as base64.

    Deterministic (RFC 8032): the same (key, domain, digest) always yields
    the same signature.
    """
    return base64.b64encode(keypair.private.sign(_message(domain, digest))).decode()


def verify(
    public: Ed25519PublicKey, signature_b64: str, digest: bytes, *, domain: str
) -> bool:
    """Check a base64 signature over a digest under a domain prefix.

    Returns False for any failure mode short of caller error — bad base64,
    wrong key, tampered digest, wrong domain. An empty domain still raises
    ValueError (that is a composition bug, not a verification outcome).
    """
    message = _message(domain, digest)
    try:
        raw = base64.b64decode(signature_b64, validate=True)
        public.verify(raw, message)
    except (InvalidSignature, binascii.Error, ValueError):
        return False
    return True
