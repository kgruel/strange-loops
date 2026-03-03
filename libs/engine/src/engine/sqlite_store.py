"""SqliteStore — SQLite-backed append-only event store.

Implements the Store protocol with durable persistence. Facts are stored
with kind, ts, observer as real columns (SQL-queryable) and payload as
JSON text (queryable via json_extract()).

Uses WAL mode for concurrent reads during folds. ULID primary keys for
globally-unique identity and merge compatibility with libs/store.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Generic, TypeVar

import sqlite_ulid

from .tick import Tick

T = TypeVar("T")

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
CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts);

CREATE TABLE IF NOT EXISTS ticks (
    id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
    name     TEXT NOT NULL,
    ts       REAL NOT NULL,
    since    REAL,
    origin   TEXT NOT NULL,
    payload  TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS idx_ticks_name ON ticks(name);
CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts);
"""


class SqliteStore(Generic[T]):
    """Append-only SQLite event store.

    Cursor semantics: since(cursor) returns rows with rowid > cursor,
    matching EventStore's logical index behavior (0 = all events).
    """

    def __init__(
        self,
        *,
        path: Path,
        serialize: Callable[[T], dict],
        deserialize: Callable[[dict], T],
    ) -> None:
        self._path = Path(path)
        self._serialize = serialize
        self._deserialize = deserialize

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.enable_load_extension(True)
        sqlite_ulid.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def append(self, event: T) -> None:
        """Append one event to the store."""
        d = self._serialize(event)
        self._conn.execute(
            "INSERT INTO facts (kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?)",
            (d["kind"], d["ts"], d["observer"], d.get("origin", ""), json.dumps(d["payload"])),
        )
        self._conn.commit()

    async def consume(self, event: T) -> None:
        """Consumer protocol: append event to store."""
        self.append(event)

    def since(self, cursor: int) -> list[T]:
        """Return events with rowid > cursor.

        cursor=0 returns all events (rowid starts at 1 in SQLite).
        """
        rows = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts WHERE rowid > ? ORDER BY rowid",
            (cursor,),
        ).fetchall()
        return [
            self._deserialize(
                {"kind": r[0], "ts": r[1], "observer": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    def between(self, start: datetime | float, end: datetime | float) -> list[T]:
        """Return events in the time range [start, end]."""
        start_ts = start.timestamp() if isinstance(start, datetime) else start
        end_ts = end.timestamp() if isinstance(end, datetime) else end

        rows = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts WHERE ts >= ? AND ts <= ? ORDER BY rowid",
            (start_ts, end_ts),
        ).fetchall()
        return [
            self._deserialize(
                {"kind": r[0], "ts": r[1], "observer": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    @property
    def total(self) -> int:
        """Total number of events in the store."""
        row = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()
        return row[0]

    def append_tick(self, tick: Tick) -> None:
        """Append a tick to the ticks table."""
        d = tick.to_dict()
        self._conn.execute(
            "INSERT INTO ticks (name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?)",
            (d["name"], d["ts"], d["since"], d["origin"], json.dumps(d["payload"])),
        )
        self._conn.commit()

    def ticks_since(self, cursor: int) -> list[Tick]:
        """Return ticks with rowid > cursor."""
        rows = self._conn.execute(
            "SELECT name, ts, since, origin, payload FROM ticks WHERE rowid > ? ORDER BY rowid",
            (cursor,),
        ).fetchall()
        return [
            Tick.from_dict(
                {"name": r[0], "ts": r[1], "since": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    def ticks_between(self, start: datetime | float, end: datetime | float) -> list[Tick]:
        """Return ticks in the time range [start, end]."""
        start_ts = start.timestamp() if isinstance(start, datetime) else start
        end_ts = end.timestamp() if isinstance(end, datetime) else end
        rows = self._conn.execute(
            "SELECT name, ts, since, origin, payload FROM ticks WHERE ts >= ? AND ts <= ? ORDER BY rowid",
            (start_ts, end_ts),
        ).fetchall()
        return [
            Tick.from_dict(
                {"name": r[0], "ts": r[1], "since": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    @property
    def tick_total(self) -> int:
        """Total number of ticks in the store."""
        row = self._conn.execute("SELECT COUNT(*) FROM ticks").fetchone()
        return row[0]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SqliteStore[T]:
        return self

    def __exit__(self, *args) -> None:
        self.close()
