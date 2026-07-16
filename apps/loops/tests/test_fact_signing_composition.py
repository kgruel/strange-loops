"""Delta-3 composition: fact authorship signing wired through the CLI layer.

Engine takes callables (tested with fakes in libs/engine); these tests
exercise the REAL composition — libs/sign Ed25519 under FACT_DOMAIN, the
per-observer key layout ``keys/<observer>/`` with flat-layout fallback for
the self-observer, the .vertex observer-key registry as exact-key trust
anchor, and the emit/verify CLI paths
(design/fact-signature-at-store-column,
design/fact-signing-per-observer-keys).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from engine.builder import fold_count, vertex
from sign import ed25519


def _emit(vertex_path: Path, kind: str, observer: str = "", **payload):
    from loops.main import cmd_emit
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(
        vertex=None, kind=kind, parts=parts, observer=observer, dry_run=False
    )
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


def _fact_sigs(tmp_path: Path) -> list[tuple[str, str | None]]:
    conn = sqlite3.connect(str(tmp_path / "x.db"))
    try:
        return list(conn.execute("SELECT observer, signature FROM facts"))
    finally:
        conn.close()


class TestFactSignerResolution:
    def test_no_keys_dir_means_no_signer(self, tmp_path):
        from custody import fact_signer_for
        vpath = _make_vertex(tmp_path)
        assert fact_signer_for(vpath) is None

    def test_flat_key_serves_self_observer_only(self, tmp_path):
        from custody import fact_signer_for
        vpath = _make_vertex(tmp_path)
        ed25519.load_or_generate(tmp_path / "keys")  # flat delta-2 layout
        signer = fact_signer_for(vpath)
        assert signer is not None
        assert signer("x", "digest") is not None       # self-observer (stem)
        assert signer("someone-else", "digest") is None

    def test_per_observer_dir_serves_that_observer(self, tmp_path):
        from custody import fact_signer_for
        vpath = _make_vertex(tmp_path)
        ed25519.load_or_generate(tmp_path / "keys" / "kyle")
        signer = fact_signer_for(vpath)
        assert signer is not None
        assert signer("kyle", "digest") is not None
        assert signer("x", "digest") is None  # no flat key, self unkeyed

    def test_slashed_observer_names_nest(self, tmp_path):
        from custody import fact_signer_for
        vpath = _make_vertex(tmp_path)
        ed25519.load_or_generate(tmp_path / "keys" / "kyle" / "loops-claude")
        signer = fact_signer_for(vpath)
        assert signer is not None
        assert signer("kyle/loops-claude", "digest") is not None

    def test_empty_and_traversal_observers_never_sign(self, tmp_path):
        """The path-join footgun: keys_root/'' collapses to the flat layout
        — an anonymous writer must not receive the vertex key's authorship
        claim (observation implementation/empty-observer-path-join-footgun)."""
        from custody import fact_signer_for
        vpath = _make_vertex(tmp_path)
        ed25519.load_or_generate(tmp_path / "keys")
        signer = fact_signer_for(vpath)
        assert signer is not None
        assert signer("", "digest") is None
        assert signer("../x", "digest") is None

    def test_deterministic_signature(self, tmp_path):
        from custody import fact_signer_for
        vpath = _make_vertex(tmp_path)
        ed25519.load_or_generate(tmp_path / "keys" / "kyle")
        signer = fact_signer_for(vpath)
        assert signer is not None
        assert signer("kyle", "d") == signer("kyle", "d")


class TestEmitSignsFactsEndToEnd:
    def test_keyed_observer_fact_signed_and_verifies(self, tmp_path, capsys):
        from loops.commands.store import _run_verify
        vpath = _make_vertex(tmp_path)
        kp = ed25519.load_or_generate(tmp_path / "keys" / "kyle")
        _declare_key(vpath, "kyle", kp.public_b64)
        _emit(vpath, "ping", observer="kyle", service="api")

        rows = _fact_sigs(tmp_path)
        assert rows == [("kyle", rows[0][1])] and rows[0][1] is not None

        capsys.readouterr()
        rc = _run_verify([str(vpath)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "authorship   1/1 facts signed" in out

    def test_unkeyed_observer_fact_unsigned(self, tmp_path):
        vpath = _make_vertex(tmp_path)
        ed25519.load_or_generate(tmp_path / "keys" / "kyle")
        # An observer that passes emit validation but holds no key here.
        _declare_key(vpath, "visitor", ed25519.load_or_generate(
            tmp_path / "elsewhere").public_b64)
        _emit(vpath, "ping", observer="visitor", service="api")
        rows = _fact_sigs(tmp_path)
        assert rows[0][1] is None

    def test_tampered_fact_fails_verify(self, tmp_path, capsys):
        from loops.commands.store import _run_verify
        vpath = _make_vertex(tmp_path)
        kp = ed25519.load_or_generate(tmp_path / "keys" / "kyle")
        _declare_key(vpath, "kyle", kp.public_b64)
        _emit(vpath, "ping", observer="kyle", service="api")

        conn = sqlite3.connect(str(tmp_path / "x.db"))
        conn.execute("UPDATE facts SET payload = '{\"service\": \"forged\"}'")
        conn.commit()
        conn.close()

        capsys.readouterr()
        rc = _run_verify([str(vpath)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "FACT SIGNATURES BROKEN" in out or "signature invalid" in out

    def test_wrong_observer_key_is_not_authorship(self, tmp_path, capsys):
        """Exact-key verification: claude's valid signature attributed to
        kyle is a break — no any-key relaxation on the fact path."""
        from loops.commands.store import _run_verify
        vpath = _make_vertex(tmp_path)
        kp_kyle = ed25519.load_or_generate(tmp_path / "keys" / "kyle")
        kp_claude = ed25519.load_or_generate(tmp_path / "keys" / "claude")
        _declare_key(vpath, "kyle", kp_kyle.public_b64)
        _declare_key(vpath, "claude", kp_claude.public_b64)
        _emit(vpath, "ping", observer="claude", service="api")

        conn = sqlite3.connect(str(tmp_path / "x.db"))
        conn.execute("UPDATE facts SET observer = 'kyle'")
        conn.commit()
        conn.close()

        capsys.readouterr()
        rc = _run_verify([str(vpath)])
        assert rc == 1

    def test_json_report_carries_fact_signature_block(self, tmp_path, capsys):
        from loops.commands.store import _run_verify
        vpath = _make_vertex(tmp_path)
        kp = ed25519.load_or_generate(tmp_path / "keys" / "kyle")
        _declare_key(vpath, "kyle", kp.public_b64)
        _emit(vpath, "ping", observer="kyle", service="api")

        capsys.readouterr()
        rc = _run_verify([str(vpath), "--json"])
        report = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert report["fact_signatures"]["signed"] == 1
        assert report["fact_signatures"]["sig_checked"] is True
        assert report["fact_signatures"]["observers"]["kyle"]["signed"] == 1


class TestKeygenPerObserver:
    def test_ensure_signing_key_observer_layout(self, tmp_path):
        from custody import ensure_signing_key
        vpath = _make_vertex(tmp_path)
        kp = ensure_signing_key(vpath, observer="kyle")
        assert (tmp_path / "keys" / "kyle" / "ed25519.key").exists()
        assert len(kp.public_b64) == 44

    def test_self_observer_keeps_flat_layout(self, tmp_path):
        from custody import ensure_signing_key
        vpath = _make_vertex(tmp_path)
        ensure_signing_key(vpath, observer="x")  # vertex stem
        assert (tmp_path / "keys" / "ed25519.key").exists()
        assert not (tmp_path / "keys" / "x").exists()

    def test_add_observer_slashed_name_splices_quoted(self, tmp_path):
        """Slashed observers (kyle/loops-claude) must splice as quoted KDL
        node names — bare they fail the parse-gate AFTER keygen minted the
        key, stranding an unregistered (unverifiable) signer."""
        from loops.commands.add import _add_observer
        from custody import declared_observer_keys
        vpath = _make_vertex(tmp_path)
        rc = _add_observer(str(vpath), ["kyle/loops-claude", "--keygen"])
        assert rc == 0
        keys = declared_observer_keys(vpath)
        assert "kyle/loops-claude" in keys
        assert (tmp_path / "keys" / "kyle" / "loops-claude" / "ed25519.key").exists()
