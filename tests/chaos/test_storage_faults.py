"""Outer-Loop Tier 7: Chaos & Storage Fault Injection Tests.

Simulates catastrophic conditions: ENOSPC (disk full), torn write recovery,
and corrupted trailing bytes across store and engine layers.
"""

from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from atoms import Fact
from engine import open_vertex
from engine.handle import WriteCredentials
from engine.jsonl_store import JsonlStore
from engine.sqlite_store import SqliteStore


class BenchCreds:
    def for_write(self, vertex: Path) -> WriteCredentials:
        return WriteCredentials()


def test_sqlite_store_disk_full_resilience(tmp_path: Path) -> None:
    """SqliteStore must handle disk full without corrupting previously committed facts."""
    db_path = tmp_path / "fault.db"
    store = SqliteStore(
        path=db_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )

    # Initial valid append
    f1 = Fact(kind="note", ts=1000.0, payload={"msg": "initial"}, observer="test")
    store.append(f1)
    assert len(store.since(0)) == 1

    # Simulate ENOSPC on the underlying SQLite connection execute/commit
    with patch.object(
        store,
        "_write_fact_row",
        side_effect=sqlite3.OperationalError("database or disk is full"),
    ):
        f2 = Fact(kind="note", ts=1001.0, payload={"msg": "should fail"}, observer="test")
        with pytest.raises(sqlite3.OperationalError, match="disk is full"):
            store.append(f2)

    # Verify store integrity: existing facts preserved, no half-written phantom facts
    facts = store.since(0)
    assert len(facts) == 1
    assert facts[0].payload == {"msg": "initial"}


def test_jsonl_store_torn_line_recovery(tmp_path: Path) -> None:
    """JsonlStore must automatically detect and recover from torn/truncated trailing lines."""
    log_path = tmp_path / "torn.jsonl"
    store = JsonlStore(
        path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )

    # Write initial valid fact
    f1 = Fact(kind="note", ts=1000.0, payload={"msg": "valid"}, observer="test")
    store.append(f1)

    # Manually append a torn line (simulating process death mid-flush)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write('{"id": "01M01000000000000000000002", "kind": "note", "ts": 1001.0, "payload": {"msg": "torn')

    # Next append must reconcile and truncate the torn line cleanly
    f3 = Fact(kind="note", ts=1002.0, payload={"msg": "recovered"}, observer="test")
    store.append(f3)

    # Store must contain exactly the 2 valid facts
    facts = store.since(0)
    assert len(facts) == 2
    assert facts[0].payload == {"msg": "valid"}
    assert facts[1].payload == {"msg": "recovered"}


def test_engine_emit_disk_error_resilience(tmp_path: Path) -> None:
    """Engine VertexHandle must fail gracefully under storage errors without wedging."""
    store_path = tmp_path / "engine_fault.db"
    vertex_path = tmp_path / "engine_fault.vertex"
    vertex_path.write_text(
        f'name "engine_fault"\n'
        f'store "{store_path}"\n'
        f'loops {{\n'
        f'  note {{\n'
        f'    fold {{ items "collect" 100 }}\n'
        f'  }}\n'
        f'}}\n'
    )
    SqliteStore(
        path=store_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    ).close()

    with open_vertex(vertex_path, credentials=BenchCreds()) as handle:
        # Valid emission
        handle.receive(Fact(kind="note", ts=1000.0, payload={"i": 1}, observer="test"))
        assert handle.snapshot.visible_domain_count == 1

        # Simulate storage failure during receive
        from engine.program import VertexProgram
        with patch.object(
            VertexProgram,
            "receive",
            side_effect=sqlite3.OperationalError("disk I/O error"),
        ):
            with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
                handle.receive(Fact(kind="note", ts=1001.0, payload={"i": 2}, observer="test"))

        # Subsequent emission after transient error succeeds cleanly
        handle.receive(Fact(kind="note", ts=1002.0, payload={"i": 3}, observer="test"))
        assert handle.snapshot.visible_domain_count == 2
