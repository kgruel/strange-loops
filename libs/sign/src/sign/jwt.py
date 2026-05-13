"""JWT minting and verification.

Library injects iss/iat/exp/jti; caller builds the claims dict.
Verify accepts a normalized list of `PublicKey` (from either `keystore.public_keys()`
or `jwks.parse(...)`) and validates iss/aud/exp/signature/header.kid only — claim
content validation (sub, act, scope) is the caller's domain.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import jwt as pyjwt
from ulid import ULID

from sign.keys import KeyStore, PublicKey

__all__ = ["mint", "verify"]


def mint(
    *,
    keystore: KeyStore,
    issuer: str,
    claims: dict,
    ttl_seconds: int,
    jti: str | None = None,
) -> tuple[str, str]:
    """Mint a signed JWT.

    Library injects iss, iat, exp, jti — everything else (sub, aud, act, scope, …)
    is the caller's claims dict, merged in verbatim. The library does NOT inspect
    or validate the contents of claims.

    Returns: (encoded_jwt_token, jti).
    """
    now = int(time.time())
    resolved_jti = jti or str(ULID())
    payload: dict[str, Any] = {
        **claims,
        "iss": issuer,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": resolved_jti,
    }
    token = pyjwt.encode(
        payload,
        keystore._signing_key,
        algorithm="RS256",
        headers={"kid": keystore._kid},
    )
    return token, resolved_jti


def verify(
    token: str,
    *,
    public_keys: Sequence[PublicKey],
    issuer: str,
    audience: str,
) -> dict:
    """Verify a JWT against the provided key set.

    Looks up the signing key by `kid` from the token header in `public_keys`.
    Validates iss/aud/exp/signature. Claim-content checks (sub non-empty, act
    shape, scope, …) are the caller's responsibility — this library only
    verifies the JWT envelope.

    Raises pyjwt's InvalidTokenError subclasses for each failure mode.
    """
    header = pyjwt.get_unverified_header(token)
    kid = header.get("kid")
    if not kid:
        raise pyjwt.InvalidTokenError("token header missing kid")

    match = next((pk for pk in public_keys if pk.kid == kid), None)
    if match is None:
        raise pyjwt.InvalidTokenError(f"unknown kid: {kid}")

    claims = pyjwt.decode(
        token,
        match.key,
        algorithms=[match.alg],
        issuer=issuer,
        audience=audience,
        options={"require": ["exp", "iat", "iss", "aud", "jti"]},
    )
    return claims
