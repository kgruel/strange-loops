"""Internal connection management for store databases.

Schema creation, WAL mode, read-only URI opens. Not public API —
used by slice, merge, search.

IDs are supplied by writers (engine.SqliteStore._gen_id() for fresh emits,
SELECT'd through for ATTACH-DATABASE cross-store ops in slice/merge). The
schema declares id as TEXT PRIMARY KEY with no DEFAULT — every INSERT
must supply an id. This is the post-2026-05-16 shape; prior to that the
schema used DEFAULT (ulid()) backed by the sqlite-ulid C extension, which
was needed only because some inserts omitted id. All production paths now
supply id explicitly, so the extension is no longer required.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS facts (
    id       TEXT NOT NULL PRIMARY KEY,
    kind     TEXT NOT NULL,
    ts       REAL NOT NULL,
    observer TEXT NOT NULL,
    origin   TEXT NOT NULL DEFAULT '',
    payload  TEXT NOT NULL CHECK (json_valid(payload)),
    signature TEXT
);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
CREATE INDEX IF NOT EXISTS idx_facts_ts   ON facts(ts);

CREATE TABLE IF NOT EXISTS ticks (
    id           TEXT NOT NULL PRIMARY KEY,
    name         TEXT NOT NULL,
    ts           REAL NOT NULL,
    since        REAL,
    origin       TEXT NOT NULL,
    payload      TEXT NOT NULL CHECK (json_valid(payload)),
    prev_hash    TEXT,
    window_start TEXT,
    fact_cursor  TEXT,
    window_hash  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ticks_name ON ticks(name);
CREATE INDEX IF NOT EXISTS idx_ticks_ts   ON ticks(ts);
"""


def _open(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a store database.

    Read-only mode uses URI to avoid WAL/SHM sidecars.
    Write mode sets WAL journal and NORMAL synchronous.
    """
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _create(path: Path) -> sqlite3.Connection:
    """Create a fresh store with canonical schema.

    Parent directories are created if needed.
    Raises FileExistsError if the database file already exists.
    """
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"Store already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    return conn
