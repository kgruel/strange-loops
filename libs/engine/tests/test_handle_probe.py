"""VertexHandle S0 — cursor-bearing probe + the transaction-free invariant.

Proves the detection core: rowid-bearing reads that never synthesize a cursor
from ``COUNT(*)``, separate facts/ticks axes, and — the load-bearing contract —
a probe connection that is TRANSACTION-FREE BETWEEN PROBES so an external commit
is seen within one cycle (``data_version`` pinned inside an open read
transaction never advances → unbounded silent staleness; panel amendment A,
empirically verified here).

Scratch stores in tmp_path only; never touches a live store.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from atoms import Fact

from engine.handle import (
    FactHead,
    HandleClosed,
    StoreProbe,
    TickHead,
)
from engine.sqlite_store import SqliteStore, gen_id


def _fresh_store(store: Path) -> None:
    """Create a WAL store with schema (via SqliteStore) and close it."""
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()


def _append(store: Path, kind: str, ts: float, *, fid: str | None = None, **payload) -> str:
    """Append one fact via a direct connection (a distinct writer)."""
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


def _append_tick(store: Path, name: str, ts: float) -> str:
    conn = sqlite3.connect(str(store))
    tid = gen_id()
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tid, name, ts, ts, "t", json.dumps({"n": 1})),
    )
    conn.commit()
    conn.close()
    return tid


# ---------------------------------------------------------------------------
# Cursor-bearing reads — rowid, never count
# ---------------------------------------------------------------------------


class TestCursorReads:
    def test_empty_store_heads(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        with StoreProbe(store) as probe:
            assert probe.fact_head() == FactHead(rowid=0, fact_id="", count=0)
            assert probe.tick_head() == TickHead(rowid=0, count=0)
            assert probe.facts_after(0, 0) == []
            assert probe.visible_domain_count(0) == 0

    def test_fact_head_and_after(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        a = _append(store, "decision", 100, topic="a")
        b = _append(store, "decision", 101, topic="b")
        with StoreProbe(store) as probe:
            head = probe.fact_head()
            assert head.rowid == 2
            assert head.fact_id == b
            assert head.count == 2
            after = probe.facts_after(0, head.rowid)
            assert [f.fact_id for f in after] == [a, b]
            assert [f.rowid for f in after] == [1, 2]
            # incremental slice
            assert [f.fact_id for f in probe.facts_after(1, 2)] == [b]

    def test_rowid_gap_does_not_misadvance_cursor(self, tmp_path):
        """A gap in rowids (synthesized by deleting a middle row) must not let
        a count-derived cursor skip a live row. The cursor is the real
        ``MAX(rowid)``, never ``COUNT(*)``."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")  # rowid 1
        _append(store, "decision", 101, topic="b")  # rowid 2
        keep = _append(store, "decision", 102, topic="c")  # rowid 3
        # Synthesize a gap: delete rowid 2. Append-only never does this in
        # production; the test forces the count!=max-rowid divergence.
        conn = sqlite3.connect(str(store))
        conn.execute("DELETE FROM facts WHERE rowid = 2")
        conn.commit()
        conn.close()
        with StoreProbe(store) as probe:
            head = probe.fact_head()
            assert head.rowid == 3  # real max rowid, not count (=2)
            assert head.count == 2
            assert head.fact_id == keep
            # facts_after(count=2, ...) would MISS rowid 3 if we used count as
            # the cursor. Using the real rowid, the after-cursor 2 yields rowid 3.
            after = probe.facts_after(2, head.rowid)
            assert [f.rowid for f in after] == [3]
            assert after[0].fact_id == keep

    def test_ticks_are_a_separate_axis(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        _append_tick(store, "boundary", 100.0)
        _append_tick(store, "boundary", 200.0)
        with StoreProbe(store) as probe:
            # facts axis unaffected by ticks
            assert probe.fact_head().rowid == 1
            th = probe.tick_head()
            assert th.rowid == 2 and th.count == 2
            ticks = probe.ticks_after(0, th.rowid)
            assert [t.name for t in ticks] == ["boundary", "boundary"]
            assert [t.rowid for t in ticks] == [1, 2]

    def test_visible_domain_count_excludes_decl(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        _append(store, "_decl.kind_defined", 101, subject="decision")
        _append(store, "thread", 102, name="x")
        with StoreProbe(store) as probe:
            head = probe.fact_head()
            assert head.count == 3  # all rows
            # visible domain excludes the _decl.* control receipt
            assert probe.visible_domain_count(head.rowid) == 2


# ---------------------------------------------------------------------------
# THE probe-transaction invariant — transaction-free between probes
# ---------------------------------------------------------------------------


class TestProbeTransactionInvariant:
    def test_probe_is_transaction_free_between_probes(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with StoreProbe(store) as probe:
            assert probe.in_transaction is False
            probe.data_version()
            assert probe.in_transaction is False
            probe.fact_head()
            assert probe.in_transaction is False
            # reading() pins a txn ONLY for its duration, then releases it
            with probe.reading() as conn:
                assert probe.in_transaction is True
                probe.fact_head(conn)
            assert probe.in_transaction is False

    def test_external_commit_seen_within_one_cycle(self, tmp_path):
        """Open a handle-shaped probe, external commit lands, probe detects it
        on the very next cycle — the exit test the panel required."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with StoreProbe(store) as probe:
            v0 = probe.data_version()
            head0 = probe.fact_head()
            assert head0.rowid == 1
            # External writer (separate connection) commits.
            new_id = _append(store, "decision", 101, topic="b")
            # ONE cycle later: the probe sees it. No reopen, no reload.
            v1 = probe.data_version()
            assert v1 != v0, "data_version must advance on an external commit"
            head1 = probe.fact_head()
            assert head1.rowid == 2 and head1.fact_id == new_id
            assert [f.fact_id for f in probe.facts_after(head0.rowid, head1.rowid)] == [new_id]
            assert probe.in_transaction is False

    def test_true_external_process_commit_detected(self, tmp_path):
        """A genuinely separate OS process commits; the held probe detects it.

        Uses ``subprocess`` with a minimal stdlib-only writer so the commit
        crosses a real process boundary (the daemon-shaped case)."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")
        with StoreProbe(store) as probe:
            v0 = probe.data_version()
            head0 = probe.fact_head()
            writer = (
                "import sqlite3, sys, json;"
                "c=sqlite3.connect(sys.argv[1]);"
                "c.execute(\"INSERT INTO facts (id,kind,ts,observer,origin,payload,signature)"
                " VALUES ('EXTID','decision',102,'kyle','',?,NULL)\", (json.dumps({'topic':'z'}),));"
                "c.commit(); c.close()"
            )
            result = subprocess.run(
                [sys.executable, "-c", writer, str(store)],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, result.stderr
            assert probe.data_version() != v0
            head1 = probe.fact_head()
            assert head1.fact_id == "EXTID"
            new = probe.facts_after(head0.rowid, head1.rowid)
            assert [f.fact_id for f in new] == ["EXTID"]

    def test_pinned_read_txn_would_go_stale_documenting_why(self, tmp_path):
        """Documents the failure the invariant exists to prevent: a connection
        pinned INSIDE an open read transaction does NOT see an external commit's
        ``data_version`` until the txn closes. Our probe avoids this by being
        autocommit; this test proves the hazard is real (not folklore) on a raw
        default-isolation connection."""
        store = tmp_path / "t.db"
        _fresh_store(store)
        _append(store, "decision", 100, topic="a")

        def dv(c):
            return c.execute("PRAGMA data_version").fetchone()[0]

        pinned = sqlite3.connect(str(store))  # default isolation (NOT our probe)
        pinned.execute("BEGIN")
        pinned.execute("SELECT COUNT(*) FROM facts").fetchone()  # opens the snapshot
        v_pinned = dv(pinned)
        _append(store, "decision", 101, topic="b")  # external commit
        assert dv(pinned) == v_pinned, "pinned txn stays stale — the hazard"
        pinned.execute("COMMIT")
        assert dv(pinned) != v_pinned, "only after closing the txn does it advance"
        pinned.close()

        # Our probe (autocommit) has no such blind spot on the same sequence.
        with StoreProbe(store) as probe:
            v0 = probe.data_version()
            _append(store, "decision", 102, topic="c")
            assert probe.data_version() != v0


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestProbeLifecycle:
    def test_close_is_idempotent_and_use_after_close_raises(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        probe = StoreProbe(store)
        probe.close()
        probe.close()  # idempotent
        with pytest.raises(HandleClosed):
            probe.data_version()

    def test_identity_capture(self, tmp_path):
        store = tmp_path / "t.db"
        _fresh_store(store)
        with StoreProbe(store) as probe:
            ident = probe.identity()
            assert ident.device != 0
            assert ident.inode != 0
            assert ident.lineage is None  # unadopted scratch store
