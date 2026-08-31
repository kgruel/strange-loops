"""Direct unit tests for the custody composition layer.

Full CLI composition (emit → verify) is exercised in apps/loops/tests;
these pin the lib's own contract: key layout, minting side effects,
signer/verifier construction, and the guards.
"""

from __future__ import annotations

from pathlib import Path

from custody import (
    FACT_DOMAIN,
    TICK_DOMAIN,
    ensure_signing_key,
    fact_signer_for,
    keys_dir_for,
    observer_keys_dir_for,
    tick_signer_for,
)
from custody.signing import (
    ARRIVAL_DOMAIN,
    arrival_signer_for,
    arrival_verifier_for,
    fact_verifier_for,
)
from sign import ed25519


def _vertex(tmp_path: Path) -> Path:
    vpath = tmp_path / "x.vertex"
    vpath.write_text('vertex "x" { store "./x.db" }\n')
    return vpath


class TestLayout:
    def test_keys_dir_is_sibling_of_vertex(self, tmp_path):
        v = _vertex(tmp_path)
        assert keys_dir_for(v) == tmp_path / "keys"

    def test_observer_dir_nests_slashed_names(self, tmp_path):
        v = _vertex(tmp_path)
        assert observer_keys_dir_for(v, "kyle/loops-claude") == (
            tmp_path / "keys" / "kyle" / "loops-claude"
        )


class TestEnsureSigningKey:
    def test_mints_flat_key_and_gitignores(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v)
        assert (tmp_path / "keys" / "ed25519.key").exists()
        assert "keys/" in (tmp_path / ".gitignore").read_text().splitlines()

    def test_idempotent_load(self, tmp_path):
        v = _vertex(tmp_path)
        kp1 = ensure_signing_key(v)
        kp2 = ensure_signing_key(v)
        assert kp1.public_b64 == kp2.public_b64

    def test_observer_mints_nested(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v, observer="alice")
        assert (tmp_path / "keys" / "alice" / "ed25519.key").exists()

    def test_self_observer_mints_flat(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v, observer="x")  # == vertex stem → flat layout
        assert (tmp_path / "keys" / "ed25519.key").exists()
        assert not (tmp_path / "keys" / "x").exists()

    def test_appends_to_existing_gitignore(self, tmp_path):
        v = _vertex(tmp_path)
        (tmp_path / ".gitignore").write_text("*.db\n")
        ensure_signing_key(v)
        lines = (tmp_path / ".gitignore").read_text().splitlines()
        assert lines == ["*.db", "keys/"]


class TestTickSigner:
    def test_none_without_key_material(self, tmp_path):
        assert tick_signer_for(_vertex(tmp_path)) is None

    def test_signs_under_tick_domain(self, tmp_path):
        v = _vertex(tmp_path)
        kp = ensure_signing_key(v)
        sig = tick_signer_for(v)("digest")
        pub = ed25519.public_key_from_b64(kp.public_b64)
        assert ed25519.verify(pub, sig, b"digest", domain=TICK_DOMAIN)
        assert not ed25519.verify(pub, sig, b"digest", domain=FACT_DOMAIN)


class TestFactSigner:
    def test_none_without_keys_dir(self, tmp_path):
        assert fact_signer_for(_vertex(tmp_path)) is None

    def test_flat_key_is_self_observer_only(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v)
        signer = fact_signer_for(v)
        assert signer("x", "digest") is not None  # self-observer → flat key
        assert signer("stranger", "digest") is None  # unkeyed → unsigned era

    def test_empty_observer_never_signs(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v)
        assert fact_signer_for(v)("", "digest") is None

    def test_path_traversal_guarded(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v)
        assert fact_signer_for(v)("../x", "digest") is None


class TestArrivalSigner:
    def test_none_without_keys_dir(self, tmp_path):
        assert arrival_signer_for(_vertex(tmp_path)) is None

    def test_signs_under_arrival_domain_and_roundtrips(self, tmp_path):
        v = tmp_path / "x.vertex"
        kp = ensure_signing_key(v)
        v.write_text(
            f'name "x"\nstore "./x.arrival" backend="file"\nobservers {{\n  x {{\n    key "{kp.public_b64}"\n  }}\n}}\nloops {{\n  concept {{ fold {{ items "collect" 100 }} }}\n}}\n'
        )
        signer = arrival_signer_for(v)
        assert signer is not None
        sig = signer("x", "0" * 64)
        assert sig is not None
        pub = ed25519.public_key_from_b64(kp.public_b64)
        assert ed25519.verify(pub, sig, ("0" * 64).encode(), domain=ARRIVAL_DOMAIN)

        verifier, keys = arrival_verifier_for(v)
        assert verifier is not None
        assert verifier("x", sig, "0" * 64) is True

    def test_fact_and_arrival_mutually_refuse(self, tmp_path):
        v = tmp_path / "x.vertex"
        kp = ensure_signing_key(v)
        v.write_text(
            f'name "x"\nstore "./x.arrival" backend="file"\nobservers {{\n  x {{\n    key "{kp.public_b64}"\n  }}\n}}\nloops {{\n  concept {{ fold {{ items "collect" 100 }} }}\n}}\n'
        )
        arr_signer = arrival_signer_for(v)
        fact_signer = fact_signer_for(v)
        arr_verifier, _ = arrival_verifier_for(v)
        fact_verifier, _ = fact_verifier_for(v)

        digest = "a" * 64
        arr_sig = arr_signer("x", digest)
        fact_sig = fact_signer("x", digest)

        # Arrival signature verifies under arrival, fails under fact
        assert arr_verifier("x", arr_sig, digest) is True
        assert fact_verifier("x", arr_sig, digest) is False

        # Fact signature verifies under fact, fails under arrival
        assert fact_verifier("x", fact_sig, digest) is True
        assert arr_verifier("x", fact_sig, digest) is False

    def test_flat_key_is_self_observer_only(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v)
        signer = arrival_signer_for(v)
        assert signer("x", "digest") is not None
        assert signer("stranger", "digest") is None

    def test_empty_observer_never_signs(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v)
        assert arrival_signer_for(v)("", "digest") is None

    def test_path_traversal_guarded(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v)
        assert arrival_signer_for(v)("../x", "digest") is None
