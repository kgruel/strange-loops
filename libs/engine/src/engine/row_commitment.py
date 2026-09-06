"""Pure commitments for persisted fact and tick rows.

These functions have no store or connection dependency. The SQLite writer,
Arrival runtime planner, and readers that verify chain evidence use the same
row bytes so a new write path cannot quietly fork an existing chain.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from .admission import _canonical_bytes

__all__ = ["fact_row_hash", "tick_commitment_hash", "tick_envelope", "tick_row_hash"]


def tick_envelope(row: tuple) -> dict:
    """The ten tick fields that its inner signature commits to."""
    return {
        "id": row[0], "name": row[1], "ts": row[2], "since": row[3],
        "origin": row[4], "payload": row[5], "prev_hash": row[6],
        "window_start": row[7], "fact_cursor": row[8], "window_hash": row[9],
    }


def tick_commitment_hash(
    row: tuple, *, canonical_bytes: Callable[[object], bytes] = _canonical_bytes
) -> str:
    """Hash one tick's signed content, excluding its signature field."""
    return hashlib.sha256(canonical_bytes(tick_envelope(row))).hexdigest()


def tick_row_hash(
    row: tuple, *, canonical_bytes: Callable[[object], bytes] = _canonical_bytes
) -> str:
    """Hash one tick row as its successor's ``prev_hash`` value."""
    envelope = tick_envelope(row)
    if len(row) > 10 and row[10] is not None:
        envelope["signature"] = row[10]
    return hashlib.sha256(canonical_bytes(envelope)).hexdigest()


def fact_row_hash(
    row: tuple, *, canonical_bytes: Callable[[object], bytes] = _canonical_bytes
) -> str:
    """Hash one fact row for a tick window, preserving exact payload text."""
    envelope = {
        "id": row[0], "kind": row[1], "ts": row[2],
        "observer": row[3], "origin": row[4], "payload": row[5],
    }
    if len(row) > 6 and row[6] is not None:
        envelope["signature"] = row[6]
    return hashlib.sha256(canonical_bytes(envelope)).hexdigest()
