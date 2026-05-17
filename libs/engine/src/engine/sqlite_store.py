"""SqliteStore — SQLite-backed append-only event store.

Implements the Store protocol with durable persistence. Facts are stored
with kind, ts, observer as real columns (SQL-queryable) and payload as
JSON text (queryable via json_extract()).

Uses WAL mode for concurrent reads during folds. IDs are ULIDs generated
Python-side via python-ulid (26-char Crockford base32, time-sortable,
within-ms monotonic). Time-sortability is load-bearing for cross-store
fact interleaving (ORDER BY id ≈ chronological) and for merge dedup
on slice→merge round-trips via INSERT OR IGNORE on the id PK.

History: 2026-03-15 to 2026-05-16 a perf-driven change swapped to
uuid.uuid4() to avoid loading the sqlite-ulid C extension per connection
(~0.5ms dlopen). That swap dropped the time-sortable property without
naming the substrate contract. Restored 2026-05-16 via pure-Python
python-ulid (no dlopen, ~2.3μs/id, negligible at this scale). See
project decision architecture/id-primitive-python-ulid.
"""

from __future__ import annotations

import json
import sqlite3

from ulid import ULID

# Pre-created decoder for faster JSON parsing in hot paths.
# raw_decode skips strip() and end-position validation — safe for SQLite
# payloads which are always well-formed JSON without whitespace padding.
_raw_decode = json.JSONDecoder().raw_decode


def _gen_id() -> str:
    """Generate a unique ID for store records.

    Uses python-ulid: 26-char Crockford base32 ULID, time-sortable
    (lexicographic order matches generation time), within-ms monotonic
    (sequential calls within the same millisecond have incrementing
    suffixes). Pure Python — no C extension, no dlopen cost.
    """
    return str(ULID())
from datetime import datetime, timezone as _tz

_UTC = _tz.utc
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

# IDs generated Python-side via python-ulid (see _gen_id above).
# The sqlite-ulid C extension is no longer loaded — it was only needed
# when id generation happened SQL-side via the schema's DEFAULT (ulid())
# clause. INSERTs supply id explicitly, so the SQL-callable ulid()
# function is not required. The DEFAULT clause in _SCHEMA_STMTS below
# is vestigial from that era and will be removed once we confirm no
# external tooling relies on it.


def _mapping_proxy_default(obj: object) -> object:
    """Handle MappingProxyType in JSON serialization."""
    from types import MappingProxyType
    if isinstance(obj, MappingProxyType):
        return dict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

from .tick import Tick

T = TypeVar("T")

