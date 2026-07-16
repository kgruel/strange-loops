"""Delta-2 composition: tick signing wired through the CLI layer.

Engine takes callables (tested with fakes in libs/engine); these tests
exercise the REAL composition — libs/sign Ed25519 + the .vertex observer-key
registry + the emit/verify CLI paths (design/tick-key-custody-colocated,
design/observer-key-registry).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from engine.builder import fold_count, vertex
from sign import ed25519


def _emit(vertex_path: Path, kind: str, **payload):
    from loops.main import cmd_emit
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(vertex=None, kind=kind, parts=parts, observer="", dry_run=False)
    return cmd_emit(ns, vertex_path=vertex_path)


def _make_vertex(tmp_path: Path) -> Path:
    vpath = tmp_path / "x.vertex"
    (vertex("x").store("./x.db")
        .loop("ping", fold_count("n"), boundary_every=1)
        .write(vpath))
    return vpath


def _declare_key(vpath: Path, name: str, key_b64: str) -> None:
    vpath.write_text(
        vpath.read_text()
        + f'\nobservers {{\n  {name} {{\n    key "{key_b64}"\n  }}\n}}\n'
    )


def _make_signed_vertex(tmp_path: Path) -> Path:
    """Vertex + co-located keypair + self-observer key declaration."""
    vpath = _make_vertex(tmp_path)
    kp = ed25519.load_or_generate(tmp_path / "keys")
    _declare_key(vpath, "x", kp.public_b64)
    return vpath


class TestTickSignerComposition:
    def test_no_keys_means_no_signer(self, tmp_path):
        from custody import tick_signer_for
        vpath = _make_vertex(tmp_path)
        assert tick_signer_for(vpath) is None

    def test_emit_signs_ticks_when_key_exists(self, tmp_path):
        vpath = _make_signed_vertex(tmp_path)
        _emit(vpath, "ping", service="api")

        conn = sqlite3.connect(str(tmp_path / "x.db"))
        sigs = [r[0] for r in conn.execute("SELECT signature FROM ticks")]
        conn.close()
        assert sigs and all(s for s in sigs)

    def test_emit_without_key_appends_unsigned(self, tmp_path):
        vpath = _make_vertex(tmp_path)
        _emit(vpath, "ping", service="api")

        conn = sqlite3.connect(str(tmp_path / "x.db"))
        sigs = [r[0] for r in conn.execute("SELECT signature FROM ticks")]
        conn.close()
        assert sigs and all(s is None for s in sigs)


class TestVerifyComposition:
    def test_signed_store_verifies_against_registry(self, tmp_path, capsys):
        from loops.commands.store import _run_verify
        vpath = _make_signed_vertex(tmp_path)
        _emit(vpath, "ping", service="api")
        _emit(vpath, "ping", service="api")

        capsys.readouterr()
        rc = _run_verify([str(vpath)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "chain intact" in out
        assert "verified against registry" in out

    def test_tampered_signed_head_detected(self, tmp_path, capsys):
        """The delta-1 head gap, closed end-to-end: rewrite the newest tick's
        payload and the registry-checked signature catches it."""
        from loops.commands.store import _run_verify
        vpath = _make_signed_vertex(tmp_path)
        _emit(vpath, "ping", service="api")

        conn = sqlite3.connect(str(tmp_path / "x.db"))
        conn.execute("UPDATE ticks SET payload = '{\"n\": 999}'")
        conn.commit()
        conn.close()

        rc = _run_verify([str(vpath)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "signature invalid" in out

    def test_declared_key_with_unsigned_ticks_warns(self, tmp_path, capsys):
        """The strip-attack tripwire: registry says signing, store shows none."""
        from loops.commands.store import _run_verify
        vpath = _make_vertex(tmp_path)
        # Key declared in the registry, but no private key next to the store
        # — ticks append unsigned (also the post-total-strip appearance).
        kp = ed25519.load_or_generate(tmp_path / "elsewhere")
        _declare_key(vpath, "x", kp.public_b64)
        _emit(vpath, "ping", service="api")

        capsys.readouterr()
        rc = _run_verify([str(vpath)])
        out = capsys.readouterr().out
        assert rc == 0  # warning, not a break — could be a pre-signing store
        assert "no tick is signed" in out

    def test_raw_db_target_cannot_check_signatures(self, tmp_path, capsys):
        from loops.commands.store import _run_verify
        vpath = _make_signed_vertex(tmp_path)
        _emit(vpath, "ping", service="api")

        capsys.readouterr()
        rc = _run_verify([str(tmp_path / "x.db")])
        out = capsys.readouterr().out
        assert rc == 0
        assert "unchecked" in out

    def test_json_report_carries_signature_fields(self, tmp_path, capsys):
        from loops.commands.store import _run_verify
        vpath = _make_signed_vertex(tmp_path)
        _emit(vpath, "ping", service="api")

        capsys.readouterr()
        rc = _run_verify([str(vpath), "--json"])
        report = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert report["signed"] >= 1
        assert report["sig_checked"] is True


class TestRegistryReads:
    def test_declared_observer_keys(self, tmp_path):
        from custody import declared_observer_keys
        vpath = _make_signed_vertex(tmp_path)
        keys = declared_observer_keys(vpath)
        assert list(keys) == ["x"]
        assert len(keys["x"]) == 44

    def test_no_observers_block_is_empty_registry(self, tmp_path):
        from custody import declared_observer_keys
        vpath = _make_vertex(tmp_path)
        assert declared_observer_keys(vpath) == {}


class TestAddObserverKey:
    def test_malformed_key_rejected_before_splice(self, capsys):
        from loops.commands.add import _add_observer
        rc = _add_observer("does-not-matter", ["bob", "--key", "@@@@"])
        assert rc == 1
        assert "invalid --key" in capsys.readouterr().err

    def test_keygen_bootstraps_flat_self_observer_key(self, tmp_path, monkeypatch):
        """friction:bootstrap-tick-key-not-minted — bootstrapping a fresh store
        the documented way (`loops add <v> observer <human>/<agent> --keygen`)
        must leave the FIRST seal signed AND verifiable.

        Before the fix, --keygen for a <human>/<agent> observer minted only that
        per-observer FACT key, while tick_signer_for loads the flat
        self-observer key (keys/ed25519.key). So the first seal appended
        silently unsigned until someone separately ran --keygen for the stem.
        """
        from loops.commands.add import _add_observer
        from custody import declared_observer_keys, tick_signer_for
        from loops.commands.store import _run_verify

        vpath = _make_vertex(tmp_path)   # hand-written vertex, NO keys yet
        monkeypatch.chdir(tmp_path)      # local-first resolution finds x.vertex

        assert tick_signer_for(vpath) is None  # fresh store: pre-signature era

        rc = _add_observer("x", ["kyle/claude", "--keygen"])
        assert rc == 0

        # Both the per-observer fact key AND the flat self-observer tick key
        # are now registered — the store is fully signing-capable.
        keys = declared_observer_keys(vpath)
        assert set(keys) == {"x", "kyle/claude"}
        assert tick_signer_for(vpath) is not None

        # First seal signs (boundary_every=1 → each emit mints a tick).
        _emit(vpath, "ping", service="api")
        conn = sqlite3.connect(str(tmp_path / "x.db"))
        sigs = [r[0] for r in conn.execute("SELECT signature FROM ticks")]
        conn.close()
        assert sigs and all(s for s in sigs)

        # …and verifies against the registry.
        rc = _run_verify([str(vpath)])
        assert rc == 0

    def test_keygen_for_self_observer_does_not_double_register(
        self, tmp_path, monkeypatch
    ):
        """The self-observer --keygen path already mints+registers the flat key;
        the self-observer bootstrap must not fire a second, colliding splice."""
        from loops.commands.add import _add_observer
        from custody import declared_observer_keys, tick_signer_for

        vpath = _make_vertex(tmp_path)
        monkeypatch.chdir(tmp_path)

        rc = _add_observer("x", ["x", "--keygen"])
        assert rc == 0
        assert list(declared_observer_keys(vpath)) == ["x"]
        assert tick_signer_for(vpath) is not None

    def test_keygen_backfills_key_into_keyless_self_observer(
        self, tmp_path, monkeypatch
    ):
        """FINDING 1: a pre-existing KEYLESS self-observer declaration
        (`observers { x { } }`) must get the flat pubkey BACKFILLED. Otherwise
        the flat key mints, ticks sign with it, but the registry — which skips
        keyless observers — cannot verify them. Keying off node presence (not
        the declared key) left this broken; keying off declared_observer_keys
        fixes it.
        """
        from loops.commands.add import _add_observer
        from custody import declared_observer_keys, tick_signer_for
        from loops.commands.store import _run_verify

        vpath = _make_vertex(tmp_path)
        # Hand-written keyless self-observer declaration.
        vpath.write_text(vpath.read_text() + "\nobservers {\n  x {\n  }\n}\n")
        assert declared_observer_keys(vpath) == {}  # keyless: registry empty
        monkeypatch.chdir(tmp_path)

        rc = _add_observer("x", ["kyle/claude", "--keygen"])
        assert rc == 0

        # The stem 'x' now carries the flat pubkey (backfilled into the
        # existing node), alongside the new per-observer key.
        keys = declared_observer_keys(vpath)
        assert "x" in keys and "kyle/claude" in keys
        assert tick_signer_for(vpath) is not None

        # Signed AND verifiable — the backfilled stem key matches the flat
        # key the tick signer uses.
        _emit(vpath, "ping", service="api")
        conn = sqlite3.connect(str(tmp_path / "x.db"))
        sigs = [r[0] for r in conn.execute("SELECT signature FROM ticks")]
        conn.close()
        assert sigs and all(s for s in sigs)
        assert _run_verify([str(vpath)]) == 0

    def test_failed_keygen_add_does_not_enable_tick_signing(
        self, tmp_path, monkeypatch
    ):
        """FINDING 2 / fail-atomic: a --keygen add that FAILS (the requested
        observer is already declared) must not have enabled tick signing as a
        side effect. The self-observer bootstrap is deferred until AFTER the
        requested splice succeeds, so a failed add leaves seal behavior
        unchanged.
        """
        from loops.commands.add import _add_observer
        from custody import declared_observer_keys, tick_signer_for

        vpath = _make_vertex(tmp_path)
        # Pre-declare a bare observer so the requested add collides (bare names
        # are what the splice's duplicate-check reliably detects).
        vpath.write_text(vpath.read_text() + "\nobservers {\n  bob {\n  }\n}\n")
        monkeypatch.chdir(tmp_path)
        assert tick_signer_for(vpath) is None  # pre-signature era

        rc = _add_observer("x", ["bob", "--keygen"])
        assert rc == 1  # duplicate observer → add fails

        # No flat self-observer key registered; tick signing NOT enabled.
        assert "x" not in declared_observer_keys(vpath)
        assert tick_signer_for(vpath) is None

    def test_slashed_name_bootstrap_registers_stem_not_full_name(self, tmp_path):
        """FINDING 3 (REBUTTED): the old init._bootstrap_signing spliced the
        vertex's full `name` as a bare KDL node. For a slashed name that node
        does NOT parse, so the old path silently NEVER registered the full name
        — it registered nothing. The new code registers the vertex STEM, which
        is exactly what tick_signer_for (observer = vertex stem) verifies
        against. Evidence, not argument.
        """
        from lang import parse_vertex
        from loops.commands.add import ensure_self_observer_signing
        from custody import declared_observer_keys, tick_signer_for

        base = (
            'name "proj"\nstore "./x.db"\n'
            'loops {\n  ping {\n    fold {\n      n "count"\n    }\n  }\n}\n'
        )
        # Old behavior: bare slashed node name is unparseable → the parse-gate
        # would have refused the write → nothing registered.
        import pytest
        with pytest.raises(Exception):
            parse_vertex(
                base + 'observers {\n  team/proj {\n    key "AAAA"\n  }\n}\n'
            )

        # New behavior: stem registration, and it verifies. Mirror init's
        # slashed layout (.loops/team/proj.vertex → stem "proj").
        vdir = tmp_path / "team"
        vdir.mkdir()
        vpath = vdir / "proj.vertex"
        vpath.write_text(base)
        assert ensure_self_observer_signing(vpath) is True
        assert list(declared_observer_keys(vpath)) == ["proj"]
        assert tick_signer_for(vpath) is not None


def _seed_config_vertex(loops_home: Path, name: str = "proj") -> Path:
    """Config-level source vertex so init takes the stamp path (the
    real-world shape — the minimal stub deliberately doesn't parse)."""
    vpath = loops_home / name / f"{name}.vertex"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    (vertex(name).store(f"./data/{name}.db")
        .loop("ping", fold_count("n"), boundary_every=1)
        .write(vpath))
    return vpath


class TestInitBootstrap:
    def test_init_generates_key_gitignore_and_observer(
        self, loops_home, tmp_path, monkeypatch
    ):
        _seed_config_vertex(loops_home)
        workdir = tmp_path / "repo"
        workdir.mkdir()
        monkeypatch.chdir(workdir)  # cwd IS resolution context — isolate it

        from loops.commands.init import _init_local_vertex
        vpath = _init_local_vertex("proj")

        key_dir = workdir / ".loops" / "keys"
        assert (key_dir / "ed25519.key").exists()
        assert ((key_dir / "ed25519.key").stat().st_mode & 0o777) == 0o600

        gitignore = (workdir / ".loops" / ".gitignore").read_text()
        assert "keys/" in gitignore.split()

        from custody import declared_observer_keys, tick_signer_for
        keys = declared_observer_keys(vpath)
        assert keys["proj"] == (key_dir / "ed25519.pub").read_text().strip()
        assert tick_signer_for(vpath) is not None

    def test_init_is_idempotent(self, loops_home, tmp_path, monkeypatch):
        _seed_config_vertex(loops_home)
        workdir = tmp_path / "repo"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        from loops.commands.init import _init_local_vertex
        _init_local_vertex("proj")
        pub_before = (workdir / ".loops" / "keys" / "ed25519.pub").read_text()
        vpath = _init_local_vertex("proj")  # re-run on existing .loops

        assert (workdir / ".loops" / "keys" / "ed25519.pub").read_text() == pub_before
        from custody import declared_observer_keys
        assert list(declared_observer_keys(vpath)) == ["proj"]
        # gitignore not duplicated
        lines = (workdir / ".loops" / ".gitignore").read_text().split()
        assert lines.count("keys/") == 1
