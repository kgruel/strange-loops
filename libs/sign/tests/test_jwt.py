"""Tests for sign.jwt — mint, verify, the JWT envelope contract."""

from __future__ import annotations

import time
from pathlib import Path

import jwt as pyjwt
import pytest
from ulid import ULID

from sign.jwt import mint, verify
from sign.keys import load_or_generate


def test_mint_verify_roundtrip(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    token, jti = mint(
        keystore=ks,
        issuer="https://iss.example",
        claims={"sub": "alice", "aud": "api", "scope": "read"},
        ttl_seconds=60,
    )
    claims = verify(
        token,
        public_keys=ks.public_keys(),
        issuer="https://iss.example",
        audience="api",
    )
    assert claims["sub"] == "alice"
    assert claims["scope"] == "read"
    assert claims["iss"] == "https://iss.example"
    assert claims["jti"] == jti


def test_caller_supplied_jti(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    token, jti = mint(
        keystore=ks,
        issuer="iss",
        claims={"sub": "x", "aud": "a"},
        ttl_seconds=60,
        jti="custom-jti-value",
    )
    assert jti == "custom-jti-value"
    claims = verify(token, public_keys=ks.public_keys(), issuer="iss", audience="a")
    assert claims["jti"] == "custom-jti-value"


def test_generated_jti_is_valid_ulid(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    _, jti = mint(
        keystore=ks,
        issuer="iss",
        claims={"sub": "x", "aud": "a"},
        ttl_seconds=60,
    )
    # ULID.from_str raises if invalid.
    ULID.from_str(jti)


def test_iat_exp_injection(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    before = int(time.time())
    token, _ = mint(
        keystore=ks,
        issuer="iss",
        claims={"sub": "x", "aud": "a"},
        ttl_seconds=600,
    )
    after = int(time.time())
    claims = verify(token, public_keys=ks.public_keys(), issuer="iss", audience="a")
    assert before <= claims["iat"] <= after
    assert claims["exp"] - claims["iat"] == 600


def test_kid_missing_from_keyset(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path / "issuer")
    token, _ = mint(
        keystore=ks,
        issuer="iss",
        claims={"sub": "x", "aud": "a"},
        ttl_seconds=60,
    )
    other = load_or_generate(tmp_path / "other")
    with pytest.raises(pyjwt.InvalidTokenError):
        verify(token, public_keys=other.public_keys(), issuer="iss", audience="a")


def test_kidless_token_rejected(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    bad = pyjwt.encode(
        {"iss": "iss", "aud": "a", "sub": "x", "iat": 0, "exp": 9_999_999_999, "jti": "j"},
        ks._signing_key,
        algorithm="RS256",
    )
    with pytest.raises(pyjwt.InvalidTokenError):
        verify(bad, public_keys=ks.public_keys(), issuer="iss", audience="a")


def test_wrong_issuer(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    token, _ = mint(
        keystore=ks,
        issuer="iss-a",
        claims={"sub": "x", "aud": "a"},
        ttl_seconds=60,
    )
    with pytest.raises(pyjwt.InvalidIssuerError):
        verify(token, public_keys=ks.public_keys(), issuer="iss-b", audience="a")


def test_wrong_audience(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    token, _ = mint(
        keystore=ks,
        issuer="iss",
        claims={"sub": "x", "aud": "good"},
        ttl_seconds=60,
    )
    with pytest.raises(pyjwt.InvalidAudienceError):
        verify(token, public_keys=ks.public_keys(), issuer="iss", audience="bad")


def test_expired_token(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    token, _ = mint(
        keystore=ks,
        issuer="iss",
        claims={"sub": "x", "aud": "a"},
        ttl_seconds=1,
    )
    time.sleep(1.5)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        verify(token, public_keys=ks.public_keys(), issuer="iss", audience="a")


def test_arbitrary_claims_pass_through(tmp_path: Path) -> None:
    """The library does not inspect claim contents — anything caller passes flows through."""
    ks = load_or_generate(tmp_path)
    token, _ = mint(
        keystore=ks,
        issuer="iss",
        claims={
            "sub": "alice",
            "aud": "api",
            "act": {"sub": "service"},
            "scope": "read write",
            "custom_field": {"nested": [1, 2, 3]},
        },
        ttl_seconds=60,
    )
    claims = verify(token, public_keys=ks.public_keys(), issuer="iss", audience="api")
    assert claims["act"] == {"sub": "service"}
    assert claims["custom_field"] == {"nested": [1, 2, 3]}
