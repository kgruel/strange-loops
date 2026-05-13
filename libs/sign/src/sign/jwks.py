"""JWKS document construction and parsing, plus OpenID Connect discovery.

Pure functions — no HTTP framework coupling. Consumers wrap the returned dicts
in their own framework's response (e.g. a one-line Litestar handler).
"""

from __future__ import annotations

import json

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.algorithms import RSAAlgorithm

from sign.keys import KeyStore, PublicKey

__all__ = ["build_document", "build_openid_configuration", "parse"]


def build_document(keystore: KeyStore) -> dict:
    """Build a JWKS document per RFC 7517.

    Shape: {"keys": [<jwk-dict>, ...]}. Each entry carries kid, kty, alg, use,
    n, e (for RSA).
    """
    return {"keys": [dict(keystore._jwk_dict)]}


def build_openid_configuration(
    issuer: str,
    *,
    jwks_uri: str,
    **extra: object,
) -> dict:
    """Build an OpenID Connect discovery document.

    Required fields: issuer, jwks_uri. Anything else (e.g. response_types_supported,
    subject_types_supported, id_token_signing_alg_values_supported) flows through
    **extra into the output dict verbatim.
    """
    doc: dict = {"issuer": issuer, "jwks_uri": jwks_uri}
    doc.update(extra)
    return doc


def parse(jwks_dict: dict) -> list[PublicKey]:
    """Parse a JWKS document into a list of PublicKey for use with verify().

    Inverse of build_document() for public-key fields. Entries missing kid/alg
    or with unsupported kty are skipped.
    """
    out: list[PublicKey] = []
    for entry in jwks_dict.get("keys", []):
        kid = entry.get("kid")
        alg = entry.get("alg")
        kty = entry.get("kty")
        if not kid or kty != "RSA" or alg != "RS256":
            continue
        key = RSAAlgorithm.from_jwk(json.dumps(entry))
        if not isinstance(key, RSAPublicKey):
            continue
        out.append(PublicKey(kid=kid, alg=alg, key=key))
    return out
