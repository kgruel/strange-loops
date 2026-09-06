"""Tests for sign.ed25519 — detached digest signatures with domain separation."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from sign import ed25519

DIGEST = hashlib.sha256(b"tick row canonical bytes").hexdigest().encode()
DOMAIN = "test-domain-a"


def test_generates_when_dir_empty(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    assert isinstance(kp, ed25519.Keypair)
    assert (tmp_path / "ed25519.key").exists()
    assert (tmp_path / "ed25519.pub").exists()


def test_load_reads_existing_keypair_without_creating(tmp_path: Path) -> None:
    original = ed25519.load_or_generate(tmp_path)
    loaded = ed25519.load(tmp_path)
    assert loaded.public_b64 == original.public_b64


def test_load_missing_key_never_creates_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        ed25519.load(missing)
    assert not missing.exists()


def test_concurrent_creation_publishes_one_complete_keypair(tmp_path: Path) -> None:
    key_dir = tmp_path / "concurrent"
    workers = 12
    barrier = Barrier(workers)

    def mint() -> str:
        barrier.wait()
        return ed25519.load_or_generate(key_dir).public_b64

    with ThreadPoolExecutor(max_workers=workers) as pool:
        public_keys = list(pool.map(lambda _unused: mint(), range(workers)))

    assert len(set(public_keys)) == 1
    assert (key_dir / "ed25519.pub").read_text().strip() == public_keys[0]
    assert list(key_dir.glob(".ed25519.*")) == []


def test_private_key_file_is_owner_only(tmp_path: Path) -> None:
    ed25519.load_or_generate(tmp_path)
    mode = (tmp_path / "ed25519.key").stat().st_mode & 0o777
    assert mode == 0o600


def test_reuses_existing_keypair(tmp_path: Path) -> None:
    kp1 = ed25519.load_or_generate(tmp_path)
    kp2 = ed25519.load_or_generate(tmp_path)
    assert kp1.public_b64 == kp2.public_b64


def test_pub_file_holds_the_inline_registry_string(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    assert (tmp_path / "ed25519.pub").read_text().strip() == kp.public_b64


def test_accepts_str_path(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(str(tmp_path))
    assert isinstance(kp, ed25519.Keypair)


def test_rejects_non_ed25519_key_file(tmp_path: Path) -> None:
    from sign.keys import load_or_generate as rsa_load_or_generate

    rsa_load_or_generate(tmp_path)  # writes signing.key (RSA)
    (tmp_path / "ed25519.key").write_bytes((tmp_path / "signing.key").read_bytes())
    with pytest.raises(ValueError, match="expected Ed25519"):
        ed25519.load_or_generate(tmp_path)


def test_sign_verify_roundtrip(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    sig = ed25519.sign(kp, DIGEST, domain=DOMAIN)
    assert ed25519.verify(kp.public, sig, DIGEST, domain=DOMAIN) is True


def test_signatures_are_deterministic(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    assert ed25519.sign(kp, DIGEST, domain=DOMAIN) == ed25519.sign(
        kp, DIGEST, domain=DOMAIN
    )


def test_tampered_digest_fails(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    sig = ed25519.sign(kp, DIGEST, domain=DOMAIN)
    assert ed25519.verify(kp.public, sig, DIGEST + b"x", domain=DOMAIN) is False


def test_wrong_domain_fails(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    sig = ed25519.sign(kp, DIGEST, domain=DOMAIN)
    assert ed25519.verify(kp.public, sig, DIGEST, domain="test-domain-b") is False


def test_wrong_key_fails(tmp_path: Path) -> None:
    kp_a = ed25519.load_or_generate(tmp_path / "a")
    kp_b = ed25519.load_or_generate(tmp_path / "b")
    sig = ed25519.sign(kp_a, DIGEST, domain=DOMAIN)
    assert ed25519.verify(kp_b.public, sig, DIGEST, domain=DOMAIN) is False


def test_malformed_signature_fails_not_raises(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    assert ed25519.verify(kp.public, "not base64!!", DIGEST, domain=DOMAIN) is False


def test_empty_domain_raises_on_both_sides(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    with pytest.raises(ValueError, match="domain"):
        ed25519.sign(kp, DIGEST, domain="")
    with pytest.raises(ValueError, match="domain"):
        ed25519.verify(kp.public, "AAAA", DIGEST, domain="")


def test_public_key_b64_roundtrip(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    restored = ed25519.public_key_from_b64(kp.public_b64)
    sig = ed25519.sign(kp, DIGEST, domain=DOMAIN)
    assert ed25519.verify(restored, sig, DIGEST, domain=DOMAIN) is True


def test_public_key_b64_is_inline_sized(tmp_path: Path) -> None:
    kp = ed25519.load_or_generate(tmp_path)
    assert len(kp.public_b64) == 44  # raw 32 bytes -> 44 base64 chars


def test_public_key_from_b64_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="base64"):
        ed25519.public_key_from_b64("@@@@")
    with pytest.raises(ValueError, match="32-byte"):
        ed25519.public_key_from_b64("AAAA")