_SCHEMA_STMTS = (
    """CREATE TABLE IF NOT EXISTS facts (
        id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
        kind     TEXT NOT NULL,
        ts       REAL NOT NULL,
        observer TEXT NOT NULL,
        origin   TEXT NOT NULL DEFAULT '',
        payload  TEXT NOT NULL CHECK (json_valid(payload))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind)",
    "CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts)",
    """CREATE TABLE IF NOT EXISTS ticks (
        id       TEXT NOT NULL PRIMARY KEY DEFAULT (ulid()),
        name     TEXT NOT NULL,
        ts       REAL NOT NULL,
        since    REAL,
        origin   TEXT NOT NULL,
        payload  TEXT NOT NULL CHECK (json_valid(payload))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ticks_name ON ticks(name)",
    "CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts)",
)


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
        self._direct_fact_build: bool | None = None  # lazy detection
        self._fact_class: type | None = None

        try:
            is_new = self._path.stat().st_size == 0
        except OSError:
            is_new = True
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        if is_new:
            # New DB — set WAL (persistent) and synchronous, create schema
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            for stmt in _SCHEMA_STMTS:
                self._conn.execute(stmt)
            self._sync_set = True
        else:
            # Existing DB: skip schema + pragmas — WAL is persistent,
            # schema already exists, first real query triggers schema load.
            # Defer synchronous=NORMAL to first write (after schema is loaded).
            self._sync_set = False

    def _detect_fact_build(self) -> None:
        """Detect if deserializer is Fact.from_dict for direct construction."""
        self._direct_fact_build = False
        deserialize = self._deserialize
        if hasattr(deserialize, '__self__') and hasattr(deserialize.__self__, '__name__'):
            self._fact_class = deserialize.__self__
            self._direct_fact_build = True
        elif hasattr(deserialize, '__func__'):
            try:
                from atoms import Fact
                if deserialize.__func__ is Fact.from_dict.__func__:
                    self._fact_class = Fact
                    self._direct_fact_build = True
            except (ImportError, AttributeError):
                pass

    def _ensure_sync(self) -> None:
        """Set synchronous=NORMAL before first write. Deferred so schema load
        happens on first read (replay_into) rather than on pragma."""
        if not self._sync_set:
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._sync_set = True

    def append(self, event: T, *, id_override: str | None = None) -> str:
        """Append one event to the store. Returns the ID assigned.

        If id_override is provided, that ID is used; otherwise a new ID
        is generated via _gen_id(). The ID is returned in either case so
        callers (e.g. emit's receipt path) can reference the stored row.
        """
        self._ensure_sync()
        d = self._serialize(event)
        fact_id = id_override if id_override is not None else _gen_id()
        self._conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (fact_id, d["kind"], d["ts"], d["observer"], d.get("origin", ""), json.dumps(d["payload"])),
        )
        self._conn.commit()
        return fact_id

    async def consume(self, event: T, *, id_override: str | None = None) -> None:
        """Consumer protocol: append event to store."""
        self.append(event, id_override=id_override)

    def since(self, cursor: int) -> list[T]:
        """Return events with rowid > cursor.

        cursor=0 returns all events (rowid starts at 1 in SQLite).
        """
        rows = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts WHERE rowid > ? ORDER BY rowid",
            (cursor,),
        ).fetchall()
        loads = _raw_decode
        # Fast path: build Facts directly when deserializer is Fact.from_dict
        # Avoids intermediate dict allocation per row
        if self._direct_fact_build is None:
            self._detect_fact_build()
        if self._direct_fact_build:
            return [
                self._fact_class(kind=r[0], ts=r[1], observer=r[2], origin=r[3], payload=loads(r[4])[0])
                for r in rows
            ]
        deserialize = self._deserialize
        return [
            deserialize(
                {"kind": r[0], "ts": r[1], "observer": r[2], "origin": r[3], "payload": loads(r[4])[0]}
            )
            for r in rows
        ]

    def since_raw(self, cursor: int) -> list[tuple[str, dict]]:
        """Return (kind, payload) tuples for replay — no Fact construction.

        Avoids MappingProxyType wrapping and full Fact dataclass overhead.
        Only returns the fields needed for fold replay.
        """
        rows = self._conn.execute(
            "SELECT kind, payload FROM facts WHERE rowid > ? ORDER BY rowid",
            (cursor,),
        ).fetchall()
        loads = _raw_decode
        return [(r[0], loads(r[1])[0]) for r in rows]

    def replay_cursor(self, cursor: int):
        """Yield (kind, payload) pairs by streaming from the SQL cursor.

        No intermediate list allocation — rows are decoded and yielded
        one at a time. The caller handles fold dispatch; the store just
        provides data. This keeps fold logic in the Projection layer
        where it belongs.
        """
        loads = _raw_decode
        for r in self._conn.execute(
            "SELECT kind, payload FROM facts WHERE rowid > ? ORDER BY rowid",
            (cursor,),
        ):
            yield r[0], loads(r[1])[0]

    def last_tick_ts(self, name: str) -> datetime | None:
        """Return the timestamp of the most recent tick with the given name.

        Optimized query for replay period tracking — avoids loading all ticks.
        """
        row = self._conn.execute(
            "SELECT ts FROM ticks WHERE name = ? ORDER BY rowid DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromtimestamp(row[0], tz=_UTC)

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
        self._ensure_sync()
        d = tick.to_dict()
        self._conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (_gen_id(), d["name"], d["ts"], d["since"], d["origin"],
             json.dumps(d["payload"], default=_mapping_proxy_default)),
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

    def latest_by_kind(self, kind: str) -> T | None:
        """Return the most recent fact of a given kind, or None."""
        row = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts WHERE kind = ? ORDER BY rowid DESC LIMIT 1",
            (kind,),
        ).fetchone()
        if row is None:
            return None
        return self._deserialize(
            {"kind": row[0], "ts": row[1], "observer": row[2], "origin": row[3], "payload": json.loads(row[4])}
        )

    def latest_by_kind_where(self, kind: str, key: str, value: Any) -> T | None:
        """Return the most recent fact of kind where payload[key] == value."""
        path = "$." + key
        row = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts "
            "WHERE kind = ? AND json_extract(payload, ?) = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (kind, path, value),
        ).fetchone()
        if row is None:
            return None
        return self._deserialize(
            {"kind": row[0], "ts": row[1], "observer": row[2], "origin": row[3], "payload": json.loads(row[4])}
        )

    def has_kind_since(self, kind: str, ts: float) -> bool:
        """True if any fact of kind exists with ts > the given timestamp."""
        row = self._conn.execute(
            "SELECT 1 FROM facts WHERE kind = ? AND ts > ? LIMIT 1",
            (kind, ts),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SqliteStore[T]:
        return self

    def __exit__(self, *args) -> None:
        self.close()
