"""S1 — genesis + absorb ceremony (SPEC §9.2 era opening).

Exercises the REAL composition: parse a .vertex → signed ``_decl.genesis``
event (whole declaration document + protocol version + era pins), the
lineage-identity / no-force / must-be-signed rules, and the write-time
reservation of the ``_decl.*`` namespace on the emit path.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pytest

from engine.builder import fold_count, vertex
from lang.document import DECL_GENESIS, DECLARATION_PROTOCOL_VERSION
from loops.commands.store import _run_absorb
from sign import ed25519


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


def _emit(vertex_path: Path, kind: str, **payload):
    from loops.main import cmd_emit
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(vertex=None, kind=kind, parts=parts, observer="", dry_run=False)
    return cmd_emit(ns, vertex_path=vertex_path)


def _genesis_row(db_path: Path) -> tuple | None:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, kind, observer, payload, signature FROM facts WHERE kind = ?",
            (DECL_GENESIS,),
        ).fetchone()
    finally:
        conn.close()


class TestAbsorbFreshStore:
    def test_genesis_written_signed_and_pinned(self, tmp_path):
        vpath = _make_signed_vertex(tmp_path)
        rc = _run_absorb(["--observer", "x"], vertex_path=vpath)
        assert rc == 0

        row = _genesis_row(tmp_path / "x.db")
        assert row is not None
        gid, kind, observer, payload_text, signature = row
        assert kind == DECL_GENESIS
        assert observer == "x"
        assert signature  # genesis MUST be signed

        payload = json.loads(payload_text)
        assert payload["protocol"] == DECLARATION_PROTOCOL_VERSION
        # Fresh store: nothing predates the genesis.
        assert payload["chain_head"] is None
        assert payload["fact_cursor"] is None
        # Whole-document set present: at minimum the vertex-defined singleton
        # and the one kind-defined loop.
        kinds = {d["kind"] for d in payload["documents"]}
        assert "_decl.vertex-defined" in kinds
        assert "_decl.kind-defined" in kinds

    def test_lineage_id_equals_genesis_fact_id(self, tmp_path, capsys):
        vpath = _make_signed_vertex(tmp_path)
        rc = _run_absorb(["--observer", "x", "--json"], vertex_path=vpath)
        assert rc == 0
        receipt = json.loads(capsys.readouterr().out)
        gid, *_ = _genesis_row(tmp_path / "x.db")
        # The genesis fact's own ULID IS the lineage id (§9.2): the receipt's
        # lineage must equal the id assigned to the stored row.
        assert receipt["lineage"] == gid
        assert len(gid) == 26  # ULID

    def test_json_receipt_shape(self, tmp_path, capsys):
        vpath = _make_signed_vertex(tmp_path)
        rc = _run_absorb(["--observer", "x", "--json"], vertex_path=vpath)
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["protocol"] == DECLARATION_PROTOCOL_VERSION
        assert out["observer"] == "x"
        assert out["signed"] is True
        assert out["dry_run"] is False
        assert out["chain_head"] is None
        assert out["fact_cursor"] is None
        gid, *_ = _genesis_row(tmp_path / "x.db")
        assert out["lineage"] == gid


class TestAbsorbPins:
    def test_pins_reflect_existing_facts_and_ticks(self, tmp_path):
        vpath = _make_signed_vertex(tmp_path)
        # boundary_every=1 → each emit also seals a signed tick.
        _emit(vpath, "ping", service="api")
        _emit(vpath, "ping", service="web")

        db = tmp_path / "x.db"
        conn = sqlite3.connect(str(db))
        newest_fact = conn.execute(
            "SELECT id FROM facts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()

        # The actual latest-chained-tick row hash — what a successor's
        # prev_hash would commit to. absorb writes no tick, so this is
        # unchanged by the absorb and must equal the pinned chain_head.
        from atoms import Fact
        from engine.sqlite_store import SqliteStore
        s = SqliteStore(
            path=db, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
        )
        expected_head = s.current_chain_head()
        s.close()
        assert expected_head is not None

        rc = _run_absorb(["--observer", "x"], vertex_path=vpath)
        assert rc == 0

        payload = json.loads(_genesis_row(db)[3])
        # fact_cursor pins the newest PRE-genesis fact (witness order).
        assert payload["fact_cursor"] == newest_fact
        # chain_head EQUALS the store's actual latest-tick chain hash.
        assert payload["chain_head"] == expected_head
        assert len(payload["chain_head"]) == 64  # sha256 hexdigest


class TestAbsorbRefusals:
    def test_double_absorb_refuses(self, tmp_path):
        vpath = _make_signed_vertex(tmp_path)
        assert _run_absorb(["--observer", "x"], vertex_path=vpath) == 0
        # Second absorb: a genesis already exists → refuse (exit 2), no --force.
        assert _run_absorb(["--observer", "x"], vertex_path=vpath) == 2
        # Still exactly one genesis.
        conn = sqlite3.connect(str(tmp_path / "x.db"))
        n = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE kind = ?", (DECL_GENESIS,)
        ).fetchone()[0]
        conn.close()
        assert n == 1

    def test_absorb_without_signing_key_refuses(self, tmp_path):
        vpath = _make_vertex(tmp_path)  # no keys, no observer key declaration
        assert _run_absorb([], vertex_path=vpath) == 2
        # Nothing written — no genesis, store never materialized by absorb.
        assert not (tmp_path / "x.db").exists() or _genesis_row(tmp_path / "x.db") is None

    def test_non_vertex_target_refuses(self, tmp_path):
        # A raw .db target has no key custody / declaration to record.
        with pytest.raises(ValueError, match="absorb requires a .vertex target"):
            _run_absorb([str(tmp_path / "x.db")])


class TestAbsorbDryRun:
    def test_dry_run_writes_nothing(self, tmp_path):
        vpath = _make_signed_vertex(tmp_path)
        rc = _run_absorb(["--observer", "x", "--dry-run"], vertex_path=vpath)
        assert rc == 0
        # No store materialized, no genesis written.
        assert not (tmp_path / "x.db").exists() or _genesis_row(tmp_path / "x.db") is None

    def test_dry_run_json_has_null_lineage(self, tmp_path, capsys):
        vpath = _make_signed_vertex(tmp_path)
        rc = _run_absorb(["--observer", "x", "-n", "--json"], vertex_path=vpath)
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["dry_run"] is True
        assert out["lineage"] is None
        assert out["signed"] is True  # would be signed


class TestEmitReservation:
    def test_emit_of_decl_kind_refuses(self, tmp_path):
        vpath = _make_vertex(tmp_path)
        # A user-supplied _decl.* kind is refused at emit (exit 2), regardless
        # of strict mode — read-side filtering is not reservation.
        rc = _emit(vpath, "_decl.genesis", topic="x")
        assert rc == 2
        # Nothing stored under the reserved kind.
        db = tmp_path / "x.db"
        if db.exists():
            assert _genesis_row(db) is None


class TestAbsorbRoundTrip:
    def test_genesis_documents_reconstruct_ast(self, tmp_path):
        from lang.document import documents_to_vertex

        vpath = _make_signed_vertex(tmp_path)
        assert _run_absorb(["--observer", "x"], vertex_path=vpath) == 0
        payload = json.loads(_genesis_row(tmp_path / "x.db")[3])
        # Project the absorbed document set back to an AST (modulo residence).
        reconstructed = documents_to_vertex(payload["documents"])
        assert reconstructed.name == "x"
        assert "ping" in reconstructed.loops
