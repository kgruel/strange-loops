"""Internal connection management for store databases.

Handles ULID extension loading, schema creation, WAL mode.
Not public API — used by slice, merge, search.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_ulid

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS facts (
    id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
    kind     TEXT NOT NULL,
    ts       REAL NOT NULL,
    observer TEXT NOT NULL,
    origin   TEXT NOT NULL DEFAULT '',
    payload  TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
CREATE INDEX IF NOT EXISTS idx_facts_ts   ON facts(ts);

CREATE TABLE IF NOT EXISTS ticks (
    id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
    name     TEXT NOT NULL,
    ts       REAL NOT NULL,
    since    REAL,
    origin   TEXT NOT NULL,
    payload  TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS idx_ticks_name ON ticks(name);
CREATE INDEX IF NOT EXISTS idx_ticks_ts   ON ticks(ts);
"""


def _load_ulid(conn: sqlite3.Connection) -> None:
    """Load the sqlite-ulid extension into a connection."""
    conn.enable_load_extension(True)
    sqlite_ulid.load(conn)
    conn.enable_load_extension(False)


def _open(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a store database with ULID extension loaded.

    Read-only mode uses URI to avoid WAL/SHM sidecars.
    Write mode sets WAL journal and NORMAL synchronous.
    """
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    _load_ulid(conn)
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
    _load_ulid(conn)
    conn.executescript(_SCHEMA)
    return conn
