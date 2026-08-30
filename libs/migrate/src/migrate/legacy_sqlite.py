"""Legacy SQLite reader — frozen read spine for canonical SQLite stores.

Historical artifact copied from ``store.rebirth`` at commit
``affe92a6fc1a034b477cbc068cc563f6e5ca69e6``.

This module provides the READ-ONLY SQLite spine for migration:
- Open legacy SQLite databases strictly read-only (URI mode ``file:...?mode=ro``);
- Compute witness-order content hash (verifiable claim);
- Read historical fact rows and tick columns in witness (rowid) order.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .legacy_ids import FactRow

__all__ = [
    "open_legacy_sqlite",
    "read_facts",
    "read_ticks",
    "_tick_columns",
    "_facts_have_signature",
    "_content_sha256",
]

_TICK_BASE_COLS = ("id", "name", "ts", "since", "origin", "payload")
_TICK_CHAIN_COLS = (
    "prev_hash",
    "window_start",
    "fact_cursor",
    "window_hash",
    "signature",
)


def open_legacy_sqlite(path: Path | str) -> sqlite3.Connection:
    """Open a legacy SQLite database strictly read-only."""
    path_obj = Path(path).resolve()
    if not path_obj.exists():
        raise FileNotFoundError(f"Legacy sqlite source not found: {path_obj}")
    return sqlite3.connect(f"file:{path_obj}?mode=ro", uri=True)


def _tick_columns(conn: sqlite3.Connection) -> list[str]:
    """Tick columns present in this store, canonical order, era-aware."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
    return [c for c in (*_TICK_BASE_COLS, *_TICK_CHAIN_COLS) if c in have]


def _facts_have_signature(conn: sqlite3.Connection) -> bool:
    """Whether this store's facts table carries the delta-3 signature column."""
    return "signature" in {
        r[1] for r in conn.execute("PRAGMA table_info(facts)")
    }


def _content_sha256(conn: sqlite3.Connection) -> str:
    """Witness-order content hash: every fact row in rowid order, then every tick row.

    This is the SAME-FORMAT row-content identity of a SQLite store's contents.
    It hashes all facts in rowid order, then all ticks in rowid order. It is
    stable across re-reads and invariant to physical file rewrites (VACUUM),
    but is NOT comparable across formats (JSONL hashes in line order).
    """
    h = hashlib.sha256()
    sig_col = _facts_have_signature(conn)
    for row in conn.execute(
        "SELECT id, kind, ts, observer, origin, payload"
        + (", signature" if sig_col else "")
        + " FROM facts ORDER BY rowid"
    ):
        # Era-aware: the signature joins the row hash only when non-NULL,
        # so a store's content hash is stable across the column's arrival
        # (same posture as engine's fact row hash).
        if sig_col and row[6] is None:
            row = row[:6]
        h.update(json.dumps(list(row), separators=(",", ":")).encode())
    cols = _tick_columns(conn)
    for row in conn.execute(
        f"SELECT {', '.join(cols)} FROM ticks ORDER BY rowid"
    ):
        h.update(json.dumps(list(row), separators=(",", ":")).encode())
    return h.hexdigest()


def read_facts(conn: sqlite3.Connection) -> list[FactRow]:
    """Read all fact rows from legacy SQLite store in rowid order."""
    sig_col = _facts_have_signature(conn)
    rows: list[FactRow] = []
    for raw in conn.execute(
        "SELECT id, kind, ts, observer, origin, payload"
        + (", signature" if sig_col else "")
        + " FROM facts ORDER BY rowid"
    ):
        rows.append(FactRow(*raw) if sig_col else FactRow(*raw, signature=None))
    return rows


def read_ticks(conn: sqlite3.Connection) -> list[dict]:
    """Read all tick rows from legacy SQLite store in rowid order."""
    cols = _tick_columns(conn)
    ticks: list[dict] = []
    for raw in conn.execute(
        f"SELECT {', '.join(cols)} FROM ticks ORDER BY rowid"
    ):
        ticks.append(dict(zip(cols, raw, strict=True)))
    return ticks
