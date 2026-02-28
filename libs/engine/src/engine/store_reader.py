"""StoreReader — read-only inspector for SqliteStore databases."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .tick import Tick


class StoreReader:
    """Read-only connection to a SqliteStore database.

    Opens the database with PRAGMA query_only=ON. Does not create
    the file or parent directories — raises FileNotFoundError if
    the path does not exist.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"Store not found: {self._path}")

        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA query_only=ON")

    @property
    def fact_total(self) -> int:
        """Total number of facts in the store."""
        row = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()
        return row[0]

    @property
    def tick_total(self) -> int:
        """Total number of ticks in the store."""
        row = self._conn.execute("SELECT COUNT(*) FROM ticks").fetchone()
        return row[0]

    def fact_kind_stats(self) -> dict[str, dict]:
        """Per-kind fact counts and time ranges."""
        rows = self._conn.execute(
            "SELECT kind, COUNT(*), MIN(ts), MAX(ts) FROM facts GROUP BY kind"
        ).fetchall()
        return {
            r[0]: {
                "count": r[1],
                "earliest": datetime.fromtimestamp(r[2], tz=timezone.utc),
                "latest": datetime.fromtimestamp(r[3], tz=timezone.utc),
            }
            for r in rows
        }

    def tick_name_stats(self) -> dict[str, dict]:
        """Per-name tick counts and time ranges."""
        rows = self._conn.execute(
            "SELECT name, COUNT(*), MIN(ts), MAX(ts) FROM ticks GROUP BY name"
        ).fetchall()
        return {
            r[0]: {
                "count": r[1],
                "earliest": datetime.fromtimestamp(r[2], tz=timezone.utc),
                "latest": datetime.fromtimestamp(r[3], tz=timezone.utc),
            }
            for r in rows
        }

    def summary(self) -> dict:
        """Aggregate store contents into a summary dict."""
        return {
            "facts": {
                "total": self.fact_total,
                "kinds": self.fact_kind_stats(),
            },
            "ticks": {
                "total": self.tick_total,
                "names": self.tick_name_stats(),
            },
        }

    def tick_timestamps(self, name: str, limit: int | None = None) -> list[float]:
        """Raw timestamps for a tick name, newest first. No payload parsing."""
        query = "SELECT ts FROM ticks WHERE name = ? ORDER BY ts DESC"
        params: list = [name]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return [r[0] for r in self._conn.execute(query, params).fetchall()]

    def recent_ticks(self, name: str, n: int) -> list[Tick]:
        """Last N ticks for a given name, newest first."""
        rows = self._conn.execute(
            "SELECT name, ts, since, origin, payload FROM ticks "
            "WHERE name = ? ORDER BY ts DESC LIMIT ?",
            (name, n),
        ).fetchall()
        return [
            Tick.from_dict(
                {"name": r[0], "ts": r[1], "since": r[2], "origin": r[3], "payload": json.loads(r[4])}
            )
            for r in rows
        ]

    @property
    def freshness(self) -> datetime | None:
        """Timestamp of the most recent fact, or None if store is empty."""
        row = self._conn.execute("SELECT MAX(ts) FROM facts").fetchone()
        if row[0] is None:
            return None
        return datetime.fromtimestamp(row[0], tz=timezone.utc)

    def facts_between(
        self,
        since_ts: float,
        until_ts: float,
        kind: str | None = None,
    ) -> list[dict]:
        """Facts within a time range, optionally filtered by kind."""
        if kind is not None:
            rows = self._conn.execute(
                "SELECT kind, ts, observer, origin, payload FROM facts "
                "WHERE ts >= ? AND ts <= ? AND (kind = ? OR kind LIKE ?) ORDER BY ts",
                (since_ts, until_ts, kind, kind + ".%"),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT kind, ts, observer, origin, payload FROM facts "
                "WHERE ts >= ? AND ts <= ? ORDER BY ts",
                (since_ts, until_ts),
            ).fetchall()
        return [
            {
                "kind": r[0],
                "ts": datetime.fromtimestamp(r[1], tz=timezone.utc),
                "observer": r[2],
                "origin": r[3],
                "payload": json.loads(r[4]),
            }
            for r in rows
        ]

    def recent_facts(self, kind: str, n: int) -> list[dict]:
        """Last N facts for a given kind, newest first. Returns raw dicts."""
        rows = self._conn.execute(
            "SELECT kind, ts, observer, origin, payload FROM facts "
            "WHERE kind = ? ORDER BY ts DESC LIMIT ?",
            (kind, n),
        ).fetchall()
        return [
            {
                "kind": r[0],
                "ts": datetime.fromtimestamp(r[1], tz=timezone.utc),
                "observer": r[2],
                "origin": r[3],
                "payload": json.loads(r[4]),
            }
            for r in rows
        ]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> StoreReader:
        return self

    def __exit__(self, *args) -> None:
        self.close()
