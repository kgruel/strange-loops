"""Tests for store transport — LocalTransport + push/pull orchestration."""

from __future__ import annotations

import json
import sqlite3

import pytest
import sqlite_ulid

from store._transport_local import LocalTransport
from store.receive import ReceiveResult
from store.transport import PullResult, PushResult, pull_store, push_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(path, facts=None, ticks=None):
    """Create a store DB and populate it with test data."""
    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_ulid.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.executescript("""\
        CREATE TABLE facts (
            id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
            kind     TEXT NOT NULL,
            ts       REAL NOT NULL,
            observer TEXT NOT NULL,
            origin   TEXT NOT NULL DEFAULT '',
            payload  TEXT NOT NULL CHECK (json_valid(payload))
        );
        CREATE INDEX idx_facts_kind ON facts(kind);
        CREATE INDEX idx_facts_ts   ON facts(ts);
        CREATE TABLE ticks (
            id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
            name     TEXT NOT NULL,
            ts       REAL NOT NULL,
            since    REAL,
            origin   TEXT NOT NULL,
            payload  TEXT NOT NULL CHECK (json_valid(payload))
        );
        CREATE INDEX idx_ticks_name ON ticks(name);
        CREATE INDEX idx_ticks_ts   ON ticks(ts);
    """)

    for f in (facts or []):
        if "id" in f:
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f["id"], f["kind"], f["ts"], f["observer"], f.get("origin", ""),
                 json.dumps(f.get("payload", {}))),
            )
        else:
            conn.execute(
                "INSERT INTO facts (kind, ts, observer, origin, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (f["kind"], f["ts"], f["observer"], f.get("origin", ""),
                 json.dumps(f.get("payload", {}))),
            )

    for t in (ticks or []):
        conn.execute(
            "INSERT INTO ticks (name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?)",
            (t["name"], t["ts"], t.get("since"), t["origin"],
             json.dumps(t.get("payload", {}))),
        )

    conn.commit()
    conn.close()


def _count(path, table):
    """Count rows in a table."""
    conn = sqlite3.connect(str(path))
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _read_fact_ids(path):
    """Read all fact ULIDs."""
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT id FROM facts ORDER BY id").fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_BASE_TS = 1700000000.0

SAMPLE_FACTS = [
    {"kind": "health", "ts": _BASE_TS + 1, "observer": "alice", "origin": "sensor",
     "payload": {"status": "ok"}},
    {"kind": "health", "ts": _BASE_TS + 2, "observer": "bob", "origin": "sensor",
     "payload": {"status": "warn"}},
    {"kind": "deploy", "ts": _BASE_TS + 3, "observer": "ci", "origin": "github",
     "payload": {"sha": "abc123"}},
]

SAMPLE_TICKS = [
    {"name": "health.check", "ts": _BASE_TS + 2.5, "since": _BASE_TS, "origin": "vertex",
     "payload": {"count": 2}},
]


# ---------------------------------------------------------------------------
# LocalTransport unit tests
# ---------------------------------------------------------------------------

class TestLocalTransportPush:
    """LocalTransport.push — copy to remote via receive."""

    def test_push_creates_remote(self, tmp_path):
        local = tmp_path / "local.db"
        remote = tmp_path / "remote.db"
        _make_store(local, facts=SAMPLE_FACTS)

        transport = LocalTransport()
        result = transport.push(local, remote_path=remote)

        assert isinstance(result, ReceiveResult)
        assert result.status == "created"
        assert result.facts == 3
        assert remote.exists()

    def test_push_merges_into_existing(self, tmp_path):
        local = tmp_path / "local.db"
        remote = tmp_path / "remote.db"

        _make_store(remote, facts=[SAMPLE_FACTS[0]])  # 1 fact already there
        _make_store(local, facts=SAMPLE_FACTS[1:])  # 2 new facts

        transport = LocalTransport()
        result = transport.push(local, remote_path=remote)

        assert result.status == "merged"
        assert result.facts == 2
        assert _count(remote, "facts") == 3


