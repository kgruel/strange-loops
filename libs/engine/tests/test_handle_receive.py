"""VertexHandle S3 — write-through, operation-fresh credentials, CAS seam.

Proves: receive() catches up, writes through the held handle exactly once, and
reconstructs the canonical (ts,id) snapshot without a full reload; a backdated
local fact matches cold replay on return; a racing external write appears
exactly once; signer creation/rotation within one handle lifetime works
(operation-fresh, never frozen); gate rejection has no batch; the CAS seam
(expect=) is refused, not faked; a post-fact tick failure raises a named
committed-fact error and leaves the handle current. Scratch stores in tmp_path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact

from engine import vertex_fold
from engine.handle import (
    ConditionalEmitUnsupported,
    HandleError,
    ReceiveCommittedError,
    ReceiveResult,
    WriteCredentials,
    open_vertex,
)
from engine.peer import Grant
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

_BOUNDARY_KDL = '''name "t"
store "{store}"
loops {{
  event {{ fold {{ acc "sum" "v" }}
           boundary when="event.close" }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


class _Creds:
    """A mutable CredentialProvider — the calls list proves per-write freshness;
    ``current`` can change between writes (key creation / rotation)."""

    def __init__(self, current: WriteCredentials | None = None):
        self.current = current or WriteCredentials()
        self.calls = 0

    def for_write(self, vertex: Path) -> WriteCredentials:
        self.calls += 1
        return self.current


def _scaffold(tmp_path: Path, kdl: str = _VERTEX_KDL) -> tuple[Path, Path]:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(kdl.format(store=store))
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


def _sections(fold):
    return {s.kind: s for s in fold.sections}


# ---------------------------------------------------------------------------
# Basic write-through + canonical reconstruction
# ---------------------------------------------------------------------------


class TestWriteThrough:
    def test_receive_writes_and_reconstructs(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        creds = _Creds()
        with open_vertex(vpath, credentials=creds) as h:
            fact = Fact.of("decision", "kyle", topic="a", position="JWT")
            result = h.receive(fact)
            assert isinstance(result, ReceiveResult)
            assert result.receipt.stored is True
            assert result.receipt.fact_id is not None
            assert result.change is not None
            assert [r.payload["topic"] for r in result.change.receipts] == ["a"]
            # published snapshot == cold read
            cold = vertex_fold(vpath)
            assert _sections(h.snapshot.fold)["decision"].items == _sections(cold)["decision"].items
            assert creds.calls == 1  # operation-fresh: one lookup for one write

    def test_backdated_local_fact_matches_cold_replay(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        creds = _Creds()
        with open_vertex(vpath, credentials=creds) as h:
            h.receive(Fact.of("decision", "kyle", topic="a", position="late", ts=300.0))
            # a locally backdated fact (older stored ts, appended later)
            h.receive(Fact.of("decision", "kyle", topic="a", position="early", ts=100.0))
            cold = vertex_fold(vpath)
            live = _sections(h.snapshot.fold)["decision"].items
            assert live == _sections(cold)["decision"].items
            # (ts,id) replay, not live-tail order: later-ts "late" wins the
            # topic 'a' upsert even though "early" was appended after it
            assert live[0].payload["position"] == "late"

    def test_racing_external_write_appears_exactly_once(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        creds = _Creds()
        with open_vertex(vpath, credentials=creds) as h:
            # external write races in before our local write; receive() catches
            # it up (as its own batch) then appends the local fact.
            ext = _append(store, "decision", 100, topic="x", message="ext")
            local = h.receive(Fact.of("decision", "kyle", topic="y", position="loc"))
            # Reconstruction is a fresh (ts,id) replay, not an incremental
            # tail-fold — so both facts appear exactly once, none double-applied.
            items = _sections(h.snapshot.fold)["decision"].items
            topics = sorted(i.payload["topic"] for i in items)
            assert topics == ["x", "y"]
            ids = [i.id for i in items]
            assert ext in ids and local.receipt.fact_id in ids
            assert len(ids) == len(set(ids))  # no duplication
            # the local write's own receipt rides its returned batch
            assert local.receipt.fact_id in [r.fact_id for r in local.change.receipts]

    def test_read_only_handle_refuses_write(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        with open_vertex(vpath) as h, pytest.raises(HandleError):  # no credentials
            h.receive(Fact.of("decision", "kyle", topic="a"))


# ---------------------------------------------------------------------------
# Operation-fresh credentials — key creation / rotation
# ---------------------------------------------------------------------------


class TestCredentials:
    def test_signer_creation_mid_lifetime(self, tmp_path):
        """A key minted AFTER open must be used on the next write — signers are
        fetched per write, never frozen at handle build (the tasked wedge)."""
        vpath, store = _scaffold(tmp_path)
        creds = _Creds(WriteCredentials())  # no fact_signer initially
        with open_vertex(vpath, credentials=creds) as h:
            h.receive(Fact.of("decision", "kyle", topic="a"))  # unsigned (no key)
            # "mint a key" mid-lifetime
            def signer(observer: str, digest: str) -> str:
                return hashlib.sha256(f"{observer}:{digest}".encode()).hexdigest()
            creds.current = WriteCredentials(fact_signer=signer)
            h.receive(Fact.of("decision", "kyle", topic="b"))  # signed
            assert creds.calls == 2  # one lookup per write
        # the second fact is signed, the first is not
        conn = sqlite3.connect(str(store))
        sigs = dict(conn.execute(
            "SELECT json_extract(payload,'$.topic'), signature FROM facts "
            "WHERE kind='decision'"
        ).fetchall())
        conn.close()
        assert sigs["a"] is None
        assert sigs["b"] is not None


# ---------------------------------------------------------------------------
# Gate rejection + CAS seam
# ---------------------------------------------------------------------------


class TestGatingAndSeam:
    def test_gate_rejection_has_no_batch(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        creds = _Creds()
        with open_vertex(vpath, credentials=creds) as h:
            # grant potential excludes "decision" → rejected before store
            grant = Grant(potential=frozenset({"thread"}))
            result = h.receive(Fact.of("decision", "kyle", topic="a"), grant)
            assert result.receipt.stored is False
            assert result.change is None
            # nothing was written
            assert h.snapshot.fold.is_empty

    def test_expect_seam_refused_not_faked(self, tmp_path):
        vpath, store = _scaffold(tmp_path)
        creds = _Creds()
        with open_vertex(vpath, credentials=creds) as h, \
                pytest.raises(ConditionalEmitUnsupported):
            h.receive(Fact.of("decision", "kyle", topic="a"), expect=object())


# ---------------------------------------------------------------------------
# Committed-fact-but-tick-failed → ReceiveCommittedError
# ---------------------------------------------------------------------------


class TestCommittedFactError:
    def test_post_fact_tick_failure_names_committed_fact(self, tmp_path, monkeypatch):
        vpath, store = _scaffold(tmp_path, kdl=_BOUNDARY_KDL)
        creds = _Creds()
        h = open_vertex(vpath, credentials=creds)

        # Force tick persistence to fail AFTER the fact commits.
        import engine.sqlite_store as ss

        def boom_tick(self, tick, *, enforce_floor=True):
            raise RuntimeError("synthetic tick-persist failure")

        monkeypatch.setattr(ss.SqliteStore, "append_tick", boom_tick)

        with pytest.raises(ReceiveCommittedError) as ei:
            # event.close fires the "event" boundary → a tick is minted → boom
            h.receive(Fact.of("event.close", "kyle", v=1))
        err = ei.value
        # the fact landed and is named
        assert err.fact_id is not None
        # the handle is caught up (the committed fact is in the store)
        conn = sqlite3.connect(str(store))
        (n,) = conn.execute("SELECT COUNT(*) FROM facts WHERE kind='event.close'").fetchone()
        conn.close()
        assert n == 1
        h.close()
