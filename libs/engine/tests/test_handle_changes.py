"""VertexHandle S2 — change iterators, coalescing, idle/deadline wake.

Proves: changes() delivers a ChangeBatch per committed change; a burst coalesces
into one full-reconstruction batch with no receipt lost; idle_timeout wakes at a
wall-clock deadline with zero store traffic (panel amendment F2); tick-only and
_decl commits wake with the right batch shape; one iterator per handle; the
async mirror delivers; close() terminates the iterator cleanly. Head-start-only
(no resume-from-position — scoped out of 0.8.0). Scratch stores in tmp_path.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from atoms import Fact

from engine.handle import ChangeBatch, HandleError, open_vertex
from engine.sqlite_store import SqliteStore, gen_id

_VERTEX_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''

_FAST = dict(poll_interval=0.01, coalesce=0.02, max_latency=0.1)


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


def _append_tick(store: Path, name: str, ts: float) -> None:
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?,?,?,?,?,?)",
        (gen_id(), name, ts, ts, "t", json.dumps({"x": 1})),
    )
    conn.commit()
    conn.close()


def _collect(handle, n, *, timeout=5.0, **kw):
    """Pull up to n batches from handle.changes() in a background thread."""
    out: list[ChangeBatch] = []
    done = threading.Event()

    def run():
        try:
            for b in handle.changes(**{**_FAST, **kw}):
                out.append(b)
                if len(out) >= n:
                    break
        finally:
            done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    done.wait(timeout)
    return out


# ---------------------------------------------------------------------------
# Delivery + coalescing
# ---------------------------------------------------------------------------


class TestDelivery:
    def test_catch_up_coalesces_a_burst_into_one_batch(self, tmp_path):
        """A burst that accumulated since the handle's cursor → the iterator's
        initial catch-up refresh delivers all three receipts in ONE coalesced
        full-reconstruction batch, none lost."""
        vpath, store = _scaffold(tmp_path)
        with open_vertex(vpath) as h:  # cursor at 0 (empty store)
            ids = [_append(store, "decision", 100 + i, topic=f"t{i}") for i in range(3)]
            batches = _collect(h, 1)
            assert len(batches) == 1
            b = batches[0]
            assert b.replay_mode == "full"
            assert [r.fact_id for r in b.receipts] == ids
            assert b.receipt_ranges[0][1:] == (1, 3)  # seq range 1..3

    def test_live_writer_delivers_every_receipt_without_loss(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        with open_vertex(vpath) as h:
            seen: list[str] = []
            done = threading.Event()

            def consume():
                try:
                    for b in h.changes(**_FAST):
                        seen.extend(r.fact_id for r in b.receipts)
                        if len(seen) >= 5:
                            break
                finally:
                    done.set()

            t = threading.Thread(target=consume, daemon=True)
            t.start()
            written = []
            for i in range(5):
                written.append(_append(store, "decision", 200 + i, topic=f"k{i}"))
                time.sleep(0.03)
            done.wait(5.0)
            # every written fact was delivered, in order, exactly once
            assert seen == written

    def test_no_change_yields_nothing(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")
        with open_vertex(vpath) as h:
            batches = _collect(h, 1, timeout=0.3)  # no writes, no idle_timeout
            assert batches == []  # a no-change probe does no refold, no yield


# ---------------------------------------------------------------------------
# Idle / deadline wake (panel amendment F2)
# ---------------------------------------------------------------------------


class TestIdleWake:
    def test_idle_timeout_wakes_with_zero_store_traffic(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")
        with open_vertex(vpath) as h:
            batches = _collect(h, 1, idle_timeout=0.05)
            assert len(batches) == 1
            assert batches[0].idle_wake is True
            assert batches[0].replay_mode == "idle"
            assert batches[0].receipts == ()
            # position unchanged — an idle wake is not a state change
            assert batches[0].before == batches[0].after

    def test_change_resets_idle_and_delivers_real_batch(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        with open_vertex(vpath) as h:
            _append(store, "decision", 100, topic="a")
            batches = _collect(h, 1, idle_timeout=1.0)
            # the real change arrives well before the 1s idle deadline
            assert len(batches) == 1
            assert batches[0].idle_wake is False
            assert [r.payload["topic"] for r in batches[0].receipts] == ["a"]


# ---------------------------------------------------------------------------
# Tick-only + ontology change through the iterator
# ---------------------------------------------------------------------------


class TestBatchShapes:
    def test_tick_only_commit_wakes_iterator(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")
        with open_vertex(vpath) as h:
            _append_tick(store, "boundary", 200.0)
            batches = _collect(h, 1)
            assert len(batches) == 1
            assert batches[0].replay_mode == "tick-only"
            assert [t.name for t in batches[0].ticks] == ["boundary"]

    def test_decl_ceremony_flags_ontology_changed(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")
        with open_vertex(vpath) as h:
            _append(store, "_decl.kind_defined", 101, subject="thread", lineage="L1")
            batches = _collect(h, 1)
            assert len(batches) == 1
            assert batches[0].ontology_changed is True
            assert any(r.control for r in batches[0].receipts)


# ---------------------------------------------------------------------------
# Cross-process + lifecycle
# ---------------------------------------------------------------------------


class TestProcessAndLifecycle:
    def test_external_process_commit_wakes_iterator(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")
        with open_vertex(vpath) as h:
            writer = (
                "import sqlite3, sys, json;"
                "c=sqlite3.connect(sys.argv[1]);"
                "c.execute(\"INSERT INTO facts (id,kind,ts,observer,origin,payload,signature)"
                " VALUES ('EXT','decision',105,'kyle','',?,NULL)\", (json.dumps({'topic':'z'}),));"
                "c.commit(); c.close()"
            )
            seen: list[str] = []
            done = threading.Event()

            def consume():
                try:
                    for b in h.changes(**_FAST):
                        seen.extend(r.fact_id for r in b.receipts)
                        break
                finally:
                    done.set()

            t = threading.Thread(target=consume, daemon=True)
            t.start()
            time.sleep(0.05)
            subprocess.run([sys.executable, "-c", writer, str(store)], check=True, timeout=30)
            done.wait(5.0)
            assert seen == ["EXT"]

    def test_one_iterator_per_handle(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")
        with open_vertex(vpath) as h:
            # drive the first iterator into its poll loop
            started = threading.Event()

            def hold():
                for _ in h.changes(**_FAST, idle_timeout=10.0):
                    started.set()

            t = threading.Thread(target=hold, daemon=True)
            t.start()
            # wait until the first iterator is active
            time.sleep(0.1)
            with pytest.raises(HandleError):
                next(h.changes(**_FAST))

    def test_close_terminates_iterator_cleanly(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")
        h = open_vertex(vpath)
        ended = threading.Event()

        def run():
            for _ in h.changes(**_FAST, idle_timeout=10.0):
                pass
            ended.set()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        time.sleep(0.1)
        h.close()  # iterator sees CLOSED and returns — no store mutation
        assert ended.wait(2.0)


# ---------------------------------------------------------------------------
# Async mirror
# ---------------------------------------------------------------------------


class TestAsync:
    def test_changes_async_delivers(self, tmp_path):
        vpath, store = _scaffold(tmp_path)

        async def drive():
            with open_vertex(vpath) as h:
                ids = [_append(store, "decision", 100 + i, topic=f"a{i}") for i in range(2)]
                got: list[str] = []
                async def pump():
                    async for b in h.changes_async(**_FAST):
                        got.extend(r.fact_id for r in b.receipts)
                        return
                await asyncio.wait_for(pump(), timeout=5.0)
                return got, ids

        got, ids = asyncio.run(drive())
        assert got == ids

    def test_changes_async_idle_wake(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")

        async def drive():
            with open_vertex(vpath) as h:
                async def pump():
                    async for b in h.changes_async(**_FAST, idle_timeout=0.05):
                        return b
                return await asyncio.wait_for(pump(), timeout=5.0)

        b = asyncio.run(drive())
        assert b.idle_wake is True


# ---------------------------------------------------------------------------
# Iterator single-flag race (MEDIUM #5)
# ---------------------------------------------------------------------------


class TestIteratorRace:
    def test_two_threads_racing_changes_exactly_one_wins(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        _append(store, "decision", 100, topic="a")
        with open_vertex(vpath) as h:
            results: list = []
            barrier = threading.Barrier(2)

            def run():
                barrier.wait()  # start both threads together
                try:
                    gen = h.changes(**_FAST, idle_timeout=0.1)
                    next(gen)  # forces the generator's test-and-set to run
                    results.append("ok")
                    gen.close()
                except HandleError:
                    results.append("refused")

            threads = [threading.Thread(target=run, daemon=True) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5.0)
            # exactly one acquired the single iterator; the other was refused
            assert sorted(results) == ["ok", "refused"]


# ---------------------------------------------------------------------------
# Tail-loss regression (LOW #7) — a commit injected into the capture→publish
# window must be delivered next loop, never swallowed into the watermark.
# ---------------------------------------------------------------------------


class TestTailLoss:
    def test_commit_injected_during_refresh_is_not_lost_sync(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        with open_vertex(vpath) as h:
            injected = {"id": None, "fired": False}

            def inject():
                if not injected["fired"]:
                    injected["fired"] = True
                    injected["id"] = _append(store, "decision", 200, topic="injected")

            h._on_refresh_capture = inject
            first_id = _append(store, "decision", 100, topic="first")
            seen: list[str] = []
            done = threading.Event()

            def consume():
                try:
                    for b in h.changes(**_FAST):
                        seen.extend(r.fact_id for r in b.receipts)
                        if injected["id"] and injected["id"] in seen:
                            break
                finally:
                    done.set()

            t = threading.Thread(target=consume, daemon=True)
            t.start()
            done.wait(5.0)
            assert first_id in seen
            # the commit that landed AFTER head-capture, DURING refresh, is
            # delivered on the next loop — not lost to the watermark.
            assert injected["id"] in seen

    def test_commit_injected_during_refresh_is_not_lost_async(self, tmp_path):
        vpath, store = _scaffold(tmp_path)

        async def drive():
            with open_vertex(vpath) as h:
                injected = {"id": None, "fired": False}

                def inject():
                    if not injected["fired"]:
                        injected["fired"] = True
                        injected["id"] = _append(store, "decision", 200, topic="inj")

                h._on_refresh_capture = inject
                first_id = _append(store, "decision", 100, topic="first")
                seen: list[str] = []

                async def pump():
                    async for b in h.changes_async(**_FAST):
                        seen.extend(r.fact_id for r in b.receipts)
                        if injected["id"] and injected["id"] in seen:
                            return
                await asyncio.wait_for(pump(), timeout=5.0)
                return first_id, injected["id"], seen

        first_id, inj_id, seen = asyncio.run(drive())
        assert first_id in seen
        assert inj_id in seen