class TestLocalTransportPull:
    """LocalTransport.pull — copy remote to local."""

    def test_pull_copies_file(self, tmp_path):
        remote = tmp_path / "remote.db"
        local_dest = tmp_path / "pulled.db"
        _make_store(remote, facts=SAMPLE_FACTS)

        transport = LocalTransport()
        result = transport.pull(remote, local_path=local_dest)

        assert result.status == "created"
        assert result.facts == 3
        assert local_dest.exists()

    def test_pull_remote_not_found(self, tmp_path):
        transport = LocalTransport()
        with pytest.raises(FileNotFoundError):
            transport.pull(tmp_path / "nope.db", local_path=tmp_path / "dest.db")


# ---------------------------------------------------------------------------
# push_store orchestration
# ---------------------------------------------------------------------------

class TestPushStore:
    """push_store — slice + transport.push cycle."""

    def test_push_all(self, tmp_path):
        source = tmp_path / "source.db"
        remote = tmp_path / "remote.db"
        _make_store(source, facts=SAMPLE_FACTS, ticks=SAMPLE_TICKS)

        transport = LocalTransport()
        result = push_store(source, transport, remote_path=remote)

        assert isinstance(result, PushResult)
        assert result.sliced_facts == 3
        assert result.sliced_ticks == 1
        assert result.receive.status == "created"
        assert result.receive.facts == 3
        assert _count(remote, "facts") == 3
        assert _count(remote, "ticks") == 1

    def test_push_with_since_filter(self, tmp_path):
        source = tmp_path / "source.db"
        remote = tmp_path / "remote.db"
        _make_store(source, facts=SAMPLE_FACTS, ticks=SAMPLE_TICKS)

        transport = LocalTransport()
        result = push_store(source, transport, remote_path=remote, since=_BASE_TS + 2)

        assert result.sliced_facts == 2  # health(bob) + deploy
        assert result.sliced_ticks == 1  # tick at 2.5

    def test_push_with_kinds_filter(self, tmp_path):
        source = tmp_path / "source.db"
        remote = tmp_path / "remote.db"
        _make_store(source, facts=SAMPLE_FACTS)

        transport = LocalTransport()
        result = push_store(source, transport, remote_path=remote, kinds=["deploy"])

        assert result.sliced_facts == 1
        assert result.receive.facts == 1

    def test_push_merges_into_existing_remote(self, tmp_path):
        source = tmp_path / "source.db"
        remote = tmp_path / "remote.db"

        _make_store(source, facts=SAMPLE_FACTS)
        _make_store(remote, facts=[SAMPLE_FACTS[0]])  # 1 fact already there

        transport = LocalTransport()
        result = push_store(source, transport, remote_path=remote)

        # Sliced all 3, but remote already had 1 (different ULID though, so all 3 added)
        assert result.sliced_facts == 3
        assert result.receive.status == "merged"

    def test_push_source_not_found(self, tmp_path):
        transport = LocalTransport()
        with pytest.raises(FileNotFoundError):
            push_store(tmp_path / "nope.db", transport, remote_path=tmp_path / "remote.db")


# ---------------------------------------------------------------------------
# pull_store orchestration
# ---------------------------------------------------------------------------

