"""Witness positions — the read-path temporal cursor (0.8.0 session 1, E1).

Proves the engine `at=` selector: a cursor denotes the inclusive witness prefix
(`rowid <= resolved`), identity is a fact id resolved by primary-key lookup only
(A3), the receipt-group guard refuses mid-ceremony positions at the engine seam
(A2), unadopted stores carry the marker (N1), and ontology resolves from the
same prefix — equal cursors, one position (SPEC §9.3).

Scratch stores in tmp_path only; never touches a live store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact
from lang import parse_vertex_file
from lang.ast import FoldBy
from lang.document import (
    DECL_KIND_DEFINED,
    Change,
    genesis_payload,
    vertex_to_documents,
)

from engine.declaration import (
    Unhistorized,
    load_declaration,
    load_declaration_status,
    resolve_declaration_documents,
)
from engine.sqlite_store import SqliteStore, gen_id
from engine.witness import (
    GENESIS_SENTINEL,
    MidReceiptGroupPosition,
    UnknownWitnessHandle,
    WitnessPosition,
    receipt_group_span,
    resolve_witness_position,
)

_VERTEX_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }}
             search "message" }}
  thread {{ fold {{ items "by" "name" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    return vpath, store


def _fresh_store(store: Path) -> None:
    """Create an empty pre-genesis store (schema only, no genesis)."""
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()


def _absorb(vpath: Path, store: Path) -> str:
    ast = parse_vertex_file(vpath)
    docs = genesis_payload(ast)["documents"]
    s = SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    lineage = s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)["lineage"]
    s.close()
    return lineage


def _append(store: Path, kind: str, ts: float, *, fid: str | None = None, **payload) -> str:
    """Append a fact at a controlled ts; returns the (append-ordered) fact id."""
    conn = sqlite3.connect(str(store))
    fid = fid or gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (fid, kind, ts, "kyle", "", json.dumps(payload)),
    )
    conn.commit()
    conn.close()
    return fid


def _rowid_of(store: Path, fid: str) -> int:
    conn = sqlite3.connect(str(store))
    r = conn.execute("SELECT rowid FROM facts WHERE id = ?", (fid,)).fetchone()
    conn.close()
    return r[0]


# ---------------------------------------------------------------------------
# Address resolution — head / sentinel / fact id, primary-key lookup only (A3)
# ---------------------------------------------------------------------------


class TestResolveAddress:
    def test_head_captures_newest_rowid(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        last = _append(store, "decision", 101, topic="b")
        pos = resolve_witness_position(store, "head")
        assert pos.fact_id == last
        assert pos.rowid == _rowid_of(store, last)
        assert pos.seq == 2  # two rows at-or-before head

    def test_genesis_sentinel_is_empty_prefix(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, GENESIS_SENTINEL)
        assert pos.fact_id == GENESIS_SENTINEL
        assert pos.rowid == 0
        assert pos.seq == 0

    def test_head_on_empty_store_is_empty_prefix(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        pos = resolve_witness_position(store, "head")
        assert pos.rowid == 0 and pos.fact_id == GENESIS_SENTINEL

    def test_fact_id_resolves_by_primary_key(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        first = _append(store, "decision", 100, topic="a")
        _append(store, "decision", 101, topic="b")
        pos = resolve_witness_position(store, first)
        assert pos.rowid == _rowid_of(store, first)
        assert pos.seq == 1

    def test_unknown_handle_refuses(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with pytest.raises(UnknownWitnessHandle):
            resolve_witness_position(store, "01NONEXISTENTIDNOTHERE00000")

    def test_seq_counts_decl_rows_too(self, tmp_path):
        # seq is a receipt ordinal over ALL rows (incl _decl) — the seq:N form.
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)  # genesis is rowid 1 (_decl.genesis)
        last = _append(store, "decision", 100, topic="a")  # rowid 2
        pos = resolve_witness_position(store, last)
        assert pos.seq == 2  # genesis + the decision


# ---------------------------------------------------------------------------
# Adoption / lineage marker (N1)
# ---------------------------------------------------------------------------


class TestAdoption:
    def test_pre_genesis_store_is_unadopted(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, "head")
        assert pos.unadopted is True and pos.lineage is None
        # In-session position still works everywhere (N1).
        assert pos.rowid == 1

    def test_adopted_store_carries_lineage(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, "head")
        assert pos.unadopted is False and pos.lineage == lineage


# ---------------------------------------------------------------------------
# Tick anchor (A12) — last sealed tick at-or-before the position
# ---------------------------------------------------------------------------


class TestAnchor:
    def test_no_ticks_no_anchor(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        assert resolve_witness_position(store, "head").anchor is None

    def test_anchor_is_last_sealed_tick_before_position(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append(store, "decision", 101, topic="b")  # head advances past f1
        # A tick whose window closed at f1 (its fact_cursor).
        conn = sqlite3.connect(str(store))
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload, fact_cursor) "
            "VALUES (?, 't', 150.0, 0.0, '', '{}', ?)",
            (gen_id(), f1),
        )
        conn.commit()
        conn.close()
        # Position at head (f2) — the anchor is the tick sealing f1.
        pos = resolve_witness_position(store, "head")
        assert pos.anchor is not None
        assert pos.anchor.fact_cursor == f1 and pos.anchor.name == "t"
        # Position AT f1 — still anchored (f1 rowid <= position rowid).
        assert resolve_witness_position(store, f1).anchor is not None
        # Position at the empty prefix — no sealed tick precedes it.
        assert resolve_witness_position(store, GENESIS_SENTINEL).anchor is None


# ---------------------------------------------------------------------------
# Receipt-group guard (A2) — refuse-on-ambiguity at the engine selector
# ---------------------------------------------------------------------------


class TestReceiptGroupGuard:
    def _ceremony_store(self, tmp_path) -> tuple[Path, Path, list[int]]:
        """A store whose lineage has a REAL 2-row edit ceremony (one absorb_edit).

        Returns (vpath, store, [row1, row2]) — the two contiguous _decl rows.
        """
        vpath = tmp_path / "x.vertex"
        store = tmp_path / "x.db"
        vpath.write_text(
            f'name "x"\nstore "{store}"\n'
            'loops {\n  a { fold { n "inc" } }\n  b { fold { n "inc" } }\n}\n'
            'observers { kyle { key "AAAA" } }\n'
        )
        ast = parse_vertex_file(vpath)
        s = SqliteStore(
            path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
        )
        s.absorb_genesis(
            [d.as_json() for d in vertex_to_documents(ast)],
            observer="kyle",
            fact_signer=_signer,
        )
        # One ceremony, two subjects → two _decl.kind-defined rows, shared ts.
        s.absorb_edit(
            [
                Change(kind=DECL_KIND_DEFINED, subject="a",
                       payload={"folds": [], "order": 0}, annotation="modified"),
                Change(kind=DECL_KIND_DEFINED, subject="b",
                       payload={"folds": [], "order": 1}, annotation="modified"),
            ],
            observer="kyle",
            fact_signer=_signer,
        )
        s.close()
        conn = sqlite3.connect(str(store))
        rows = [
            r[0]
            for r in conn.execute(
                "SELECT rowid FROM facts WHERE kind = ? ORDER BY rowid",
                (DECL_KIND_DEFINED,),
            ).fetchall()
        ]
        conn.close()
        return vpath, store, rows

    def test_ceremony_writes_a_two_row_group(self, tmp_path):
        _vpath, store, rows = self._ceremony_store(tmp_path)
        assert len(rows) == 2 and rows[1] == rows[0] + 1  # contiguous
        conn = sqlite3.connect(str(store))
        try:
            # Strictly inside the group (at row1) → span detected.
            assert receipt_group_span(conn, rows[0]) == (rows[0], rows[1])
            # At the group's last row → complete → no span.
            assert receipt_group_span(conn, rows[1]) is None
            # Before / after the group → no span.
            assert receipt_group_span(conn, rows[0] - 1) is None
            assert receipt_group_span(conn, rows[1] + 1) is None
        finally:
            conn.close()

    def test_resolve_at_mid_group_refuses(self, tmp_path):
        _vpath, store, rows = self._ceremony_store(tmp_path)
        conn = sqlite3.connect(str(store))
        first_id = conn.execute(
            "SELECT id FROM facts WHERE rowid = ?", (rows[0],)
        ).fetchone()[0]
        last_id = conn.execute(
            "SELECT id FROM facts WHERE rowid = ?", (rows[1],)
        ).fetchone()[0]
        conn.close()
        # Naming the FIRST ceremony row = mid-group → refuse with teaching.
        with pytest.raises(MidReceiptGroupPosition):
            resolve_witness_position(store, first_id)
        # Naming the LAST row = complete ceremony → resolves fine (head snaps
        # after a completed ceremony only).
        pos = resolve_witness_position(store, last_id)
        assert pos.rowid == rows[1]

    def test_ontology_seam_reguards_a_handbuilt_position(self, tmp_path):
        # A raw mid-group WitnessPosition that bypasses the address resolver must
        # STILL be refused at the ontology seam (A2↔A8 placement gap).
        _vpath, store, rows = self._ceremony_store(tmp_path)
        rogue = WitnessPosition(
            fact_id="rogue", rowid=rows[0], seq=rows[0],
            lineage=None, unadopted=True, anchor=None,
        )
        with pytest.raises(MidReceiptGroupPosition):
            resolve_declaration_documents(store, at=rogue)


# ---------------------------------------------------------------------------
# Equal-cursors ontology — a _decl row inside/outside the prefix flips meaning
# ---------------------------------------------------------------------------


def _rekey(store: Path, lineage: str, ts: float) -> str:
    """Overlay moving `decision`'s fold key topic→name; returns the row id."""
    fid = "rekey-decision"
    _append(
        store, DECL_KIND_DEFINED, ts, fid=fid,
        lineage=lineage, subject="decision",
        payload={"order": 0, "search": ["message"],
                 "folds": [{"target": "items", "op": {"op": "by", "key_field": "name"}}]},
    )
    return fid


