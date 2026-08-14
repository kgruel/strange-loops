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

from engine import vertex_fold
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
    WitnessLineageMismatch,
    WitnessPosition,
    WitnessResolutionError,
    durable_handle,
    receipt_group_span,
    resolve_cut_summary,
    resolve_witness_position,
    verify_position_for_store,
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


def _append_tick(store: Path, name: str, ts: float, *, fact_cursor: str | None) -> str:
    """Append a tick sealing ``fact_cursor`` — a SEPARATE connection each
    call, the same shape a real concurrent writer (a different process)
    would use, rather than reusing whatever connection a caller has open."""
    conn = sqlite3.connect(str(store))
    tid = gen_id()
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload, fact_cursor) "
        "VALUES (?, ?, ?, 0.0, '', '{}', ?)",
        (tid, name, ts, fact_cursor),
    )
    conn.commit()
    conn.close()
    return tid


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
        """Kills mutant replacing UnknownWitnessHandle error message with None at witness.py:534."""
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with pytest.raises(UnknownWitnessHandle, match="no fact with id '01NONEXISTENTIDNOTHERE00000' in this store"):
            resolve_witness_position(store, "01NONEXISTENTIDNOTHERE00000")

    def test_resolve_witness_position_invalid_store_raises(self, tmp_path):
        """Kills mutant replacing invalid store error message with None in resolve_witness_position at witness.py:380."""
        with pytest.raises(WitnessResolutionError, match="is not a usable store — cannot resolve a witness position"):
            resolve_witness_position(tmp_path / "nope.db", "head")

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
        assert pos.anchor.fact_cursor == f1 and pos.anchor.name == "t" and pos.anchor.ts == 150.0
        # Position AT f1 — still anchored (f1 rowid <= position rowid).
        at_f1 = resolve_witness_position(store, f1)
        assert at_f1.anchor is not None
        assert at_f1.anchor.ts == 150.0 and at_f1.anchor.name == "t"
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
        """Kills mutant replacing span[0] with span[1] in MidReceiptGroupPosition error message at witness.py:309."""
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
        with pytest.raises(
            MidReceiptGroupPosition,
            match=f"rowids {rows[0]}\\.\\.{rows[1]}",
        ):
            resolve_witness_position(store, first_id)
        # Naming the LAST row = complete ceremony → resolves fine (head snaps
        # after a completed ceremony only).
        pos = resolve_witness_position(store, last_id)
        assert pos.rowid == rows[1]

    def test_receipt_group_span_requires_contiguous_rowids_and_matching_ts(self, tmp_path):
        """Kills 'and' -> 'or' mutant at witness.py:234 in receipt_group_span."""
        store = tmp_path / "span_test.db"
        _fresh_store(store)
        # Row 1: _decl at ts 100
        _append(store, DECL_KIND_DEFINED, 100.0, lineage="L", subject="a", payload={"folds": [], "order": 0})
        # Row 2: regular fact at ts 100
        _append(store, "decision", 100.0, topic="mid")
        # Row 3: _decl at ts 100 (non-contiguous rowids 1 and 3)
        _append(store, DECL_KIND_DEFINED, 100.0, lineage="L", subject="b", payload={"folds": [], "order": 1})

        conn = sqlite3.connect(str(store))
        try:
            # Non-contiguous _decl rows must not be grouped together
            assert receipt_group_span(conn, 1) is None
        finally:
            conn.close()

        # Now test contiguous rowids but different timestamps
        store2 = tmp_path / "span_test2.db"
        _fresh_store(store2)
        _append(store2, DECL_KIND_DEFINED, 100.0, lineage="L", subject="a", payload={"folds": [], "order": 0})
        _append(store2, DECL_KIND_DEFINED, 200.0, lineage="L", subject="b", payload={"folds": [], "order": 1})
        conn2 = sqlite3.connect(str(store2))
        try:
            # Different ts must not be grouped together
            assert receipt_group_span(conn2, 1) is None
        finally:
            conn2.close()

    def test_receipt_group_span_extracts_and_distinguishes_lineages(self, tmp_path):
        """Kills mutants replacing 'lineage' key in _lineage_of at witness.py:200."""
        store = tmp_path / "lineage_span.db"
        _fresh_store(store)
        # Two contiguous _decl rows at same ts but DIFFERENT lineages
        _append(store, DECL_KIND_DEFINED, 100.0, lineage="L1", subject="a", payload={"lineage": "L1", "folds": [], "order": 0})
        _append(store, DECL_KIND_DEFINED, 100.0, lineage="L2", subject="b", payload={"lineage": "L2", "folds": [], "order": 1})

        conn = sqlite3.connect(str(store))
        try:
            # Different lineages -> no span
            assert receipt_group_span(conn, 1) is None
        finally:
            conn.close()

        # Two contiguous _decl rows at same ts and SAME lineage
        store2 = tmp_path / "lineage_span2.db"
        _fresh_store(store2)
        _append(store2, DECL_KIND_DEFINED, 100.0, lineage="L1", subject="a", payload={"lineage": "L1", "folds": [], "order": 0})
        _append(store2, DECL_KIND_DEFINED, 100.0, lineage="L1", subject="b", payload={"lineage": "L1", "folds": [], "order": 1})
        conn2 = sqlite3.connect(str(store2))
        try:
            assert receipt_group_span(conn2, 1) == (1, 2)
        finally:
            conn2.close()

    def test_ontology_seam_reguards_a_handbuilt_position(self, tmp_path):
        # A raw mid-group WitnessPosition that bypasses the address resolver must
        # STILL be refused at the ontology seam (A2↔A8 placement gap).
        _vpath, store, rows = self._ceremony_store(tmp_path)
        rogue = WitnessPosition(
            fact_id="rogue", rowid=rows[0], seq=rows[0],
            lineage=None, unadopted=True, anchor=None, store=str(store.resolve()),
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
            unadopted=False, anchor=None, store=str(store.resolve()),
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


def test_load_declaration_status_mutual_exclusion_on_early_return(tmp_path):
    # Review finding 4: the exclusivity check must fire even on the
    # file-pre-genesis early-return path (which never reaches the resolver).
    vpath = tmp_path / "t.vertex"
    store = tmp_path / "t.db"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    _fresh_store(store)  # pre-genesis → load_declaration_status early-returns
    pos = resolve_witness_position(store, GENESIS_SENTINEL)
    with pytest.raises(ValueError):
        load_declaration_status(vpath, as_of=100.0, at=pos)


# ---------------------------------------------------------------------------
# Lineage-qualified handles (A10) — review finding 1
# ---------------------------------------------------------------------------


class TestLineageQualification:
    def test_position_records_its_source_store(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, "head")
        assert pos.store == str(store.resolve())

    def test_verify_accepts_same_store(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, "head")
        verify_position_for_store(pos, store)  # no raise

    def test_unadopted_position_refused_on_a_different_store(self, tmp_path):
        """Kills mutant replacing unadopted mismatch error message with None at witness.py:494."""
        va = tmp_path / "a.vertex"
        sa = tmp_path / "a.db"
        va.write_text(_VERTEX_KDL.format(store=sa))
        _fresh_store(sa)
        _append(sa, "decision", 100, topic="a")
        pos_a = resolve_witness_position(sa, "head")

        vb = tmp_path / "b.vertex"
        sb = tmp_path / "b.db"
        vb.write_text(_VERTEX_KDL.format(store=sb))
        _fresh_store(sb)
        _append(sb, "decision", 100, topic="b")

        with pytest.raises(WitnessLineageMismatch, match="an UNADOPTED handle is session-local to its own store"):
            vertex_fold(vb, at=pos_a)

    def test_adopted_position_refused_on_a_different_lineage(self, tmp_path):
        """Kills mutant replacing lineage mismatch error message with None at witness.py:506."""
        va = tmp_path / "a.vertex"
        sa = tmp_path / "a.db"
        va.write_text(_VERTEX_KDL.format(store=sa))
        _absorb(va, sa)
        _append(sa, "decision", 100, topic="a")
        pos_a = resolve_witness_position(sa, "head")
        assert pos_a.lineage is not None  # adopted

        vb = tmp_path / "b.vertex"
        sb = tmp_path / "b.db"
        vb.write_text(_VERTEX_KDL.format(store=sb))
        _absorb(vb, sb)  # a DIFFERENT genesis → different lineage
        _append(sb, "decision", 100, topic="b")

        with pytest.raises(WitnessLineageMismatch, match="does not match this store's lineage"):
            vertex_fold(vb, at=pos_a)

    def test_vertex_facts_also_verifies(self, tmp_path):
        from engine import vertex_facts

        va = tmp_path / "a.vertex"
        sa = tmp_path / "a.db"
        va.write_text(_VERTEX_KDL.format(store=sa))
        _fresh_store(sa)
        _append(sa, "decision", 100, topic="a")
        pos_a = resolve_witness_position(sa, "head")

        vb = tmp_path / "b.vertex"
        sb = tmp_path / "b.db"
        vb.write_text(_VERTEX_KDL.format(store=sb))
        _fresh_store(sb)
        _append(sb, "decision", 100, topic="b")

        with pytest.raises(WitnessLineageMismatch):
            vertex_facts(vb, 0.0, 1e12, at=pos_a)


# ---------------------------------------------------------------------------
# Guard is unconditional — pre-genesis / imported ceremonies (review finding 2)
# ---------------------------------------------------------------------------


class TestPreGenesisGuard:
    def _foreign_group(self, store: Path) -> list[int]:
        """Insert a 2-row foreign ceremony (shared ts+lineage, contiguous) with
        NO own genesis — the imported-history case. Returns the two rowids."""
        _append(store, DECL_KIND_DEFINED, 500.0,
                lineage="foreign", subject="a", payload={"folds": [], "order": 0})
        _append(store, DECL_KIND_DEFINED, 500.0,
                lineage="foreign", subject="b", payload={"folds": [], "order": 1})
        conn = sqlite3.connect(str(store))
        rows = [r[0] for r in conn.execute(
            "SELECT rowid FROM facts WHERE kind = ? ORDER BY rowid",
            (DECL_KIND_DEFINED,)).fetchall()]
        conn.close()
        return rows

    def test_mid_group_refused_without_own_genesis(self, tmp_path):
        # The store has _decl ceremony rows but NO own _decl.genesis. Previously
        # resolve_declaration_documents returned None before reaching the guard;
        # now the guard runs unconditionally, so a mid-group position is refused.
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        rows = self._foreign_group(store)
        assert rows[1] == rows[0] + 1  # contiguous
        rogue = WitnessPosition(
            fact_id="rogue", rowid=rows[0], seq=rows[0], lineage=None,
            unadopted=True, anchor=None, store=str(store.resolve()),
        )
        with pytest.raises(MidReceiptGroupPosition):
            resolve_declaration_documents(store, at=rogue)

    def test_complete_group_position_still_returns_pre_genesis(self, tmp_path):
        # Precision check: a position AT the ceremony's last row is complete, so
        # the guard does NOT fire — and with no own genesis the resolver returns
        # None (pre-genesis) as before.
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        rows = self._foreign_group(store)
        ok = WitnessPosition(
            fact_id="ok", rowid=rows[1], seq=rows[1], lineage=None,
            unadopted=True, anchor=None, store=str(store.resolve()),
        )
        assert resolve_declaration_documents(store, at=ok) is None


# ---------------------------------------------------------------------------
# Durable-handle serialization (A10, capstone B1a)
# ---------------------------------------------------------------------------


class TestDurableHandle:
    def test_adopted_yields_lineage_qualified_handle(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        lineage = _absorb(vpath, store)
        f1 = _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, f1)
        assert durable_handle(pos) == f"fact:{lineage}/{f1}"

    def test_unadopted_refuses_durable_serialization(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        pos = resolve_witness_position(store, "head")
        assert durable_handle(pos) is None  # session-local, not portable (N1)

    def test_genesis_sentinel_has_no_durable_handle(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _absorb(vpath, store)
        pos = resolve_witness_position(store, GENESIS_SENTINEL)
        assert durable_handle(pos) is None

    def test_unadopted_flag_with_non_none_lineage_refuses_durable_handle(self, tmp_path):
        """Kills 'or' -> 'and' mutant on unadopted flag check in durable_handle at witness.py:564."""
        pos = WitnessPosition(
            fact_id="f1",
            rowid=1,
            seq=1,
            lineage="some-lineage",
            unadopted=True,
            anchor=None,
            store="/dummy/path",
        )
        assert durable_handle(pos) is None


# ---------------------------------------------------------------------------
# Cross-store re-resolution (A10, capstone B1c) — never reuse the source rowid
# ---------------------------------------------------------------------------


def _mirror_lineage(src: Path, dst: Path, lineage: str) -> None:
    """Simulate a within-lineage merge: copy src's genesis row into dst and
    stamp dst's own_lineage to the SAME lineage."""
    sconn = sqlite3.connect(str(src))
    grow = sconn.execute(
        "SELECT id, kind, ts, observer, origin, payload, signature "
        "FROM facts WHERE id = ?",
        (lineage,),
    ).fetchone()
    sconn.close()
    dconn = sqlite3.connect(str(dst))
    dconn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        grow,
    )
    dconn.execute(
        "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    dconn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('own_lineage', ?)",
        (lineage,),
    )
    dconn.commit()
    dconn.close()


class TestCrossStoreReResolution:
    def test_same_lineage_reresolves_to_target_rowid(self, tmp_path):
        # The capstone B1c hole: a fact copied by merge into a sibling store sits
        # at a DIFFERENT append position there. A handle minted in store A must
        # re-resolve fact_id in store B (target rowid), never reuse A's rowid.
        va = tmp_path / "a.vertex"
        sa = tmp_path / "a.db"
        va.write_text(_VERTEX_KDL.format(store=sa))
        lineage = _absorb(va, sa)  # genesis rowid 1 in A
        f1 = _append(sa, "decision", 100, topic="a")  # rowid 2 in A
        pos_a = resolve_witness_position(sa, f1)
        assert pos_a.rowid == 2 and pos_a.lineage == lineage and not pos_a.unadopted

        sb = tmp_path / "b.db"
        _fresh_store(sb)
        _mirror_lineage(sa, sb, lineage)  # genesis rowid 1 in B, same lineage
        _append(sb, "decision", 50, topic="filler")  # rowid 2 in B
        _append(sb, "decision", 100, topic="a", fid=f1)  # SAME id, rowid 3 in B

        applied = verify_position_for_store(pos_a, sb)
        assert applied.rowid == 3  # the TARGET rowid, not the source rowid 2
        assert applied.store == str(sb.resolve())
        assert applied.fact_id == f1 and applied.lineage == lineage

    def test_same_lineage_handle_absent_in_target_refuses(self, tmp_path):
        # A lineage-qualified handle whose fact was NOT merged into the target
        # doesn't resolve there — honest UnknownWitnessHandle, not a wrong rowid.
        va = tmp_path / "a.vertex"
        sa = tmp_path / "a.db"
        va.write_text(_VERTEX_KDL.format(store=sa))
        lineage = _absorb(va, sa)
        f1 = _append(sa, "decision", 100, topic="a")
        pos_a = resolve_witness_position(sa, f1)

        sb = tmp_path / "b.db"
        _fresh_store(sb)
        _mirror_lineage(sa, sb, lineage)  # same lineage, but f1 NOT copied
        with pytest.raises(UnknownWitnessHandle):
            verify_position_for_store(pos_a, sb)


# ---------------------------------------------------------------------------
# Ontology seam verifies the position too (capstone M2)
# ---------------------------------------------------------------------------


def test_ontology_seam_verifies_foreign_position(tmp_path):
    # resolve_declaration_documents(at=) is a public selector that applies
    # at.rowid — it must refuse a position from another (unadopted) store, not
    # only vertex_fold/vertex_facts (M2).
    a = tmp_path / "a.db"
    _fresh_store(a)
    _append(a, "decision", 100, topic="a")
    pos_a = resolve_witness_position(a, "head")  # unadopted, store == a

    b = tmp_path / "b.db"
    _fresh_store(b)
    _append(b, "decision", 100, topic="b")
    with pytest.raises(WitnessLineageMismatch):
        resolve_declaration_documents(b, at=pos_a)


# ---------------------------------------------------------------------------
# group_boundary snap vs refuse (capstone M3)
# ---------------------------------------------------------------------------


class TestGroupBoundarySnap:
    def _ceremony(self, tmp_path):
        return TestReceiptGroupGuard()._ceremony_store(tmp_path)

    def test_refuse_is_default_floor_snaps_before_first_row(self, tmp_path):
        """Kills mutants replacing fact_id with None and rowid <= 0 with rowid <= 1 at witness.py:305."""
        _vpath, store, rows = self._ceremony(tmp_path)
        conn = sqlite3.connect(str(store))
        first_id = conn.execute(
            "SELECT id FROM facts WHERE rowid = ?", (rows[0],)
        ).fetchone()[0]
        genesis_id = conn.execute(
            "SELECT id FROM facts WHERE rowid = ?", (rows[0] - 1,)
        ).fetchone()[0]
        conn.close()
        # Exact form (default refuse) — a mid-group position errors.
        with pytest.raises(MidReceiptGroupPosition):
            resolve_witness_position(store, first_id)
        # Floor form — snaps to the position JUST BEFORE the ceremony's first row.
        snapped = resolve_witness_position(store, first_id, group_boundary="floor")
        assert snapped.rowid == rows[0] - 1
        assert snapped.fact_id == genesis_id
        assert snapped.fact_id != "" and snapped.fact_id is not None

    def test_allow_group_boundary_skips_guard(self, tmp_path):
        """Kills mutant replacing 'allow' with 'XXallowXX' at witness.py:298."""
        _vpath, store, rows = self._ceremony(tmp_path)
        conn = sqlite3.connect(str(store))
        first_id = conn.execute(
            "SELECT id FROM facts WHERE rowid = ?", (rows[0],)
        ).fetchone()[0]
        conn.close()
        pos = resolve_witness_position(store, first_id, group_boundary="allow")
        assert pos.rowid == rows[0]
        assert pos.fact_id == first_id


# ---------------------------------------------------------------------------
# resolve_cut_summary — one-transaction cut resolution (0.9.0 S6, sol P1)
# ---------------------------------------------------------------------------


class TestResolveCutSummary:
    def test_no_seal_bundles_position_and_zero_tick_total(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        summary = resolve_cut_summary(store)
        assert summary.position.fact_id == f1
        assert summary.position.anchor is None
        assert summary.tick_total == 0
        assert summary.anchor_seq is None

    def test_sealed_to_head_bundles_matching_anchor_seq(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "t", 150.0, fact_cursor=f1)
        summary = resolve_cut_summary(store)
        assert summary.position.fact_id == f1
        assert summary.position.anchor is not None
        assert summary.tick_total == 1
        # The anchor's own receipt ordinal equals the head position's — the
        # anchor tick's fact_cursor IS head, so nothing lies beyond it.
        assert summary.anchor_seq == summary.position.seq

    def test_seal_plus_tail_reports_smaller_anchor_seq(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "t", 150.0, fact_cursor=f1)
        _append(store, "decision", 200, topic="b")
        summary = resolve_cut_summary(store)
        assert summary.tick_total == 1
        assert summary.anchor_seq is not None
        assert summary.position.seq - summary.anchor_seq == 1

    def test_no_usable_store_raises(self, tmp_path):
        """Kills mutant replacing invalid store message with None in resolve_cut_summary at witness.py:440."""
        with pytest.raises(WitnessResolutionError, match="is not a usable store — cannot resolve a cut summary"):
            resolve_cut_summary(tmp_path / "nope.db")

    def test_atomic_snapshot_ignores_write_landing_mid_resolution(
        self, tmp_path, monkeypatch,
    ):
        """A write landing BETWEEN resolve_cut_summary's internal reads must
        NOT be visible to that same call — proves the explicit BEGIN/ROLLBACK
        pins one WAL snapshot across the position/tick_total/anchor reads
        (sol P1: three independent connections could each observe a LATER
        snapshot than the last, silently advancing tick_total past what the
        returned position reflects).

        The "concurrent writer" is a genuinely separate connection (a real
        concurrent writer would be a different process), fired via a
        monkeypatched hook right after the FIRST internal position
        resolution (head) completes but before the tick_total read that
        follows it in resolve_cut_summary's body.
        """
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "t", 150.0, fact_cursor=f1)  # tick_total == 1 so far

        import engine.witness as witness_mod

        original = witness_mod._resolve_witness_position_on_conn
        calls = {"n": 0}

        def patched(conn, sp, address, **kwargs):
            result = original(conn, sp, address, **kwargs)
            calls["n"] += 1
            if calls["n"] == 1:
                # Fires after the head position is resolved, before
                # resolve_cut_summary's own tick_total/anchor reads run.
                _append_tick(store, "concurrent", 999.0, fact_cursor=f1)
            return result

        monkeypatch.setattr(witness_mod, "_resolve_witness_position_on_conn", patched)

        summary = resolve_cut_summary(store)
        # The snapshot taken at BEGIN must not see the tick committed by the
        # separate connection mid-resolution — still 1, not 2.
        assert summary.tick_total == 1
        # A fresh, un-monkeypatched call (new snapshot) DOES see it — proving
        # the write really landed and the store isn't just stale/broken.
        assert resolve_cut_summary(store).tick_total == 2

    def test_anchor_lookup_failure_degrades_only_that_field(
        self, tmp_path, monkeypatch,
    ):
        """A failure resolving the anchor's own ordinal degrades ONLY
        anchor_seq — the position/tick_total answer (already computed) is
        still returned, never discarded wholesale."""
        vpath, store = _scaffold(tmp_path)
        _fresh_store(store)
        f1 = _append(store, "decision", 100, topic="a")
        _append_tick(store, "t", 150.0, fact_cursor=f1)

        import engine.witness as witness_mod

        original = witness_mod._resolve_witness_position_on_conn
        calls = {"n": 0}

        def patched(conn, sp, address, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:  # the anchor-ordinal lookup, not head itself
                raise UnknownWitnessHandle("simulated failure")
            return original(conn, sp, address, **kwargs)

        monkeypatch.setattr(witness_mod, "_resolve_witness_position_on_conn", patched)

        summary = resolve_cut_summary(store)
        assert summary.position.fact_id == f1
        assert summary.tick_total == 1
        assert summary.anchor_seq is None
