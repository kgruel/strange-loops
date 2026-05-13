"""RSA signing key management.

Generates an RSA-2048 key on first start if absent, persists it to a directory,
loads on subsequent starts. The store holds one signing keypair today; the
verify-side surface (`public_keys()`) returns a list to anticipate key rotation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

__all__ = ["KeyStore", "PublicKey", "load_or_generate"]

log = logging.getLogger(__name__)

_KEY_FILE = "signing.key"
_PUB_FILE = "signing.pub"
_ALG = "RS256"


@dataclass(frozen=True)
class PublicKey:
    """A public key with its JWT identification metadata.

    Used by `verify()` to look up the right key by `kid` and by `jwks.parse()`
    as the normalized output of a JWKS document.
    """

    kid: str
    alg: str
    key: RSAPublicKey


def _generate(key_dir: Path) -> None:
    log.info("generating RSA-2048 signing key in %s", key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (key_dir / _KEY_FILE).write_bytes(key_pem)
    (key_dir / _PUB_FILE).write_bytes(pub_pem)
    (key_dir / _KEY_FILE).chmod(0o600)


def _compute_kid(public_key_obj: RSAPublicKey) -> str:
    der = public_key_obj.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()[:16]


def _build_jwk(public_key_obj: RSAPublicKey, kid: str) -> dict:
    from jwt.algorithms import RSAAlgorithm

    pub_jwk = json.loads(RSAAlgorithm.to_jwk(public_key_obj))
    pub_jwk["use"] = "sig"
    pub_jwk["alg"] = _ALG
    pub_jwk["kid"] = kid
    return pub_jwk


class KeyStore:
    """Owns signing keys + their public counterparts.

    Internal attributes (`_signing_key`, `_public_key`, `_kid`, `_jwk_dict`) are
    underscore-prefixed: cross-module access within libs/sign is OK (sign.jwt
    and sign.jwks reach in), but they carry NO stability contract for external
    consumers. The only public method is `public_keys()`.
    """

    def __init__(
        self,
        signing_key,
        public_key: RSAPublicKey,
        kid: str,
        jwk_dict: dict,
    ) -> None:
        self._signing_key = signing_key
        self._public_key = public_key
        self._kid = kid
        self._jwk_dict = jwk_dict

    def public_keys(self) -> list[PublicKey]:
        """Return the public keys this store can verify against (self-verify path).

        Today this is a single-element list (KeyStore holds one signing key).
        Returns a list to anticipate key rotation — when rotation lands, verify()
        must accept multiple keys to bridge the rotation window. Shape stable;
        cardinality grows.
        """
        return [PublicKey(kid=self._kid, alg=_ALG, key=self._public_key)]


def load_or_generate(signing_key_dir: str | Path) -> KeyStore:
    """Ensure the signing key exists, then load and return a KeyStore."""
    key_dir = Path(signing_key_dir)
    key_path = key_dir / _KEY_FILE

    if not key_path.exists():
        _generate(key_dir)

    key_pem = key_path.read_bytes()
    private_key_obj = serialization.load_pem_private_key(key_pem, password=None)
    if not isinstance(private_key_obj, RSAPrivateKey):
        kind = type(private_key_obj).__name__
        raise ValueError(f"expected RSA private key in {key_path}, got {kind}")
    public_key_obj = private_key_obj.public_key()
    kid = _compute_kid(public_key_obj)
    jwk_dict = _build_jwk(public_key_obj, kid)
    log.info("signing key loaded, kid=%s", kid)
    return KeyStore(
        signing_key=private_key_obj,
        public_key=public_key_obj,
        kid=kid,
        jwk_dict=jwk_dict,
    )
