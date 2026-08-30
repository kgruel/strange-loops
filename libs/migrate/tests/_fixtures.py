"""Synthetic legacy fixture builders for tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# Facts: 5 standalone + 2 in a batch line = 7 fact rows total
# 1. UUID4 era, concept, alice, signed
FACT_UUID4_SIGNED = {
    "t": "fact",
    "id": "c56a4180-65aa-42ec-a945-5fd21dec0538",
    "kind": "concept",
    "ts": 1000.0,
    "observer": "alice",
    "origin": "origin-alice",
    "payload": '{"text":"fact 1"}',
    "signature": "sig-alice-1",
}
# 2. UUID4 era, claim, bob, unsigned
FACT_UUID4_UNSIGNED = {
    "t": "fact",
    "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "kind": "claim",
    "ts": 1001.0,
    "observer": "bob",
    "origin": "origin-bob",
    "payload": '{"text":"fact 2"}',
}
# 3. Lowercase ULID era, concept, alice, unsigned
FACT_LOWER_ULID_UNSIGNED = {
    "t": "fact",
    "id": "01arz3ndektsv4rrffq69g5fav",
    "kind": "concept",
    "ts": 1002.0,
    "observer": "alice",
    "origin": "origin-alice",
    "payload": '{"text":"fact 3"}',
}
# 4. Canonical ULID era, event, alice, signed
FACT_CANONICAL_ULID_SIGNED = {
    "t": "fact",
    "id": "01ARZ3NDEKTSV4RRFFQ69G5FA0",
    "kind": "event",
    "ts": 1003.0,
    "observer": "alice",
    "origin": "origin-alice",
    "payload": '{"text":"fact 4"}',
    "signature": "sig-alice-4",
}
# 5. Canonical ULID era, claim, carol, unsigned
FACT_CANONICAL_ULID_UNSIGNED = {
    "t": "fact",
    "id": "01ARZ3NDEKTSV4RRFFQ69G5FA1",
    "kind": "claim",
    "ts": 1004.0,
    "observer": "carol",
    "origin": "origin-carol",
    "payload": '{"text":"fact 5"}',
}

# Single-observer batch line (alice, 2 fact rows)
# 6. batch row 1: canonical ULID, concept, alice, unsigned
BATCH_ROW_1 = {
    "t": "fact",
    "id": "01ARZ3NDEKTSV4RRFFQ69G5FB1",
    "kind": "concept",
    "ts": 1005.0,
    "observer": "alice",
    "origin": "origin-alice",
    "payload": '{"text":"batch fact 1"}',
}
# 7. batch row 2: canonical ULID, claim, alice, signed (F7b)
BATCH_ROW_2 = {
    "t": "fact",
    "id": "01ARZ3NDEKTSV4RRFFQ69G5FB2",
    "kind": "claim",
    "ts": 1005.0,
    "observer": "alice",
    "origin": "origin-alice",
    "payload": '{"text":"batch fact 2"}',
    "signature": "sig-alice-batch-2",
}
BATCH_LINE_ALICE = {
    "t": "batch",
    "rows": [BATCH_ROW_1, BATCH_ROW_2],
}

# Ticks (2 tick rows)
TICK_1 = {
    "t": "tick",
    "id": "01ARZ3NDEKTSV4RRFFQ69G5FT1",
    "name": "heartbeat",
    "ts": 1006.0,
    "since": 1000.0,
    "origin": "system",
    "payload": '{"seq":1}',
    "prev_hash": None,
    "window_start": None,
    "fact_cursor": None,
    "window_hash": None,
}
TICK_2 = {
    "t": "tick",
    "id": "01ARZ3NDEKTSV4RRFFQ69G5FT2",
    "name": "checkpoint",
    "ts": 1007.0,
    "since": 1006.0,
    "origin": "system",
    "payload": '{"seq":2}',
    "prev_hash": "prevhash123",
    "window_start": "01ARZ3NDEKTSV4RRFFQ69G5FT1",
    "fact_cursor": "01ARZ3NDEKTSV4RRFFQ69G5FB2",
    "window_hash": "winhash123",
    "signature": "sig-tick-2",
}

ALL_FACT_ROWS = [
    FACT_UUID4_SIGNED,
    FACT_UUID4_UNSIGNED,
    FACT_LOWER_ULID_UNSIGNED,
    FACT_CANONICAL_ULID_SIGNED,
    FACT_CANONICAL_ULID_UNSIGNED,
    BATCH_ROW_1,
    BATCH_ROW_2,
]

ALL_TICK_ROWS = [
    TICK_1,
    TICK_2,
]

EXPECTED_HAND_COMPUTED_COUNTS = {
    "jsonl": {
        "source_format": "jsonl-canonical",
        "total_rows": 9,  # 5 facts + 2 batch facts + 2 ticks
        "total_lines": 8,  # 5 facts + 1 batch line + 2 ticks
        "per_kind_counts": {"concept": 3, "claim": 3, "event": 1},
        "tick_count": 2,
        "batch_line_count": 1,
        "observer_census": {"alice": 5, "bob": 1, "carol": 1},
        "id_era_census": {"other": 2, "lowercase-ulid": 1, "canonical-ulid": 4},
    },
    "sqlite": {
        "source_format": "sqlite-canonical",
        "total_rows": 9,  # 7 facts + 2 ticks
        "total_lines": None,  # SQLite has no concept of lines
        "per_kind_counts": {"concept": 3, "claim": 3, "event": 1},
        "tick_count": 2,
        "batch_line_count": None,  # SQLite cannot carry batch envelopes
        "observer_census": {"alice": 5, "bob": 1, "carol": 1},
        "id_era_census": {"other": 2, "lowercase-ulid": 1, "canonical-ulid": 4},
    },
}


def build_synthetic_jsonl(path: Path) -> Path:
    """Write standard synthetic legacy JSONL source to path."""
    lines = [
        FACT_UUID4_SIGNED,
        FACT_UUID4_UNSIGNED,
        FACT_LOWER_ULID_UNSIGNED,
        FACT_CANONICAL_ULID_SIGNED,
        FACT_CANONICAL_ULID_UNSIGNED,
        BATCH_LINE_ALICE,
        TICK_1,
        TICK_2,
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")
    return path


def build_synthetic_sqlite(path: Path) -> Path:
    """Create standard synthetic legacy SQLite source at path with identical rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE facts (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                ts REAL NOT NULL,
                observer TEXT NOT NULL,
                origin TEXT NOT NULL,
                payload TEXT NOT NULL,
                signature TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE ticks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ts REAL NOT NULL,
                since REAL,
                origin TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT,
                window_start TEXT,
                fact_cursor TEXT,
                window_hash TEXT,
                signature TEXT
            )
            """
        )
        for r in ALL_FACT_ROWS:
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    r["kind"],
                    r["ts"],
                    r["observer"],
                    r["origin"],
                    r["payload"],
                    r.get("signature"),
                ),
            )
        for t in ALL_TICK_ROWS:
            conn.execute(
                "INSERT INTO ticks (id, name, ts, since, origin, payload, prev_hash, "
                "window_start, fact_cursor, window_hash, signature) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    t["id"],
                    t["name"],
                    t["ts"],
                    t.get("since"),
                    t["origin"],
                    t["payload"],
                    t.get("prev_hash"),
                    t.get("window_start"),
                    t.get("fact_cursor"),
                    t.get("window_hash"),
                    t.get("signature"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def build_mixed_observer_jsonl(path: Path) -> Path:
    """Build a synthetic JSONL legacy store with TWO mixed-observer batch lines."""
    line_1_fact = {
        "t": "fact",
        "id": "01ARZ3NDEKTSV4RRFFQ69G5FA1",
        "kind": "concept",
        "ts": 100.0,
        "observer": "alice",
        "origin": "origin",
        "payload": "{}",
    }
    line_2_mixed_batch = {
        "t": "batch",
        "rows": [
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FB1",
                "kind": "concept",
                "ts": 101.0,
                "observer": "kyle",
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FB2",
                "kind": "claim",
                "ts": 101.0,
                "observer": "someone-else",
                "origin": "origin",
                "payload": "{}",
            },
        ],
    }
    line_3_fact = {
        "t": "fact",
        "id": "01ARZ3NDEKTSV4RRFFQ69G5FA2",
        "kind": "claim",
        "ts": 102.0,
        "observer": "bob",
        "origin": "origin",
        "payload": "{}",
    }
    line_4_mixed_batch = {
        "t": "batch",
        "rows": [
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FC1",
                "kind": "concept",
                "ts": 103.0,
                "observer": "alice",
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FC2",
                "kind": "claim",
                "ts": 103.0,
                "observer": "bob",
                "origin": "origin",
                "payload": "{}",
            },
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in [line_1_fact, line_2_mixed_batch, line_3_fact, line_4_mixed_batch]:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")
    return path


def build_absent_observer_jsonl(path: Path) -> Path:
    """Build a synthetic JSONL legacy store with a batch line having a missing observer field."""
    line_1_fact = {
        "t": "fact",
        "id": "01ARZ3NDEKTSV4RRFFQ69G5FA1",
        "kind": "concept",
        "ts": 100.0,
        "observer": "alice",
        "origin": "origin",
        "payload": "{}",
    }
    line_2_absent_batch = {
        "t": "batch",
        "rows": [
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FB1",
                "kind": "concept",
                "ts": 101.0,
                # 'observer' is deliberately missing
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FB2",
                "kind": "claim",
                "ts": 101.0,
                "observer": "alice",
                "origin": "origin",
                "payload": "{}",
            },
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in [line_1_fact, line_2_absent_batch]:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")
    return path


def build_combined_defects_jsonl(path: Path) -> Path:
    """Build a synthetic JSONL legacy store with ALL THREE defect classes together:
    - Line 1: legal fact (alice)
    - Line 2: codec-invalid batch (unknown field in envelope)
    - Line 3: legal tick
    - Line 4: mixed-observer batch (kyle, someone-else)
    - Line 5: legal fact (bob)
    - Line 6: absent-observer batch (missing observer in one row, alice in other)
    - Line 7: legal fact (carol)
    """
    line_1 = {
        "t": "fact",
        "id": "01ARZ3NDEKTSV4RRFFQ69G5FA1",
        "kind": "concept",
        "ts": 100.0,
        "observer": "alice",
        "origin": "origin",
        "payload": "{}",
    }
    line_2_codec_invalid = {
        "t": "batch",
        "unknown_extra": 123,
        "rows": [
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FB1",
                "kind": "concept",
                "ts": 101.0,
                "observer": "alice",
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FB2",
                "kind": "claim",
                "ts": 101.0,
                "observer": "alice",
                "origin": "origin",
                "payload": "{}",
            },
        ],
    }
    line_3 = {
        "t": "tick",
        "id": "01ARZ3NDEKTSV4RRFFQ69G5FT1",
        "name": "heartbeat",
        "ts": 102.0,
        "since": 100.0,
        "origin": "system",
        "payload": "{}",
        "prev_hash": None,
        "window_start": None,
        "fact_cursor": None,
        "window_hash": None,
    }
    line_4_mixed = {
        "t": "batch",
        "rows": [
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FC1",
                "kind": "concept",
                "ts": 103.0,
                "observer": "kyle",
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FC2",
                "kind": "claim",
                "ts": 103.0,
                "observer": "someone-else",
                "origin": "origin",
                "payload": "{}",
            },
        ],
    }
    line_5 = {
        "t": "fact",
        "id": "01ARZ3NDEKTSV4RRFFQ69G5FA2",
        "kind": "claim",
        "ts": 104.0,
        "observer": "bob",
        "origin": "origin",
        "payload": "{}",
    }
    line_6_absent = {
        "t": "batch",
        "rows": [
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FD1",
                "kind": "concept",
                "ts": 105.0,
                # observer missing
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FD2",
                "kind": "claim",
                "ts": 105.0,
                "observer": "alice",
                "origin": "origin",
                "payload": "{}",
            },
        ],
    }
    line_7 = {
        "t": "fact",
        "id": "01ARZ3NDEKTSV4RRFFQ69G5FA3",
        "kind": "event",
        "ts": 106.0,
        "observer": "carol",
        "origin": "origin",
        "payload": "{}",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in [line_1, line_2_codec_invalid, line_3, line_4_mixed, line_5, line_6_absent, line_7]:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")
    return path


def build_both_aspects_batch_jsonl(path: Path) -> Path:
    """Build a JSONL file with a batch exhibiting BOTH mixed and absent aspects:
    rows with alice, bob, and one observerless row.
    """
    line_both_aspects = {
        "t": "batch",
        "rows": [
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FE1",
                "kind": "concept",
                "ts": 100.0,
                "observer": "alice",
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FE2",
                "kind": "claim",
                "ts": 100.0,
                "observer": "bob",
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FE3",
                "kind": "event",
                "ts": 100.0,
                # observer missing
                "origin": "origin",
                "payload": "{}",
            },
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(line_both_aspects, separators=(",", ":")) + "\n")
    return path


def build_type_error_batch_jsonl(path: Path) -> Path:
    """Build a JSONL file with a batch having a non-string observer (dict),
    which must land cleanly in codec-invalid rather than raising TypeError.
    """
    line_type_error = {
        "t": "batch",
        "rows": [
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FF1",
                "kind": "concept",
                "ts": 100.0,
                "observer": {"nested": "dict"},
                "origin": "origin",
                "payload": "{}",
            },
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FF2",
                "kind": "claim",
                "ts": 100.0,
                "observer": "alice",
                "origin": "origin",
                "payload": "{}",
            },
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(line_type_error, separators=(",", ":")) + "\n")
    return path


def build_flat_equivalent_jsonl(path: Path) -> Path:
    """Write standard synthetic legacy JSONL with the 2 batch rows unrolled flat."""
    lines = [
        FACT_UUID4_SIGNED,
        FACT_UUID4_UNSIGNED,
        FACT_LOWER_ULID_UNSIGNED,
        FACT_CANONICAL_ULID_SIGNED,
        FACT_CANONICAL_ULID_UNSIGNED,
        BATCH_ROW_1,
        BATCH_ROW_2,
        TICK_1,
        TICK_2,
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")
    return path


def build_empty_observer_sqlite(path: Path) -> Path:
    """Create a legacy SQLite database containing rows with observer=''."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE facts (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                ts REAL NOT NULL,
                observer TEXT NOT NULL,
                origin TEXT NOT NULL,
                payload TEXT NOT NULL,
                signature TEXT
            )
            """
        )
        # Row 1: valid fact (alice)
        conn.execute(
            "INSERT INTO facts VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA1', 'concept', 100.0, 'alice', 'origin', '{}', NULL)"
        )
        # Row 2: empty observer ''
        conn.execute(
            "INSERT INTO facts VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA2', 'claim', 101.0, '', 'origin', '{}', NULL)"
        )
        # Row 3: empty observer ''
        conn.execute(
            "INSERT INTO facts VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA3', 'event', 102.0, '', 'origin', '{}', NULL)"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def build_codec_invalid_sqlite(path: Path) -> Path:
    """Create a legacy SQLite database containing a row with ts as TEXT."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE facts (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                ts REAL NOT NULL,
                observer TEXT NOT NULL,
                origin TEXT NOT NULL,
                payload TEXT NOT NULL,
                signature TEXT
            )
            """
        )
        # Row 1: ts stored as TEXT
        conn.execute(
            "INSERT INTO facts VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA1', 'concept', 'invalid-ts-text', 'alice', 'origin', '{}', NULL)"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def build_unsafe_integer_ts_sqlite(path: Path) -> Path:
    """Create a legacy SQLite database containing a fact row whose INTEGER ts holds 2**60."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE facts (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                ts INTEGER NOT NULL,
                observer TEXT NOT NULL,
                origin TEXT NOT NULL,
                payload TEXT NOT NULL,
                signature TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO facts VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA1', 'concept', ?, 'alice', 'origin', '{}', NULL)",
            (2**60,),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def build_era1_sqlite(path: Path) -> Path:
    """Create an era-1 legacy SQLite database whose ticks table lacks chain columns and since."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE facts (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                ts REAL NOT NULL,
                observer TEXT NOT NULL,
                origin TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE ticks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ts REAL NOT NULL,
                origin TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO facts VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA1', 'concept', 1000.0, 'alice', 'origin-alice', '{\"text\":\"fact 1\"}')"
        )
        conn.execute(
            "INSERT INTO ticks VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FT1', 'heartbeat', 1006.0, 'system', '{\"seq\":1}')"
        )
        conn.execute(
            "INSERT INTO ticks VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FT2', 'checkpoint', 1007.0, 'system', '{\"seq\":2}')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