class TestPullStore:
    """pull_store — transport.pull + receive cycle."""

    def test_pull_creates_local(self, tmp_path):
        remote = tmp_path / "remote.db"
        local = tmp_path / "local.db"
        _make_store(remote, facts=SAMPLE_FACTS, ticks=SAMPLE_TICKS)

        transport = LocalTransport()
        result = pull_store(local, transport, remote_path=remote)

        assert isinstance(result, PullResult)
        assert result.sliced_facts == 3
        assert result.sliced_ticks == 1
        assert result.receive.status == "created"
        assert local.exists()
        assert _count(local, "facts") == 3

    def test_pull_merges_into_existing(self, tmp_path):
        remote = tmp_path / "remote.db"
        local = tmp_path / "local.db"

        _make_store(local, facts=[SAMPLE_FACTS[0]])
        _make_store(remote, facts=SAMPLE_FACTS)

        transport = LocalTransport()
        result = pull_store(local, transport, remote_path=remote)

        assert result.receive.status == "merged"
        # Local had 1 fact with a different ULID, remote has 3 with different ULIDs
        # So all 3 from remote get added (they have different ULIDs)
        assert _count(local, "facts") == 4  # 1 original + 3 pulled

    def test_pull_with_since_filter(self, tmp_path):
        remote = tmp_path / "remote.db"
        local = tmp_path / "local.db"
        _make_store(remote, facts=SAMPLE_FACTS)

        transport = LocalTransport()
        result = pull_store(local, transport, remote_path=remote, since=_BASE_TS + 2)

        assert result.sliced_facts == 2  # health(bob) + deploy
        assert _count(local, "facts") == 2

    def test_pull_with_kinds_filter(self, tmp_path):
        remote = tmp_path / "remote.db"
        local = tmp_path / "local.db"
        _make_store(remote, facts=SAMPLE_FACTS)

        transport = LocalTransport()
        result = pull_store(local, transport, remote_path=remote, kinds=["health"])

        assert result.sliced_facts == 2
        assert _count(local, "facts") == 2

    def test_pull_remote_not_found(self, tmp_path):
        transport = LocalTransport()
        with pytest.raises(FileNotFoundError):
            pull_store(
                tmp_path / "local.db", transport, remote_path=tmp_path / "nope.db",
            )


# ---------------------------------------------------------------------------
# Full push/pull round-trip
# ---------------------------------------------------------------------------

class TestPushPullRoundTrip:
    """Integration: push from A -> remote, pull from remote -> B."""

    def test_roundtrip_preserves_data(self, tmp_path):
        store_a = tmp_path / "store_a.db"
        remote = tmp_path / "remote.db"
        store_b = tmp_path / "store_b.db"

        _make_store(store_a, facts=SAMPLE_FACTS, ticks=SAMPLE_TICKS)
        transport = LocalTransport()

        # Push A -> remote
        push_result = push_store(store_a, transport, remote_path=remote)
        assert push_result.receive.status == "created"

        # Pull remote -> B
        pull_result = pull_store(store_b, transport, remote_path=remote)
        assert pull_result.receive.status == "created"

        # B should have exactly the same facts as A
        a_ids = set(_read_fact_ids(store_a))
        b_ids = set(_read_fact_ids(store_b))
        assert a_ids == b_ids
        assert _count(store_b, "facts") == 3
        assert _count(store_b, "ticks") == 1

    def test_incremental_push(self, tmp_path):
        """Push, add more data, push again — dedup works."""
        source = tmp_path / "source.db"
        remote = tmp_path / "remote.db"

        _make_store(source, facts=SAMPLE_FACTS[:2])
        transport = LocalTransport()

        # First push: 2 facts
        r1 = push_store(source, transport, remote_path=remote)
        assert r1.receive.facts == 2
        assert _count(remote, "facts") == 2

        # Add more facts to source and push again
        conn = sqlite3.connect(str(source))
        conn.enable_load_extension(True)
        sqlite_ulid.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            "INSERT INTO facts (kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?)",
            ("deploy", _BASE_TS + 10, "ci", "github", json.dumps({"sha": "def"})),
        )
        conn.commit()
        conn.close()

        # Second push: 3 facts total, but remote already has 2
        r2 = push_store(source, transport, remote_path=remote)
        assert r2.sliced_facts == 3
        assert r2.receive.status == "merged"
        # The 2 original facts have different ULIDs (sliced into new file each time)
        # so they get re-added. But wait — slice creates new ULIDs? No, slice preserves ULIDs.
        # However, the source facts also have ULIDs, and the remote has different ULIDs
        # from the first push (source was sliced into a fresh file both times).
        # Actually, slice_store does SELECT * which includes the id column,
        # so ULIDs are preserved through slice. The remote should dedup correctly.
        assert _count(remote, "facts") == 3
