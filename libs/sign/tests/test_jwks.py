"""Tests for sign.jwks — document construction, OIDC discovery, parsing."""

from __future__ import annotations

from pathlib import Path

from sign.jwks import build_document, build_openid_configuration, parse
from sign.jwt import mint, verify
from sign.keys import load_or_generate


def test_build_document_shape(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    doc = build_document(ks)
    assert "keys" in doc
    assert isinstance(doc["keys"], list)
    assert len(doc["keys"]) == 1
    [jwk] = doc["keys"]
    assert jwk["kid"] == ks.public_keys()[0].kid
    assert jwk["alg"] == "RS256"
    assert jwk["kty"] == "RSA"
    assert "n" in jwk and "e" in jwk
    assert jwk["use"] == "sig"


def test_build_openid_configuration_minimal() -> None:
    doc = build_openid_configuration("https://iss.example", jwks_uri="https://iss.example/jwks")
    assert doc == {"issuer": "https://iss.example", "jwks_uri": "https://iss.example/jwks"}


def test_build_openid_configuration_extra_kwargs_canonical() -> None:
    """Commission's canonical OIDC fields flow through **extra unchanged.

    This is the migration path for vouch's wellknown handler: commission
    used to inject these directly; now the caller passes them as extra.
    """
    doc = build_openid_configuration(
        "https://iss.example",
        jwks_uri="https://iss.example/.well-known/jwks.json",
        response_types_supported=["token"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["RS256"],
    )
    assert doc["issuer"] == "https://iss.example"
    assert doc["jwks_uri"] == "https://iss.example/.well-known/jwks.json"
    assert doc["response_types_supported"] == ["token"]
    assert doc["subject_types_supported"] == ["public"]
    assert doc["id_token_signing_alg_values_supported"] == ["RS256"]


def test_parse_roundtrips_publickeys(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    parsed = parse(build_document(ks))
    [original] = ks.public_keys()
    [reparsed] = parsed
    assert reparsed.kid == original.kid
    assert reparsed.alg == original.alg
    # Compare the RSA public numbers — semantic equivalence, not Python identity.
    assert reparsed.key.public_numbers() == original.key.public_numbers()


def test_cross_bridge_mint_verify_via_jwks(tmp_path: Path) -> None:
    """Mint with keystore; verify via parse(build_document(keystore)).

    This exercises the remote-verify path: a consumer like pile fetches the
    JWKS over HTTP, parses it into PublicKey objects, and verifies.
    """
    ks = load_or_generate(tmp_path)
    token, _ = mint(
        keystore=ks,
        issuer="https://iss.example",
        claims={"sub": "alice", "aud": "api"},
        ttl_seconds=60,
    )
    remote_keys = parse(build_document(ks))
    claims = verify(token, public_keys=remote_keys, issuer="https://iss.example", audience="api")
    assert claims["sub"] == "alice"


def test_parse_skips_unsupported_entries() -> None:
    doc = {
        "keys": [
            {"kty": "EC", "kid": "ec1", "alg": "ES256"},  # unsupported kty
            {"kty": "RSA", "kid": "bad-alg", "alg": "HS256", "n": "abc", "e": "AQAB"},
            {"kty": "RSA", "alg": "RS256"},  # missing kid
            {"kty": "RSA", "kid": "missing-alg"},  # missing alg
        ]
    }
    assert parse(doc) == []


def test_parse_empty_document() -> None:
    assert parse({}) == []
    assert parse({"keys": []}) == []
