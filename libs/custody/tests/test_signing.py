"""Direct unit tests for the custody composition layer.

Full CLI composition (emit → verify) is exercised in apps/loops/tests;
these pin the lib's own contract: key layout, minting side effects,
signer/verifier construction, and the guards.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from sign import ed25519

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
    @pytest.mark.parametrize(
        "observer",
        [
            "",
            ".",
            "..",
            "../escape",
            "alice/../bob",
            "alice//bob",
            "ed25519.key",
            "ed25519.pub",
            "ED25519.KEY",
            "alice/ed25519.key",
        ],
    )
    def test_refuses_path_aliases_before_creating_keys(self, tmp_path, observer):
        vertex = _vertex(tmp_path)
        with pytest.raises(ValueError, match="observer"):
            ensure_signing_key(vertex, observer=observer)
        assert not (tmp_path / "keys").exists()
        assert not (tmp_path / ".gitignore").exists()

    def test_absolute_observer_cannot_select_external_key_directory(self, tmp_path):
        home = tmp_path / "vertex"
        home.mkdir()
        vertex = _vertex(home)
        external = tmp_path / "external"
        with pytest.raises(ValueError, match="observer"):
            ensure_signing_key(vertex, observer=str(external))
        assert not external.exists()
        assert not (home / "keys").exists()

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

    @pytest.mark.parametrize("stem", ["ed25519", "ed25519.key", "ed25519.pub"])
    def test_reserved_self_stem_uses_flat_key_only(self, tmp_path, stem):
        v = tmp_path / f"{stem}.vertex"
        v.write_text(f'vertex "{stem}" {{ store "./x.db" }}\n')
        ensured = ensure_signing_key(v, observer=v.stem)
        assert (keys_dir_for(v) / "ed25519.key").is_file()
        assert not (keys_dir_for(v) / v.stem).is_dir()
        public = ed25519.public_key_from_b64(ensured.public_b64)
        tick = tick_signer_for(v)
        fact = fact_signer_for(v)
        arrival = arrival_signer_for(v)
        assert tick is not None and fact is not None and arrival is not None
        assert ed25519.verify(public, tick("digest"), b"digest", domain=TICK_DOMAIN)
        assert ed25519.verify(public, fact(v.stem, "digest"), b"digest", domain=FACT_DOMAIN)
        assert ed25519.verify(
            public, arrival(v.stem, "digest"), b"digest", domain=ARRIVAL_DOMAIN
        )

    def test_missing_vertex_locator_still_mints_its_self_key(self, tmp_path):
        future = tmp_path / "future.vertex"
        ensure_signing_key(future, observer="future")
        assert (tmp_path / "keys" / "ed25519.key").exists()

    def test_refuses_case_alias_of_existing_self_locator(self, tmp_path):
        actual = tmp_path / "Alice.vertex"
        actual.write_text('vertex "Alice" { store "./a.db" }\n')
        ensure_signing_key(actual, observer="Alice")
        alias = tmp_path / "alice.vertex"
        if not alias.exists():
            pytest.skip("filesystem preserves case-distinct vertex basenames")

        with pytest.raises(ValueError, match="vertex locator.*differently spelled"):
            ensure_signing_key(alias, observer="alice")
        with pytest.raises(ValueError, match="vertex locator.*differently spelled"):
            tick_signer_for(alias)
        for factory in (fact_signer_for, arrival_signer_for):
            with pytest.raises(ValueError, match="vertex locator.*differently spelled"):
                factory(alias)

    def test_appends_to_existing_gitignore(self, tmp_path):
        v = _vertex(tmp_path)
        (tmp_path / ".gitignore").write_text("*.db\n")
        ensure_signing_key(v)
        lines = (tmp_path / ".gitignore").read_text().splitlines()
        assert lines == ["*.db", "keys/"]

    def test_refuses_symlinked_observer_directory_portably(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v, observer="Alice")
        alias = keys_dir_for(v) / "alias"
        alias.symlink_to("Alice", target_is_directory=True)

        with pytest.raises(ValueError, match="aliases existing custody"):
            ensure_signing_key(v, observer="alias")
        with pytest.raises(ValueError, match="aliases existing custody"):
            observer_keys_dir_for(v, "alias")

    def test_refuses_case_variant_alias_on_case_insensitive_filesystem(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v, observer="Alice")
        if not (keys_dir_for(v) / "alice" / "ed25519.key").exists():
            pytest.skip("filesystem preserves case-distinct observer directories")
        with pytest.raises(ValueError, match="aliases existing custody"):
            ensure_signing_key(v, observer="alice")

    def test_refuses_case_alias_parent_before_creating_nested_key(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v, observer="Alice/child")
        if not (keys_dir_for(v) / "alice").exists():
            pytest.skip("filesystem preserves case-distinct observer directories")
        with pytest.raises(ValueError, match="aliases existing custody"):
            ensure_signing_key(v, observer="alice")
        assert not (keys_dir_for(v) / "Alice" / "ed25519.key").exists()

    def test_case_alias_component_refusal_is_portable(self, tmp_path, monkeypatch):
        v = _vertex(tmp_path)
        keys = keys_dir_for(v)
        keys.mkdir()
        (keys / "Alice").mkdir()
        candidate = keys / "alice"
        original_exists = Path.exists

        def case_alias_exists(path):
            if path == candidate:
                return True
            return original_exists(path)

        monkeypatch.setattr(Path, "exists", case_alias_exists)
        with pytest.raises(ValueError, match="aliases existing custody"):
            ensure_signing_key(v, observer="alice")

    def test_case_alias_created_during_mkdir_recheck_is_portable(self, tmp_path, monkeypatch):
        v = _vertex(tmp_path)
        keys = keys_dir_for(v)
        candidate = keys / "alice"
        original_exists = Path.exists
        original_mkdir = Path.mkdir

        def case_alias_exists(path):
            if path == candidate:
                return True
            return original_exists(path)

        def race_mkdir(path, *args, **kwargs):
            if path == candidate:
                return original_mkdir(keys / "Alice", parents=True, exist_ok=True)
            return original_mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "exists", case_alias_exists)
        monkeypatch.setattr(Path, "mkdir", race_mkdir)
        with pytest.raises(ValueError, match="aliases existing custody"):
            ensure_signing_key(v, observer="alice")

    def test_refuses_regular_file_observer_component(self, tmp_path):
        v = _vertex(tmp_path)
        keys = keys_dir_for(v)
        keys.mkdir()
        (keys / "observer").write_text("not a directory")
        with pytest.raises(ValueError, match="non-directory custody component"):
            ensure_signing_key(v, observer="observer")


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

    def test_renamed_nested_self_key_is_shared_by_all_signers(self, tmp_path):
        old = tmp_path / "old.vertex"
        old.write_text('vertex "old" { store "./old.db" }\n')
        nested = ensure_signing_key(old, observer="new")
        new = tmp_path / "new.vertex"
        old.rename(new)

        # A renamed nested self key remains the one returned by mint/load;
        # do not mint a competing flat key.
        ensured = ensure_signing_key(new, observer="new")
        assert ensured.public_b64 == nested.public_b64
        assert not (keys_dir_for(new) / "ed25519.key").exists()
        public = ed25519.public_key_from_b64(ensured.public_b64)
        tick = tick_signer_for(new)
        fact = fact_signer_for(new)
        arrival = arrival_signer_for(new)
        assert tick is not None and fact is not None and arrival is not None
        assert ed25519.verify(public, tick("digest"), b"digest", domain=TICK_DOMAIN)
        assert ed25519.verify(public, fact("new", "digest"), b"digest", domain=FACT_DOMAIN)
        assert ed25519.verify(
            public, arrival("new", "digest"), b"digest", domain=ARRIVAL_DOMAIN
        )

    def test_exact_self_symlink_refuses_instead_of_minting_a_flat_key(self, tmp_path):
        vertex = _vertex(tmp_path)
        ensure_signing_key(vertex, observer="alice")
        root = keys_dir_for(vertex)
        (root / "x").symlink_to("alice", target_is_directory=True)
        original_key = (root / "alice" / "ed25519.key").read_bytes()

        with pytest.raises(ValueError, match="self observer.*symlink"):
            ensure_signing_key(vertex)
        with pytest.raises(ValueError, match="self observer.*symlink"):
            tick_signer_for(vertex)
        for factory in (fact_signer_for, arrival_signer_for):
            signer = factory(vertex)
            assert signer is not None
            with pytest.raises(ValueError, match="self observer.*symlink"):
                signer("x", "digest")
        assert not (root / "ed25519.key").exists()
        assert (root / "alice" / "ed25519.key").read_bytes() == original_key

    def test_refuses_different_flat_and_nested_self_keys(self, tmp_path):
        old = tmp_path / "old.vertex"
        old.write_text('vertex "old" { store "./old.db" }\n')
        ensure_signing_key(old, observer="new")
        new = tmp_path / "new.vertex"
        old.rename(new)
        # Construct an interrupted/manual migration with two key materials.
        from sign import ed25519 as signing

        signing.load_or_generate(keys_dir_for(new))
        with pytest.raises(ValueError, match="ambiguous self-observer custody"):
            ensure_signing_key(new, observer="new")
        with pytest.raises(ValueError, match="ambiguous self-observer custody"):
            tick_signer_for(new)
        for factory in (fact_signer_for, arrival_signer_for):
            signer = factory(new)
            assert signer is not None
            with pytest.raises(ValueError, match="ambiguous self-observer custody"):
                signer("new", "digest")

    def test_same_flat_and_nested_self_key_selects_consistently(self, tmp_path):
        v = _vertex(tmp_path)
        flat = ensure_signing_key(v, observer="x")
        nested = keys_dir_for(v) / "x"
        nested.mkdir()
        os.link(keys_dir_for(v) / "ed25519.key", nested / "ed25519.key")
        shutil.copy2(keys_dir_for(v) / "ed25519.pub", nested / "ed25519.pub")

        ensured = ensure_signing_key(v, observer="x")
        assert ensured.public_b64 == flat.public_b64
        public = ed25519.public_key_from_b64(flat.public_b64)
        tick = tick_signer_for(v)
        fact = fact_signer_for(v)
        arrival = arrival_signer_for(v)
        assert tick is not None and fact is not None and arrival is not None
        assert ed25519.verify(public, tick("digest"), b"digest", domain=TICK_DOMAIN)
        assert ed25519.verify(public, fact("x", "digest"), b"digest", domain=FACT_DOMAIN)
        assert ed25519.verify(
            public, arrival("x", "digest"), b"digest", domain=ARRIVAL_DOMAIN
        )

    def test_signer_load_paths_do_not_mint_after_a_missing_read(self, tmp_path, monkeypatch):
        v = _vertex(tmp_path)
        ensure_signing_key(v)
        key_path = keys_dir_for(v) / "ed25519.key"
        original = key_path.read_bytes()

        def missing(_key_dir):
            raise FileNotFoundError("simulated deletion race")

        monkeypatch.setattr(ed25519, "load", missing)
        assert tick_signer_for(v) is None
        for factory in (fact_signer_for, arrival_signer_for):
            signer = factory(v)
            assert signer is not None
            assert signer("x", "digest") is None
        assert key_path.read_bytes() == original


class TestFactSigner:
    def test_path_shaped_observers_cannot_borrow_other_keys(self, tmp_path):
        vertex = _vertex(tmp_path)
        ensure_signing_key(vertex)
        for factory in (fact_signer_for, arrival_signer_for):
            signer = factory(vertex)
            assert signer is not None
            for observer in ("", ".", "..", "../keys", str(tmp_path / "keys")):
                assert signer(observer, "digest") is None
                with pytest.raises(ValueError, match="observer"):
                    observer_keys_dir_for(vertex, observer)

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

    def test_refuses_alias_when_loading_existing_observer_key(self, tmp_path):
        v = _vertex(tmp_path)
        ensure_signing_key(v, observer="Alice")
        alice = keys_dir_for(v) / "alice"
        if not (alice / "ed25519.key").exists():
            alice.symlink_to("Alice", target_is_directory=True)
        for factory in (fact_signer_for, arrival_signer_for):
            signer = factory(v)
            assert signer is not None
            with pytest.raises(ValueError, match="aliases existing custody"):
                signer("alice", "digest")

    @pytest.mark.parametrize("first", ["flat", "nested"])
    def test_case_variant_nested_observer_does_not_poison_flat_self(self, tmp_path, first):
        v = tmp_path / "Alice.vertex"
        v.write_text('vertex "Alice" { store "./a.db" }\n')
        if first == "flat":
            flat = ensure_signing_key(v, observer="Alice")
            nested = ensure_signing_key(v, observer="alice")
        else:
            nested = ensure_signing_key(v, observer="alice")
            flat = ensure_signing_key(v, observer="Alice")
        assert flat.public_b64 != nested.public_b64
        self_public = ed25519.public_key_from_b64(flat.public_b64)
        nested_public = ed25519.public_key_from_b64(nested.public_b64)
        tick = tick_signer_for(v)
        fact = fact_signer_for(v)
        arrival = arrival_signer_for(v)
        assert tick is not None and fact is not None and arrival is not None
        assert ed25519.verify(self_public, tick("digest"), b"digest", domain=TICK_DOMAIN)
        assert ed25519.verify(
            self_public, fact("Alice", "digest"), b"digest", domain=FACT_DOMAIN
        )
        assert ed25519.verify(
            self_public, arrival("Alice", "digest"), b"digest", domain=ARRIVAL_DOMAIN
        )
        assert ed25519.verify(
            nested_public, fact("alice", "digest"), b"digest", domain=FACT_DOMAIN
        )
        assert ed25519.verify(
            nested_public, arrival("alice", "digest"), b"digest", domain=ARRIVAL_DOMAIN
        )


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

        verifier, _keys = arrival_verifier_for(v)
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
