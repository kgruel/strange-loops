"""Outer-Loop Tier 7: Chaos & Storage Fault Injection Tests.

Simulates catastrophic conditions: ENOSPC (disk full via SQLite max_page_count),
torn write recovery, real process crash mid-write (SIGKILL), derived index corruption,
canonical log corruption, read-only permissions, and engine handle error resilience.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from atoms import Fact
from engine import open_vertex
from engine.declaration import _open_readonly
from engine.handle import WriteCredentials
from engine.jsonl_codec import JsonlCodecError
from engine.jsonl_store import JsonlStore
from engine.sqlite_store import SqliteStore


class BenchCreds:
    def for_write(self, vertex: Path) -> WriteCredentials:
        return WriteCredentials()


def test_sqlite_store_disk_full_resilience(tmp_path: Path) -> None:
    """SqliteStore must handle real disk exhaustion without corrupting committed facts.

    Uses SQLite's engine-native PRAGMA max_page_count ceiling to trigger genuine
    SQLITE_FULL OperationalError from the database engine rather than a mock.
    """
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

    # Clamp SQLite max_page_count to current usage to force SQLITE_FULL on next page allocation
    cur = store._conn.execute("PRAGMA page_count")
    current_pages = cur.fetchone()[0]
    store._conn.execute(f"PRAGMA max_page_count = {current_pages}")

    # Subsequent append requiring new pages must fail with genuine OperationalError
    f2 = Fact(
        kind="note",
        ts=1001.0,
        payload={"msg": "should fail" * 1000},
        observer="test",
    )
    with pytest.raises(sqlite3.OperationalError, match=r"database or disk is full"):
        store.append(f2)

    # Verify store integrity: previously committed fact preserved, uncommitted fact rolled back
    facts = store.since(0)
    assert len(facts) == 1
    assert facts[0].payload == {"msg": "initial"}

    # Lift page ceiling and verify store recovers and accepts new writes cleanly
    store._conn.execute("PRAGMA max_page_count = 100000")
    f3 = Fact(kind="note", ts=1002.0, payload={"msg": "recovered"}, observer="test")
    store.append(f3)
    facts_after = store.since(0)
    assert len(facts_after) == 2
    assert facts_after[1].payload == {"msg": "recovered"}
    store.close()


def test_jsonl_store_torn_line_recovery(tmp_path: Path) -> None:
    """JsonlStore must automatically detect and recover from torn/truncated trailing lines."""
    log_path = tmp_path / "torn.jsonl"
    store = JsonlStore(
        path=tmp_path / "torn.db",
        log_path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )

    # Write initial valid fact
    f1 = Fact(kind="note", ts=1000.0, payload={"msg": "valid"}, observer="test")
    store.append(f1)

    # Manually append a torn line (simulating process death mid-flush without trailing newline)
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
    store.close()

    # The canonical JSONL log on disk must contain exactly 2 valid lines (no torn line concatenation)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    # Reopening from the canonical log must succeed cleanly without codec errors
    reopened_store = JsonlStore(
        path=tmp_path / "torn_reopen.db",
        log_path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    reopened_facts = reopened_store.since(0)
    assert len(reopened_facts) == 2
    assert reopened_facts[0].payload == {"msg": "valid"}
    assert reopened_facts[1].payload == {"msg": "recovered"}
    reopened_store.close()


def test_jsonl_store_crash_mid_write_recovery(tmp_path: Path) -> None:
    """JsonlStore must recover cleanly when a writer process is killed mid-stream via SIGKILL."""
    log_path = tmp_path / "crash.jsonl"
    db_path = tmp_path / "crash.db"

    # Spawn child process that opens JsonlStore, writes facts in a loop,
    # and leaves a post-fsync durable unindexed line right before being killed
    child_script = (
        "import sys, os, time\n"
        "from pathlib import Path\n"
        "from atoms import Fact\n"
        "from engine.jsonl_store import JsonlStore\n"
        f"store = JsonlStore(path=Path({str(db_path)!r}), log_path=Path({str(log_path)!r}), "
        "serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)\n"
        "for i in range(5):\n"
        "    f = Fact(kind='item', ts=float(i), payload={'i': i, 'blob': 'x' * 500}, observer='test')\n"
        "    store.append(f)\n"
        "sys.stdout.write('COMMITTED 5\\n')\n"
        "sys.stdout.flush()\n"
        "# Append durable line to log directly to simulate crash between log fsync and sqlite commit\n"
        f"with open(Path({str(log_path)!r}), 'a', encoding='utf-8') as f:\n"
        "    f.write('{\"t\":\"fact\",\"id\":\"01M01UNINDEXED0000000000000\",\"kind\":\"item\",\"ts\":99.0,\"observer\":\"test\",\"origin\":\"\",\"payload\":\"{\\\\\"i\\\\\": 99}\"}\\n')\n"
        "    f.flush()\n"
        "    os.fsync(f.fileno())\n"
        "sys.stdout.write('DURABLE_UNINDEXED\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(10)\n"
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for child to report durable unindexed line
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if not line or "DURABLE_UNINDEXED" in line:
            break

    # Kill writer process abruptly with SIGKILL (simulating power failure / ungraceful termination)
    proc.send_signal(signal.SIGKILL)
    proc.wait()

    # Reopen store in parent process — catch_up should tail the durable unindexed line forward into sqlite
    recovered_store = JsonlStore(
        path=db_path,
        log_path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    facts = recovered_store.since(0)
    assert len(facts) == 6
    for i in range(5):
        assert facts[i].payload["i"] == i
    assert facts[5].payload["i"] == 99

    # Subsequent append must succeed and append after the recovered stream
    f_next = Fact(kind="item", ts=9999.0, payload={"i": 9999}, observer="test")
    recovered_store.append(f_next)
    facts_after = recovered_store.since(0)
    assert len(facts_after) == 7
    assert facts_after[-1].payload["i"] == 9999
    recovered_store.close()


def test_jsonl_store_corrupt_derived_index_auto_recovery(tmp_path: Path) -> None:
    """JsonlStore must quarantine a corrupted SQLite index and rebuild it from the canonical JSONL log."""
    log_path = tmp_path / "corrupt_index.jsonl"
    db_path = tmp_path / "corrupt_index.db"

    store = JsonlStore(
        path=db_path,
        log_path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    store.append(Fact(kind="note", ts=1.0, payload={"msg": "first"}, observer="test"))
    store.append(Fact(kind="note", ts=2.0, payload={"msg": "second"}, observer="test"))
    store.close()

    # Corrupt the header of the derived SQLite database
    with open(db_path, "r+b") as f:
        f.seek(0)
        f.write(b"CORRUPTED_SQLITE_HEADER_DATA_12345")

    # Opening JsonlStore detects corrupt index, quarantines it, and rebuilds from JSONL
    recovered_store = JsonlStore(
        path=db_path,
        log_path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    facts = recovered_store.since(0)
    assert len(facts) == 2
    assert facts[0].payload == {"msg": "first"}
    assert facts[1].payload == {"msg": "second"}
    recovered_store.close()


def test_jsonl_store_corrupt_log_record_refusal(tmp_path: Path) -> None:
    """JsonlStore must refuse corrupted JSONL log lines with structured JsonlCodecError upon rebuild."""
    log_path = tmp_path / "corrupt_log.jsonl"
    db_path = tmp_path / "corrupt_log.db"

    store = JsonlStore(
        path=db_path,
        log_path=log_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    store.append(Fact(kind="note", ts=1.0, payload={"msg": "valid_1"}, observer="test"))
    store.append(Fact(kind="note", ts=2.0, payload={"msg": "valid_2"}, observer="test"))
    store.close()

    # Corrupt a record mid-file in the canonical JSONL log
    lines = log_path.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(lines) == 2
    lines[1] = lines[1][:20] + "INVALID_JSON_CORRUPTION_HERE" + lines[1][50:]
    log_path.write_text("".join(lines), encoding="utf-8")

    # Remove SQLite index to force rebuild from the corrupted log
    db_path.unlink()

    # Reopening must refuse with structured JsonlCodecError
    with pytest.raises(JsonlCodecError):
        JsonlStore(
            path=db_path,
            log_path=log_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )


def test_sqlite_store_readonly_filesystem_resilience(tmp_path: Path) -> None:
    """SqliteStore must fail write operations with structured errors under read-only permissions while reads work."""
    db_path = tmp_path / "readonly.db"
    store = SqliteStore(
        path=db_path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    store.append(Fact(kind="note", ts=1.0, payload={"msg": "readable"}, observer="test"))
    store.close()

    # Set file to read-only
    os.chmod(db_path, stat.S_IRUSR)
    try:
        # Read-only connection succeeds
        ro_conn = _open_readonly(db_path)
        assert ro_conn is not None
        rows = ro_conn.execute("SELECT kind, payload FROM facts").fetchall()
        assert len(rows) == 1
        ro_conn.close()

        # Write attempt raises structured OperationalError ("attempt to write a readonly database")
        store_ro = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        with pytest.raises(sqlite3.OperationalError, match=r"readonly database"):
            store_ro.append(Fact(kind="note", ts=2.0, payload={"msg": "fail"}, observer="test"))
    finally:
        # Restore permissions for clean teardown
        os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR)


def test_engine_emit_disk_error_resilience(tmp_path: Path) -> None:
    """Engine VertexHandle must fail gracefully under real storage exhaustion without wedging."""
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
        # Valid initial emission
        handle.receive(Fact(kind="note", ts=1000.0, payload={"i": 1}, observer="test"))
        assert handle.snapshot.visible_domain_count == 1

        # Inject real SQLite storage fault: clamp max_page_count on the underlying store connection
        writer = handle._ensure_writer()
        underlying_store = writer.vertex._store
        cur = underlying_store._conn.execute("PRAGMA page_count")
        pages = cur.fetchone()[0]
        underlying_store._conn.execute(f"PRAGMA max_page_count = {pages}")

        # Emission attempting to allocate additional pages fails with real SQLITE_FULL
        with pytest.raises(sqlite3.OperationalError, match=r"database or disk is full"):
            handle.receive(
                Fact(
                    kind="note",
                    ts=1001.0,
                    payload={"i": 2, "big": "x" * 10000},
                    observer="test",
                )
            )

        # Lift page limit and verify subsequent emission succeeds and snapshot domain count updates
        underlying_store._conn.execute("PRAGMA max_page_count = 100000")
        handle.receive(Fact(kind="note", ts=1002.0, payload={"i": 3}, observer="test"))
        assert handle.snapshot.visible_domain_count == 2
