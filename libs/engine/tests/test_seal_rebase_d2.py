"""Slice D / WP-3 — seal re-base (D2) and W2-1 cursor-semantics ruling gates.

`docs/scratch/arrival-sliceD/design-proposal.md` §D2 re-bases the tick hash chain,
fact-window commitments, and verification from store-local rowids onto arrival
coordinates `(arrival_ordinal, arrival_seq)`.
`decision:design/sliceD-w2-1-cursor-axis-ruling` re-keys `since`, `since_raw`,
`replay_cursor`, and `ticks_since` to coordinate pair cursors.

Gates covered:
- G-D2-1: Pre-D sealed fixture — verify_chain green AND each window hash byte-equal
          to reference rowid computation on mirrored store.
- G-D2-2: Seal spanning a batch record on batch-bearing store — window membership
          and hash identical before/after rederivation.
- G-D2-3: Unresolvable cursor still hashes as empty.
- G-D2-4: Verification under permutation — verify_chain counts and verdicts identical
          on permuted-insert harness.
- G-D2-5: Rowid ratchet — no rowid in ORDER BY, range WHERE, or COUNT windows in
          sqlite_store.py outside shrink-only allowlist.
- W2-1 equivalence: Incremental fold/event delivery equals full replay on permuted
          harness with batches.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from atoms import Fact
from engine.arrival import ArrivalLog
from engine.arrival_projection import rederive_projections
from engine.arrival_store import ARRIVAL_LINEAGE_KEY, ArrivalStore
from engine.jsonl_codec import object_of_batch, object_of_fact_row, object_of_tick_row
from engine.projection import Projection
from engine.replay import replay
from engine.sqlite_store import (
    FACT_INSERT_SQL,
    TICK_INSERT_SQL,
    _TICK_ROW_SQL,
    SqliteStore,
    _fact_row_hash,
    _tick_commitment_hash,
    _tick_row_hash,
    ensure_coordinate_schema,
    gen_id,
)
from engine.store_reader import StoreReader
from engine.tick import Tick
from engine.vertex import Vertex

_SAMPLE_PUBKEY = base64.b64encode(b"\x00" * 32).decode()
_SAMPLE_SIG = base64.b64encode(b"\x01" * 64).decode()


def _tick_signer(digest: str) -> str:
    return hashlib.sha256(digest.encode()).hexdigest()


def _fact_signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"{observer}:{digest}".encode()).hexdigest()


def _legacy_rowid_window_hash(conn: sqlite3.Connection, start_fact_id: str, end_fact_id: str) -> str:
    """Reference computation of window hash using rowids."""
    h = hashlib.sha256()
    lo = 0 if start_fact_id == "" else (
        conn.execute("SELECT rowid FROM facts WHERE id = ?", (start_fact_id,)).fetchone() or (None,)
    )[0]
    hi = 0 if end_fact_id == "" else (
        conn.execute("SELECT rowid FROM facts WHERE id = ?", (end_fact_id,)).fetchone() or (None,)
    )[0]
    if lo is None or hi is None:
        return h.hexdigest()

    cols = "id, kind, ts, observer, origin, payload"
    sig_col = "signature" in {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
    if sig_col:
        cols += ", signature"
    for row in conn.execute(
        f"SELECT {cols} FROM facts WHERE rowid > ? AND rowid <= ? ORDER BY rowid",
        (lo, hi),
    ):
        h.update(_fact_row_hash(row).encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# G-D2-1: Pre-D sealed fixture
# ---------------------------------------------------------------------------


class TestGD2_1_PreDSealedFixture:
    def test_mirrored_store_window_hashes_match_reference_computation(self, tmp_path: Path) -> None:
        """On a mirrored-coordinate store (where arrival coordinates match
        append sequence), verify_chain is green and each tick's window_hash
        is byte-equal to reference rowid computation."""
        db_path = tmp_path / "mirrored.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
            tick_signer=_tick_signer,
            fact_signer=_fact_signer,
        )

        f1 = store.append(Fact.of("note", "alice", body="first"))
        f2 = store.append(Fact.of("note", "alice", body="second"))
        t1 = store.append_tick(Tick(name="seal", ts=datetime.now(UTC), payload={"n": 1}, origin="t"))

        f3 = store.append(Fact.of("note", "alice", body="third"))
        f4 = store.append(Fact.of("note", "alice", body="fourth"))
        f5 = store.append(Fact.of("note", "alice", body="fifth"))
        t2 = store.append_tick(Tick(name="seal", ts=datetime.now(UTC), payload={"n": 2}, origin="t"))

        t3 = store.append_tick(Tick(name="seal", ts=datetime.now(UTC), payload={"n": 3}, origin="t"))

        report = store.verify_chain(include_ticks=True)
        assert report["ok"] is True
        assert report["chained"] == 3
        assert report["covered_facts"] == 5
        assert report["uncovered_facts"] == 0

        # Compare every tick's window hash with legacy reference computation
        conn = sqlite3.connect(str(db_path))
        ticks = conn.execute(
            "SELECT id, window_start, fact_cursor, window_hash FROM ticks ORDER BY arrival_ordinal, arrival_seq"
        ).fetchall()
        for tid, w_start, w_cursor, w_hash in ticks:
            ref_hash = _legacy_rowid_window_hash(conn, w_start, w_cursor)
            assert w_hash == ref_hash, f"Tick {tid} window_hash diverged from reference computation"
        conn.close()


# ---------------------------------------------------------------------------
# G-D2-2: Batch-bearing store seal preservation across rederivation
# ---------------------------------------------------------------------------


class TestGD2_2_BatchBearingStoreRederivation:
    def test_seal_spanning_batch_record_survives_rederivation(self, tmp_path: Path) -> None:
        """A tick sealing across multi-row batch records verifies identically
        before and after projection rederivation."""
        log_path = tmp_path / "store.arrival"
        db_path = tmp_path / "store.db"

        log = ArrivalLog.mint(
            log_path,
            observer="kyle",
            signer=lambda obs, dig: _SAMPLE_SIG,
            key=_SAMPLE_PUBKEY,
        )
        store = ArrivalStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
            tick_signer=_tick_signer,
            fact_signer=_fact_signer,
        )

        # Single fact
        store.append(Fact.of("note", "kyle", n=1))
        # Batch record with 3 facts
        batch_facts = [
            Fact.of("item", "kyle", item_id="a"),
            Fact.of("item", "kyle", item_id="b"),
            Fact.of("item", "kyle", item_id="c"),
        ]
        batch_obj = object_of_batch(
            [(gen_id(), f.kind, f.ts, f.observer, f.origin, json.dumps(dict(f.payload))) for f in batch_facts]
        )
        log.append("batch", batch_obj, observer="kyle")

        # Absorb the record into store
        store._sync_derived_state()

        # Single fact
        store.append(Fact.of("note", "kyle", n=2))

        # Seal covering the whole sequence (single + batch + single = 5 facts)
        t1_id = store.append_tick(Tick(name="seal_1", ts=datetime.now(UTC), payload={"step": 1}, origin="test"))

        # Add another batch and seal again
        batch_facts_2 = [
            Fact.of("metric", "kyle", v=10),
            Fact.of("metric", "kyle", v=20),
        ]
        batch_obj_2 = object_of_batch(
            [(gen_id(), f.kind, f.ts, f.observer, f.origin, json.dumps(dict(f.payload))) for f in batch_facts_2]
        )
        log.append("batch", batch_obj_2, observer="kyle")
        store._sync_derived_state()

        t2_id = store.append_tick(Tick(name="seal_2", ts=datetime.now(UTC), payload={"step": 2}, origin="test"))

        # Verify before rederivation
        report_before = store.verify_chain(include_ticks=True)
        assert report_before["ok"] is True
        assert report_before["covered_facts"] == 7

        hashes_before = {t["tick"]: (t["fact_cursor"], t["window_facts"]) for t in report_before["tick_detail"]}

        store.close()

        # Rederive projections from arrival log
        rederive_projections(log_path)

        # Reopen store and verify chain after rederivation
        reopened = ArrivalStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
            tick_signer=_tick_signer,
            fact_signer=_fact_signer,
        )
        report_after = reopened.verify_chain(include_ticks=True)
        assert report_after["ok"] is True
        assert report_after["covered_facts"] == report_before["covered_facts"]
        assert report_after["chained"] == report_before["chained"]

        hashes_after = {t["tick"]: (t["fact_cursor"], t["window_facts"]) for t in report_after["tick_detail"]}
        assert hashes_after == hashes_before, "Window facts altered across rederivation"
        reopened.close()


# ---------------------------------------------------------------------------
# G-D2-3: Unresolvable cursor still hashes as empty
# ---------------------------------------------------------------------------


class TestGD2_3_UnresolvableCursor:
    def test_unresolvable_cursor_hashes_empty(self, tmp_path: Path) -> None:
        """A cursor whose fact ID does not exist in the facts table returns None
        from _cursor_ordinal and hashes as empty bytes."""
        db_path = tmp_path / "test.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )

        f1 = store.append(Fact.of("note", "alice", body="one"))
        empty_sha256 = hashlib.sha256(b"").hexdigest()

        # Sentinels
        assert store._cursor_ordinal("") == (-1, 0)
        assert store._cursor_ordinal("nonexistent-id") is None

        # Window hashes with unresolvable cursors return empty hash
        assert store._window_hash("nonexistent-start", "nonexistent-end") == empty_sha256
        assert store._window_hash("", "nonexistent-end") == empty_sha256
        assert store._window_hash("nonexistent-start", f1) == empty_sha256

        store.close()


# ---------------------------------------------------------------------------
# G-D2-4: Verification under permutation
# ---------------------------------------------------------------------------


class TestGD2_4_VerificationUnderPermutation:
    def test_permuted_insert_verify_chain_identical(self, tmp_path: Path) -> None:
        """On a store where physical insertion order (rowids) is scrambled
        relative to arrival coordinates, verify_chain answers identically to
        the ordered representation."""
        ord_db = tmp_path / "ordered.db"
        perm_db = tmp_path / "permuted.db"

        facts = [
            ("f-0", "note", 100.0, "kyle", "", '{"v": 0}', None, 0, 0),
            ("f-1", "note", 101.0, "kyle", "", '{"v": 1}', None, 1, 0),
            ("f-2", "note", 102.0, "kyle", "", '{"v": 2}', None, 2, 0),
            ("f-3", "note", 103.0, "kyle", "", '{"v": 3}', None, 3, 0),
        ]

        # Populate ordered db
        conn_ord = sqlite3.connect(str(ord_db), autocommit=True)
        store_ord = SqliteStore(
            path=ord_db,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        for row in facts:
            conn_ord.execute(FACT_INSERT_SQL, row)
        # Seal tick covering f-0..f-1
        t1_hash = store_ord._window_hash("", "f-1")
        conn_ord.execute(
            TICK_INSERT_SQL,
            ("t-1", "seal", 101.5, None, "test", '{"n": 1}', None, "", "f-1", t1_hash, None, 4, 0),
        )
        t1_row_hash = _tick_row_hash(("t-1", "seal", 101.5, None, "test", '{"n": 1}', None, "", "f-1", t1_hash, None))

        # Seal tick covering f-2..f-3
        t2_hash = store_ord._window_hash("f-1", "f-3")
        t2_row_hash = _tick_row_hash(("t-2", "seal", 103.5, None, "test", '{"n": 2}', t1_row_hash, "f-1", "f-3", t2_hash, None))
        conn_ord.execute(
            TICK_INSERT_SQL,
            ("t-2", "seal", 103.5, None, "test", '{"n": 2}', t1_row_hash, "f-1", "f-3", t2_hash, None, 5, 0),
        )
        report_ord = store_ord.verify_chain(include_ticks=True)
        assert report_ord["ok"] is True, f"Ordered store failed verify_chain: {report_ord.get('breaks')}"
        conn_ord.close()
        store_ord.close()

        # Populate permuted db: physical insertion order is scrambled
        conn_perm = sqlite3.connect(str(perm_db), autocommit=True)
        store_perm = SqliteStore(
            path=perm_db,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        # Insert facts in scrambled order: f-2, f-0, f-3, f-1
        scrambled_facts = [facts[2], facts[0], facts[3], facts[1]]
        for row in scrambled_facts:
            conn_perm.execute(FACT_INSERT_SQL, row)

        # Insert tick 2 before tick 1
        conn_perm.execute(
            TICK_INSERT_SQL,
            ("t-2", "seal", 103.5, None, "test", '{"n": 2}', t1_row_hash, "f-1", "f-3", t2_hash, None, 5, 0),
        )
        conn_perm.execute(
            TICK_INSERT_SQL,
            ("t-1", "seal", 101.5, None, "test", '{"n": 1}', None, "", "f-1", t1_hash, None, 4, 0),
        )

        report_perm = store_perm.verify_chain(include_ticks=True)
        assert report_perm["ok"] is True, f"Permuted store failed verify_chain: {report_perm.get('breaks')}"
        assert report_perm["covered_facts"] == report_ord["covered_facts"]
        assert report_perm["uncovered_facts"] == report_ord["uncovered_facts"]
        assert report_perm["chained"] == report_ord["chained"]
        assert len(report_perm["tick_detail"]) == len(report_ord["tick_detail"])

        for d_ord, d_perm in zip(report_ord["tick_detail"], report_perm["tick_detail"]):
            assert d_ord["window_facts"] == d_perm["window_facts"]
            assert d_ord["fact_cursor"] == d_perm["fact_cursor"]
            assert d_ord["ok"] == d_perm["ok"]

        # Behavioral discrimination: verify_chain window counts and cursor ordering
        # on arrival axis differ from rowid/oid axis (t-1: 2 facts on arrival vs 4 on rowid;
        # t-2: 2 facts on arrival vs 0 on rowid)
        assert report_perm["tick_detail"][0]["tick"] == "t-1"
        assert report_perm["tick_detail"][0]["fact_cursor"] == "f-1"
        assert report_perm["tick_detail"][0]["window_facts"] == 2

        assert report_perm["tick_detail"][1]["tick"] == "t-2"
        assert report_perm["tick_detail"][1]["fact_cursor"] == "f-3"
        assert report_perm["tick_detail"][1]["window_facts"] == 2

        # Chain head and last tick ts discrimination (arrival tick t-2 vs rowid/oid tick t-1)
        assert store_perm.current_chain_head() == t2_row_hash
        assert store_perm.last_tick_ts("seal") == datetime.fromtimestamp(103.5, tz=UTC)

        # Live minting under permutation: predecessor-tick selection, newest-fact edge,
        # and window_start MUST follow the arrival coordinate axis, not rowid/oid.
        t3_id = store_perm.append_tick(
            Tick(name="seal", ts=datetime.fromtimestamp(104.0, tz=UTC), payload={"n": 3}, origin="test")
        )
        t3_row = conn_perm.execute(
            f"SELECT {_TICK_ROW_SQL} FROM ticks WHERE id = ?", (t3_id,)
        ).fetchone()

        # Arrival-axis predecessor is t-2 (rowid/oid axis would pick t-1)
        assert t3_row[6] == t2_row_hash, f"Expected prev_hash from arrival head t-2, got {t3_row[6]}"
        assert t3_row[7] == "f-3", f"Expected window_start 'f-3' from t-2, got {t3_row[7]}"
        # Arrival-axis newest fact is f-3 (rowid/oid axis would pick f-1)
        assert t3_row[8] == "f-3", f"Expected fact_cursor 'f-3', got {t3_row[8]}"
        assert t3_row[9] == store_perm._window_hash("f-3", "f-3")
        t3_row_hash = _tick_row_hash(t3_row)

        # Insert new facts scrambled: f-5 (coord 5,0) inserted before f-4 (coord 4,0)
        conn_perm.execute(
            FACT_INSERT_SQL,
            ("f-5", "note", 105.0, "kyle", "", '{"v": 5}', None, 5, 0),
        )
        conn_perm.execute(
            FACT_INSERT_SQL,
            ("f-4", "note", 104.5, "kyle", "", '{"v": 4}', None, 4, 0),
        )

        t4_id = store_perm.append_tick(
            Tick(name="seal", ts=datetime.fromtimestamp(106.0, tz=UTC), payload={"n": 4}, origin="test")
        )
        t4_row = conn_perm.execute(
            f"SELECT {_TICK_ROW_SQL} FROM ticks WHERE id = ?", (t4_id,)
        ).fetchone()

        # Predecessor is t-3
        assert t4_row[6] == t3_row_hash
        assert t4_row[7] == "f-3"
        # Newest fact by arrival coordinate is f-5 (rowid/oid axis would pick f-4 having higher rowid)
        assert t4_row[8] == "f-5", f"Expected fact_cursor 'f-5', got {t4_row[8]}"
        assert t4_row[9] == store_perm._window_hash("f-3", "f-5")

        # Verify extended chain
        report_final = store_perm.verify_chain(include_ticks=True)
        assert report_final["ok"] is True, f"Extended permuted store failed verify_chain: {report_final.get('breaks')}"
        assert report_final["chained"] == 4
        assert report_final["covered_facts"] == 6
        assert report_final["uncovered_facts"] == 0
        assert [d["fact_cursor"] for d in report_final["tick_detail"]] == ["f-1", "f-3", "f-3", "f-5"]
        assert [d["window_facts"] for d in report_final["tick_detail"]] == [2, 2, 0, 2]

        conn_perm.close()
        store_perm.close()

    def test_live_edge_agrees_with_verify_chain_under_permutation(self, tmp_path: Path) -> None:
        """On a store where physical insertion order (rowids) is scrambled
        relative to arrival coordinates (SOL-WP3-01 reproduction), StoreReader.live_edge
        agrees with verify_chain's coverage accounting:
        covered_facts + live_count == total_facts.

        Fixture setup:
        - Sealed cursor row's rowid sits behind an unsealed fact: unsealed fact f-unsealed (coord 3,0)
          is inserted with rowid 1, while sealed cursor facts f-1 (coord 1,0) and f-2 (coord 2,0)
          are inserted with higher rowids (rowids 3 and 4).
        - Tick rowids are also permuted: older tick t-1 (coord 4,0) is inserted with higher rowid (rowid 2)
          than newer tick t-2 (coord 5,0, rowid 1).

        Under rowid logic:
        - Newest tick selection via ORDER BY rowid DESC picked t-1 (fact_cursor f-1) instead of t-2 (fact_cursor f-2).
        - Boundary via rowid > cursor_rowid looked for facts with rowid > rowid(f-2), missing f-unsealed (rowid 1).
        - verify_chain reported uncovered_facts == 1 while live_edge returned (0, None).

        Under arrival coordinate axis:
        - Newest tick is t-2, fact_cursor is f-2 (coord 2,0).
        - live_edge correctly identifies f-unsealed (coord 3,0 > 2,0) as the 1 live fact.
        - verify_chain coverage accounting (covered 3 + live 1 == total 4) holds.
        """
        db_path = tmp_path / "permuted_live_edge.db"
        conn = sqlite3.connect(str(db_path), autocommit=True)
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )

        facts = [
            ("f-unsealed", "note", 103.0, "kyle", "", '{"v": 3}', None, 3, 0),  # rowid 1, coord (3,0)
            ("f-0", "note", 100.0, "kyle", "", '{"v": 0}', None, 0, 0),         # rowid 2, coord (0,0)
            ("f-1", "note", 101.0, "kyle", "", '{"v": 1}', None, 1, 0),         # rowid 3, coord (1,0)
            ("f-2", "note", 102.0, "kyle", "", '{"v": 2}', None, 2, 0),         # rowid 4, coord (2,0)
        ]
        for row in facts:
            conn.execute(FACT_INSERT_SQL, row)

        # Precompute hashes on arrival axis
        t1_hash = store._window_hash("", "f-1")
        t1_row_hash = _tick_row_hash(("t-1", "seal", 101.5, None, "test", '{"n": 1}', None, "", "f-1", t1_hash, None))

        t2_hash = store._window_hash("f-1", "f-2")
        t2_row_hash = _tick_row_hash(("t-2", "seal", 102.5, None, "test", '{"n": 2}', t1_row_hash, "f-1", "f-2", t2_hash, None))

        # Insert tick 2 (coord 5,0) before tick 1 (coord 4,0) -> t-2 gets rowid 1, t-1 gets rowid 2
        conn.execute(
            TICK_INSERT_SQL,
            ("t-2", "seal", 102.5, None, "test", '{"n": 2}', t1_row_hash, "f-1", "f-2", t2_hash, None, 5, 0),
        )
        conn.execute(
            TICK_INSERT_SQL,
            ("t-1", "seal", 101.5, None, "test", '{"n": 1}', None, "", "f-1", t1_hash, None, 4, 0),
        )

        # verify_chain reports 3 covered facts (f-0, f-1, f-2) and 1 uncovered fact (f-unsealed)
        report = store.verify_chain(include_ticks=True)
        assert report["ok"] is True
        assert report["chained"] == 2
        assert report["covered_facts"] == 3
        assert report["uncovered_facts"] == 1
        assert store.total == 4

        # live_edge on StoreReader MUST agree with verify_chain
        with StoreReader(db_path) as reader:
            live_count, oldest_ts = reader.live_edge()

        assert live_count == 1, f"Expected 1 live fact (f-unsealed), got {live_count}"
        assert oldest_ts == 103.0, f"Expected oldest_ts 103.0 for f-unsealed, got {oldest_ts}"
        assert report["covered_facts"] + live_count == store.total

        # Append another unsealed backdated fact and verify accounting still holds
        conn.execute(
            FACT_INSERT_SQL,
            ("f-late", "note", 99.0, "kyle", "", '{"v": 6}', None, 6, 0),
        )
        report_late = store.verify_chain()
        assert report_late["covered_facts"] == 3
        assert report_late["uncovered_facts"] == 2

        with StoreReader(db_path) as reader:
            live_count, oldest_ts = reader.live_edge()

        assert live_count == 2
        assert oldest_ts == 99.0  # oldest on live edge is min(103.0, 99.0) = 99.0
        assert report_late["covered_facts"] + live_count == store.total

        # Append tick to seal the remaining edge
        t3_id = store.append_tick(
            Tick(name="seal", ts=datetime.fromtimestamp(105.0, tz=UTC), payload={"n": 3}, origin="test")
        )
        report_sealed = store.verify_chain()
        assert report_sealed["ok"] is True
        assert report_sealed["covered_facts"] == 5
        assert report_sealed["uncovered_facts"] == 0

        with StoreReader(db_path) as reader:
            live_count, oldest_ts = reader.live_edge()

        assert live_count == 0
        assert oldest_ts is None
        assert report_sealed["covered_facts"] + live_count == store.total

        conn.close()
        store.close()


# ---------------------------------------------------------------------------
# G-D2-5: Rowid ratchet test
# ---------------------------------------------------------------------------


class TestGD2_5_RowidRatchet:
    def test_no_rowid_in_ordering_range_or_count_windows(self) -> None:
        """AST and pattern scan over sqlite_store.py: no rowid in ORDER BY,
        range WHERE, or COUNT window outside the explicit shrink-only allowlist.

        NOTE: This ratchet is a residue locator for the literal 'rowid' spelling,
        not proof of axis correctness against synonyms or alternative syntax.
        The behavioral gates (such as G-D2-4) own the axis-correctness verdict."""
        store_file = Path(__file__).parent.parent / "src" / "engine" / "sqlite_store.py"
        content = store_file.read_text()

        # 1. No ORDER BY with rowid
        order_by_rowid = re.findall(r"ORDER\s+BY[^\n;\"\']*?\browid\b", content, re.IGNORECASE)
        assert not order_by_rowid, f"Found ORDER BY with rowid: {order_by_rowid}"

        # 2. No range WHERE with rowid (> < >= <=)
        range_where_rowid = re.findall(
            r"WHERE[^\n;\"\']*?\browid\s*(?:>|<|>=|<=)", content, re.IGNORECASE
        )
        assert not range_where_rowid, f"Found range WHERE on rowid: {range_where_rowid}"

        # 3. No COUNT window on rowid
        count_rowid = re.findall(r"COUNT\s*\([^)]*?\browid\b", content, re.IGNORECASE)
        assert not count_rowid, f"Found COUNT on rowid: {count_rowid}"

        # 4. Explicit allowlist for any remaining rowid occurrences in SQL statements
        # Permitted sites:
        # - Schema rebuild table copies in _rebuild_table
        # - reanchor Pass 1 / Pass 2 update statements
        # - _declaration_head_in_txn CAS token
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                func_code = ast.unparse(node)
                if "rowid" in func_code:
                    assert func_name in (
                        "_rebuild_table",
                        "ensure_coordinate_schema",
                        "reanchor",
                        "_declaration_head_in_txn",
                    ), f"Unexpected function containing rowid: {func_name}"


# ---------------------------------------------------------------------------
# W2-1 Equivalence: Incremental Fold vs Full Replay under Batches
# ---------------------------------------------------------------------------


class TestW2_1_IncrementalFoldEquivalence:
    def test_incremental_fold_equals_full_replay_on_permuted_batch_harness(
        self, tmp_path: Path
    ) -> None:
        """Incremental fold/event delivery via Projection.advance() and
        since_with_cursor matches full replay exactly on a permuted store
        containing multi-row batches."""
        db_path = tmp_path / "permuted_batch.db"
        conn = sqlite3.connect(str(db_path), autocommit=True)
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )

        # Create facts with coordinates:
        # Ordinal 0: single fact
        # Ordinal 1: batch of 3 facts (seq 0, 1, 2)
        # Ordinal 2: single fact
        # Ordinal 3: batch of 2 facts (seq 0, 1)
        facts = [
            ("f-0", "item", 100.0, "kyle", "", '{"val": 10, "tag": "f-0"}', None, 0, 0),
            ("f-1a", "item", 101.0, "kyle", "", '{"val": 20, "tag": "f-1a"}', None, 1, 0),
            ("f-1b", "item", 101.0, "kyle", "", '{"val": 30, "tag": "f-1b"}', None, 1, 1),
            ("f-1c", "item", 101.0, "kyle", "", '{"val": 40, "tag": "f-1c"}', None, 1, 2),
            ("f-2", "item", 102.0, "kyle", "", '{"val": 50, "tag": "f-2"}', None, 2, 0),
            ("f-3a", "item", 103.0, "kyle", "", '{"val": 60, "tag": "f-3a"}', None, 3, 0),
            ("f-3b", "item", 103.0, "kyle", "", '{"val": 70, "tag": "f-3b"}', None, 3, 1),
        ]

        # Insert facts into SQLite in scrambled physical rowid order
        scramble_order = [3, 0, 5, 1, 6, 2, 4]
        for idx in scramble_order:
            conn.execute(FACT_INSERT_SQL, facts[idx])

        # 1. Full replay
        full_facts = store.since((-1, 0))
        full_raw = store.since_raw((-1, 0))
        full_cursor_stream = list(store.replay_cursor((-1, 0)))

        expected_tags = ["f-0", "f-1a", "f-1b", "f-1c", "f-2", "f-3a", "f-3b"]
        assert [f.payload["tag"] for f in full_facts] == expected_tags
        assert len(full_raw) == 7
        assert len(full_cursor_stream) == 7

        # 2. Incremental folding with Projection
        class SumProjection(Projection[int, Fact]):
            def apply(self, state: int, event: Fact) -> int:
                return state + event.payload.get("val", 0)

        proj = SumProjection(0)

        # Advance step by step using since_with_cursor
        collected_incremental: list[str] = []

        # Step A: read first 2 facts
        step_a = store.since_with_cursor(proj.cursor)
        assert len(step_a) == 7  # All 7 currently in store
        # Suppose consumer processes up to (1, 1) (mid-batch!)
        for fact, cur in step_a[:3]:  # f-0, f-1a, f-1b
            proj.fold_one(fact)
            proj.cursor = cur
            collected_incremental.append(fact.payload["tag"])

        assert proj.cursor == (1, 1)
        assert proj.state == 10 + 20 + 30

        # Step B: advance from mid-batch cursor (1, 1)
        step_b = store.since_with_cursor(proj.cursor)
        # Should return exactly remaining facts: f-1c (1, 2), f-2 (2, 0), f-3a (3, 0), f-3b (3, 1)
        assert [f.payload["tag"] for f, _ in step_b] == ["f-1c", "f-2", "f-3a", "f-3b"]

        for fact, cur in step_b:
            proj.fold_one(fact)
            proj.cursor = cur
            collected_incremental.append(fact.payload["tag"])

        assert collected_incremental == expected_tags
        assert proj.state == sum(json.loads(f[5])["val"] for f in facts)

        # 3. Projection.advance() method incremental test
        proj_advance = SumProjection(0)
        proj_advance.advance(store)
        assert proj_advance.cursor == (3, 1)
        assert proj_advance.state == proj.state

        # Calling advance again yields no new events
        proj_advance.advance(store)
        assert proj_advance.cursor == (3, 1)

        conn.close()
        store.close()
