"""Write-receipt contract — Vertex.receive_receipt / VertexProgram.receive.

Pins the receipt semantics (friction:engine-write-path-no-receipt-no-close):
the store's append already returned the fact id; the receipt threads it out
instead of discarding it, and makes stored-vs-rejected expressible — both
were an ambiguous ``None`` under the tick-only return.
"""

from __future__ import annotations

from pathlib import Path

from atoms import Fact
from engine import Receipt, SqliteStore, Vertex
from engine.loop import Loop
from engine.peer import Grant
from engine.program import VertexProgram
from engine.store import EventStore


def _sqlite_vertex(tmp_path: Path, **loop_kw) -> Vertex:
    store = SqliteStore(
        path=tmp_path / "r.db",
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    )
    v = Vertex("r", store=store)
    v.register_loop(Loop(
        name="task", initial=[], fold=lambda s, p: [*s, p],
        boundary_count=2, boundary_mode="every", **loop_kw,
    ))
    v.replay()
    return v


class TestVertexReceipt:
    def test_sqlite_store_fact_id_round_trip(self, tmp_path):
        v = _sqlite_vertex(tmp_path)
        r = v.receive_receipt(Fact.of("task", "kyle", name="j1"))
        assert isinstance(r, Receipt)
        assert r.stored is True
        assert r.tick is None  # boundary_count=2, first fact
        assert r.fact_id is not None
        # The id on the receipt IS the id in the store — no pre-minting.
        stored_ids = [row[0] for row in
                      v._store._conn.execute("SELECT id FROM facts")]
        assert r.fact_id in stored_ids
        v.close()

    def test_id_override_is_honored_and_returned(self, tmp_path):
        v = _sqlite_vertex(tmp_path)
        r = v.receive_receipt(Fact.of("task", "kyle", name="j1"),
                              id_override="01TESTULID0000000000000000")
        assert r.fact_id == "01TESTULID0000000000000000"
        v.close()

    def test_boundary_tick_rides_the_receipt(self, tmp_path):
        v = _sqlite_vertex(tmp_path)
        v.receive_receipt(Fact.of("task", "kyle", name="j1"))
        r = v.receive_receipt(Fact.of("task", "kyle", name="j2"))
        assert r.stored is True
        assert r.tick is not None
        assert r.tick.name == "task"
        v.close()

    def test_grant_rejection_is_not_stored(self, tmp_path):
        """The trichotomy fix: rejected != stored-no-tick, and nothing lands."""
        v = _sqlite_vertex(tmp_path)
        r = v.receive_receipt(Fact.of("task", "kyle", name="j1"),
                              Grant(potential=frozenset({"other"})))
        assert r == Receipt(fact_id=None, tick=None, stored=False)
        count = v._store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        assert count == 0  # receipt says not stored — and it isn't
        v.close()

    def test_observer_state_rejection_is_not_stored(self, tmp_path):
        v = _sqlite_vertex(tmp_path)
        r = v.receive_receipt(Fact.of("focus.kyle", "mallory", target="x"))
        assert r.stored is False and r.fact_id is None
        v.close()

    def test_untracking_store_stores_without_id(self):
        v = Vertex("m", store=EventStore())
        v.register("note", {}, lambda s, p: {**s, **p})
        r = v.receive_receipt(Fact.of("note", "kyle", body="hi"))
        assert r.stored is True
        assert r.fact_id is None  # EventStore tracks no per-event ids

    def test_storeless_vertex_reports_not_stored(self):
        v = Vertex("m")
        v.register("note", {}, lambda s, p: {**s, **p})
        r = v.receive_receipt(Fact.of("note", "kyle", body="hi"))
        assert r.stored is False and r.fact_id is None
        assert v.state("note")["body"] == "hi"  # folded regardless

    def test_receive_is_the_tick_projection(self, tmp_path):
        """receive() delegates to receive_receipt — one path, two views."""
        v = _sqlite_vertex(tmp_path)
        assert v.receive(Fact.of("task", "kyle", name="j1")) is None
        tick = v.receive(Fact.of("task", "kyle", name="j2"))
        assert tick is not None and tick.name == "task"
        v.close()


class TestClose:
    def test_vertex_close_is_idempotent(self, tmp_path):
        v = _sqlite_vertex(tmp_path)
        v.close()
        v.close()  # store close is None-guarded

    def test_storeless_close_is_noop(self):
        Vertex("m").close()

    def test_program_context_manager_closes_store(self, tmp_path):
        v = _sqlite_vertex(tmp_path)
        with VertexProgram(vertex=v, sources=[], expected_ticks=["task"]) as p:
            r = p.receive(Fact.of("task", "kyle", name="j1"))
            assert isinstance(r, Receipt) and r.stored
        # closed on exit: the sqlite connection is gone
        assert v._store._conn is None


