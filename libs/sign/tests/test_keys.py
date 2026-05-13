"""Tests for sign.keys."""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from sign.keys import KeyStore, PublicKey, load_or_generate


def test_generates_when_dir_empty(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    assert isinstance(ks, KeyStore)
    assert (tmp_path / "signing.key").exists()
    assert (tmp_path / "signing.pub").exists()


def test_reuses_existing_keys(tmp_path: Path) -> None:
    ks1 = load_or_generate(tmp_path)
    ks2 = load_or_generate(tmp_path)
    [pk1] = ks1.public_keys()
    [pk2] = ks2.public_keys()
    assert pk1.kid == pk2.kid


def test_public_keys_returns_list_of_publickey(tmp_path: Path) -> None:
    ks = load_or_generate(tmp_path)
    pks = ks.public_keys()
    assert isinstance(pks, list)
    assert len(pks) == 1
    [pk] = pks
    assert isinstance(pk, PublicKey)
    assert pk.alg == "RS256"
    assert isinstance(pk.kid, str) and len(pk.kid) == 16
    assert isinstance(pk.key, RSAPublicKey)


def test_load_or_generate_accepts_str_path(tmp_path: Path) -> None:
    ks = load_or_generate(str(tmp_path))
    assert isinstance(ks, KeyStore)