def _decision_key_field(ast) -> str:
    op = ast.loops["decision"].folds[0].op
    assert isinstance(op, FoldBy)
    return op.key_field


class TestEqualCursorsOntology:
    def test_decl_row_inside_prefix_flips_key(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)  # genesis rowid 1
        rekey_id = _rekey(store, lineage, ts=1000.0)  # rowid 2 (topic→name)
        rekey_rowid = _rowid_of(store, rekey_id)

        # A position AT genesis (rowid 1) sees the genesis ontology (topic); the
        # rekey lives at rowid 2, outside the genesis prefix.
        at_genesis = WitnessPosition(
            fact_id="g", rowid=1, seq=1, lineage=lineage,
            unadopted=False, anchor=None,
        )
        at_rekey = resolve_witness_position(store, rekey_id)  # rowid 2

        assert _decision_key_field(load_declaration(vpath, at=at_genesis)) == "topic"
        assert _decision_key_field(load_declaration(vpath, at=at_rekey)) == "name"
        # Head sees the rekey too.
        assert _decision_key_field(load_declaration(vpath)) == "name"
        assert rekey_rowid == 2

    def test_position_before_genesis_is_unhistorized(self, tmp_path):
        # A13 witness variant: the position predates the genesis ROWID → floor.
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)  # genesis rowid 1
        empty = resolve_witness_position(store, GENESIS_SENTINEL)  # rowid 0
        docs = resolve_declaration_documents(store, at=empty)
        assert isinstance(docs, Unhistorized)
        _ast, status = load_declaration_status(vpath, at=empty)
        assert status == "unhistorized"


# ---------------------------------------------------------------------------
# Honesty status on the cursor output contract (N3)
# ---------------------------------------------------------------------------


class TestHonestyStatus:
    def test_pre_genesis_store_reports_file_pre_genesis(self, tmp_path):
        # The dominant live case: no lineage opened → the CURRENT file answers,
        # and the status says so rather than silently retro-claiming.
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, f1)
        _ast, status = load_declaration_status(vpath, at=pos)
        assert status == "file-pre-genesis"

    def test_adopted_store_reports_store(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        f1 = _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, f1)
        _ast, status = load_declaration_status(vpath, at=pos)
        assert status == "store"


# ---------------------------------------------------------------------------
# Mutual exclusion (A8)
# ---------------------------------------------------------------------------


def test_as_of_and_at_are_mutually_exclusive(tmp_path):
    vpath = tmp_path / "t.vertex"
    store = tmp_path / "t.db"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    _fresh_store(store)
    pos = resolve_witness_position(store, GENESIS_SENTINEL)
    with pytest.raises(ValueError):
        resolve_declaration_documents(store, as_of=100.0, at=pos)