class TestProgramReceipt:
    def test_program_receive_returns_receipt_and_dispatches(self, tmp_path):
        store = SqliteStore(path=tmp_path / "d.db",
                            serialize=Fact.to_dict, deserialize=Fact.from_dict)
        v = Vertex("orch", store=store)
        v.register_loop(Loop(name="task", initial=[], fold=lambda s, p: [*s, p],
                             boundary_count=1, boundary_mode="every",
                             boundary_run="scripts/go.sh"))
        v.replay()
        calls: list[str] = []
        with VertexProgram(vertex=v, sources=[], expected_ticks=["task"],
                           path=tmp_path / "d.vertex",
                           run_dispatcher=lambda c, n, p: calls.append(c)) as prog:
            r = prog.receive(Fact.of("task", "kyle", name="j1"))
        assert r.fact_id is not None and r.stored
        assert r.tick is not None and r.tick.run == "scripts/go.sh"
        assert calls == ["scripts/go.sh"]  # dispatch fired off the receipt's tick


class TestReplayTreeDiscipline:
    """Replay's store-swap is per-TREE (adversarial-review findings):
    per-vertex swapping let stored children re-append the parent's full
    history on every load, and a raising fold left the swap unrestored."""

    def _tree(self, tmp_path):
        parent_store = SqliteStore(path=tmp_path / "p.db",
                                   serialize=Fact.to_dict, deserialize=Fact.from_dict)
        child_store = SqliteStore(path=tmp_path / "c.db",
                                  serialize=Fact.to_dict, deserialize=Fact.from_dict)
        parent = Vertex("p", store=parent_store)
        parent.register("note", {}, lambda s, p: {**s, **p})
        child = Vertex("c", store=child_store)
        child.register("note", {}, lambda s, p: {**s, **p})
        parent.add_child(child)
        return parent, child

    def test_replay_does_not_double_append_child_stores(self, tmp_path):
        parent, child = self._tree(tmp_path)
        parent.receive(Fact.of("note", "kyle", body="hi"))  # live: both store once

        def rows(v):
            return v._store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

        assert rows(parent) == 1 and rows(child) == 1
        parent.replay()
        parent.replay()
        # Pre-fix: child grew by the parent's full history per replay (1→2→3).
        assert rows(child) == 1
        parent.close()

    def test_raising_fold_during_replay_restores_the_swap(self, tmp_path):
        store = SqliteStore(path=tmp_path / "x.db",
                            serialize=Fact.to_dict, deserialize=Fact.from_dict)
        store.append(Fact.of("boom", "kyle", n="1"))

        def bad_fold(s, p):
            raise RuntimeError("fold exploded")

        v = Vertex("x", store=store)
        v.register("boom", {}, bad_fold)
        try:
            v.replay()
            raise AssertionError("replay should have raised")
        except RuntimeError:
            pass
        # Pre-fix: _store stayed None (close() no-op → leaked handle) and
        # _replaying stayed True (boundaries dead forever).
        assert v._store is store
        assert v._replaying is False
        v.close()
        assert store._conn is None  # close actually reached the store

    def test_close_recurses_into_children(self, tmp_path):
        parent, child = self._tree(tmp_path)
        parent.close()
        assert parent._store._conn is None
        assert child._store._conn is None  # pre-fix: child handle leaked


class TestUseAfterClose:
    def test_append_after_close_raises_named_error(self, tmp_path):
        store = SqliteStore(path=tmp_path / "x.db",
                            serialize=Fact.to_dict, deserialize=Fact.from_dict)
        store.close()
        try:
            store.append(Fact.of("note", "kyle", body="hi"))
            raise AssertionError("append after close should raise")
        except RuntimeError as e:
            assert "store closed" in str(e)


class TestProgramThreading:
    """The collapsed grant/no-grant branch and id_override threading,
    pinned at the program level (blindspot findings)."""

    def test_program_receive_threads_grant(self, tmp_path):
        v = _sqlite_vertex(tmp_path)
        with VertexProgram(vertex=v, sources=[], expected_ticks=["task"]) as p:
            refused = p.receive(Fact.of("task", "kyle", name="j1"),
                                Grant(potential=frozenset({"other"})))
            assert refused == Receipt(fact_id=None, tick=None, stored=False)
            allowed = p.receive(Fact.of("task", "kyle", name="j1"),
                                Grant(potential=frozenset({"task"})))
            assert allowed.stored and allowed.fact_id is not None

    def test_program_receive_threads_id_override(self, tmp_path):
        v = _sqlite_vertex(tmp_path)
        with VertexProgram(vertex=v, sources=[], expected_ticks=["task"]) as p:
            r = p.receive(Fact.of("task", "kyle", name="j1"),
                          id_override="01TESTULID0000000000000000")
            assert r.fact_id == "01TESTULID0000000000000000"
        row = None
        import sqlite3
        conn = sqlite3.connect(tmp_path / "r.db")
        row = conn.execute("SELECT id FROM facts").fetchone()
        conn.close()
        assert row[0] == "01TESTULID0000000000000000"
