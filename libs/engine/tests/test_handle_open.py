"""VertexHandle S1 — open, immutable snapshot, atomic refresh, tick query.

Proves: the opening snapshot's fold is structurally equal to a cold
``vertex_fold`` read (A7); refresh detects cross-process appends and rebuilds
atomically; a raising reconstruction publishes no partial state and invalidates;
_decl arrival forces recompile; tick-only commits don't refold; the tick query
is hydrated at open. Scratch stores in tmp_path only.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact
from atoms.fold_state import FoldState
from lang import parse_vertex_file
from lang.document import genesis_payload

from engine import vertex_fold
from engine.handle import (
    AggregateHandleUnsupported,
    ChangeBatch,
    HandleClosed,
    HandleInvalidated,
    VertexSnapshot,
    open_vertex,
)
from engine.sqlite_store import SqliteStore, gen_id

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


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()
    return vpath, store


def _append(store: Path, kind: str, ts: float, *, fid: str | None = None, **payload) -> str:
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
        "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?,?,?,?,?,?)",
        (tid, name, ts, ts, "t", json.dumps({"closed": True})),
    )
    conn.commit()
    conn.close()
    return tid


def _sections(fold: FoldState) -> dict:
    return {s.kind: s for s in fold.sections}


# ---------------------------------------------------------------------------
# Open + snapshot equals cold read (A7 full-reconstruction equality)
# ---------------------------------------------------------------------------


class TestOpen:
    def test_open_empty_store(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        with open_vertex(vpath) as h:
            snap = h.snapshot
            assert isinstance(snap, VertexSnapshot)
            assert snap.generation == 0
            assert snap.position.rowid == 0
            assert snap.visible_domain_count == 0
            assert snap.fold.is_empty

    def test_opening_snapshot_equals_cold_read(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        _append(store, "decision", 101, topic="b", message="beta")
        _append(store, "thread", 102, name="x", status="open")
        cold = vertex_fold(vpath)  # bare head FoldState
        with open_vertex(vpath) as h:
            live = h.snapshot.fold
            # Structural equality of the substantive fold sections (unfolded is
            # a head-scoped footer, intentionally suppressed under prefix
            # reconstruction — see vertex_fold at= docstring).
            assert _sections(live).keys() == _sections(cold).keys()
            for kind in _sections(cold):
                assert _sections(live)[kind].items == _sections(cold)[kind].items
            assert h.snapshot.visible_domain_count == 3

    def test_snapshot_is_immutable_and_detached(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        with open_vertex(vpath) as h:
            snap = h.snapshot
            with pytest.raises(Exception):
                snap.generation = 5  # frozen dataclass

    def test_aggregate_refused(self, tmp_path):
        vpath = tmp_path / "agg.vertex"
        vpath.write_text('name "agg"\ncombine {\n  vertex "member"\n}\n')
        with pytest.raises(AggregateHandleUnsupported):
            open_vertex(vpath)


# ---------------------------------------------------------------------------
# Refresh — atomic catch-up
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_refresh_noop_when_unchanged(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        with open_vertex(vpath) as h:
            assert h.refresh() is None
            assert h.refresh() is None

    def test_refresh_detects_external_append(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        with open_vertex(vpath) as h:
            gen0 = h.snapshot.generation
            new_id = _append(store, "decision", 101, topic="b", message="beta")
            batch = h.refresh()
            assert isinstance(batch, ChangeBatch)
            assert batch.replay_mode == "full"
            assert [r.fact_id for r in batch.receipts] == [new_id]
            assert batch.receipts[0].control is False
            assert h.snapshot.generation == gen0 + 1
            assert h.snapshot.position.rowid == 2
            assert h.snapshot.visible_domain_count == 2
            # fold now equal to a fresh cold read
            cold = vertex_fold(vpath)
            assert _sections(h.snapshot.fold)["decision"].items == _sections(cold)["decision"].items

    def test_refresh_equals_cold_after_backdated_arrival(self, tmp_path):
        """A backdated arrival (new rowid, old ts) must reconstruct to a cold
        replay — full (ts,id) reconstruction, never incremental tail-fold."""
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 200, topic="a", message="late-ts-first")
        with open_vertex(vpath) as h:
            # backdated: earlier ts than the existing row, but appended after
            _append(store, "decision", 100, topic="a", message="earlier-ts")
            batch = h.refresh()
            assert batch is not None
            cold = vertex_fold(vpath)
            live_item = _sections(h.snapshot.fold)["decision"].items
            assert live_item == _sections(cold)["decision"].items
            # (ts,id) replay: the later-ts row wins the upsert for topic 'a'
            assert live_item[0].payload["message"] == "late-ts-first"

    def test_force_rebuilds_unconditionally(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        with open_vertex(vpath) as h:
            gen0 = h.snapshot.generation
            batch = h.refresh(force=True)
            assert batch is not None
            assert batch.replay_mode == "full"
            assert h.snapshot.generation == gen0 + 1


# ---------------------------------------------------------------------------
# tick-only + tick query hydration
# ---------------------------------------------------------------------------


class TestTicks:
    def test_tick_query_hydrated_at_open(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        _append_tick(store, "taskclose", 150.0)
        with open_vertex(vpath) as h:
            assert "taskclose" in h.tick_query
            assert h.latest_tick("taskclose").name == "taskclose"
            assert h.snapshot.tick_seq == 1

    def test_tick_only_commit_does_not_refold(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        with open_vertex(vpath) as h:
            fold_before = h.snapshot.fold
            _append_tick(store, "boundary", 200.0)
            batch = h.refresh()
            assert batch is not None
            assert batch.replay_mode == "tick-only"
            assert batch.tick_arrived is True
            assert batch.rows == ()
            assert [t.name for t in batch.ticks] == ["boundary"]
            # fold object is carried unchanged (no reconstruction)
            assert h.snapshot.fold is fold_before
            assert h.snapshot.tick_seq == 1
            assert h.latest_tick("boundary") is not None


# ---------------------------------------------------------------------------
# _decl arrival forces recompile
# ---------------------------------------------------------------------------


class TestOntologyChange:
    def test_decl_receipt_is_control_and_flags_ontology_changed(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        with open_vertex(vpath) as h:
            epoch0 = h.snapshot.ontology_epoch
            # A _decl.* receipt (direct write, mimicking an absorb ceremony row)
            _append(store, "_decl.kind_defined", 101, subject="thread",
                    lineage="L1")
            batch = h.refresh()
            assert batch is not None
            assert batch.ontology_changed is True
            assert any(r.control for r in batch.receipts)
            # epoch turns over (store _decl head changed)
            assert h.snapshot.ontology_epoch != epoch0
            # the _decl row is a visible control receipt, not silently hidden
            assert any(r.kind == "_decl.kind_defined" for r in batch.receipts)


# ---------------------------------------------------------------------------
# Invalidation — no partial publish
# ---------------------------------------------------------------------------


class TestInvalidation:
    def test_raising_reconstruction_publishes_no_partial_state(self, tmp_path, monkeypatch):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        h = open_vertex(vpath)
        good = h.snapshot
        _append(store, "decision", 101, topic="b", message="beta")

        # Force reconstruction to raise.
        import engine.handle as handle_mod

        def boom(self, position):
            raise RuntimeError("synthetic reconstruction failure")

        monkeypatch.setattr(handle_mod.VertexHandle, "_reconstruct", boom)
        with pytest.raises(HandleInvalidated):
            h.refresh()
        # State did not advance; last-good retained for diagnostics only.
        assert h.state == "invalidated"
        assert h.diagnostic_snapshot is good
        with pytest.raises(HandleInvalidated):
            _ = h.snapshot
        h.close()

    def test_use_after_close_raises(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a", message="alpha")
        h = open_vertex(vpath)
        h.close()
        h.close()  # idempotent
        with pytest.raises(HandleClosed):
            _ = h.snapshot
        with pytest.raises(HandleClosed):
            h.refresh()


class TestExports:
    def test_public_import_surface(self):
        import engine

        assert engine.open_vertex is not None
        assert engine.VertexHandle is not None
        assert engine.ChangeBatch is not None
        assert engine.StoreProbe is not None
