"""Fold: transformation rules for how facts become state.

Typed fold classes: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max

These provide type safety, IDE support, and self-documenting code.
"""

from __future__ import annotations

from dataclasses import dataclass


# =============================================================================
# Primitive folds — direct mappings to fundamental operations
# =============================================================================


@dataclass(frozen=True)
class Latest:
    """Store timestamp of last event.

    Updates target with the event's _ts field (or current time if missing).

    Attributes:
        target: State facet name to update.

    Example:
        Latest(target="last_seen")
        # {"_ts": 1234567890} → state["last_seen"] = 1234567890
    """

    target: str


@dataclass(frozen=True)
class Count:
    """Increment counter on each event.

    Attributes:
        target: State facet name to increment.

    Example:
        Count(target="events")
        # Each event: state["events"] += 1
    """

    target: str


@dataclass(frozen=True)
class Sum:
    """Add field value to accumulator.

    Attributes:
        target: State facet name to accumulate into.
        field: Payload field to read value from.

    Example:
        Sum(target="total", field="amount")
        # {"amount": 10} → state["total"] += 10
    """

    target: str
    field: str


@dataclass(frozen=True)
class Collect:
    """Append events to bounded list.

    Attributes:
        target: State facet name (must be list).
        max: Maximum items to keep. 0 = unbounded.

    Example:
        Collect(target="history", max=100)
        # Keeps last 100 events
    """

    target: str
    max: int = 0


@dataclass(frozen=True)
class Upsert:
    """Insert/update by key into dict.

    Attributes:
        target: State facet name (must be dict).
        key: Payload field to use as dict key.

    Example:
        Upsert(target="users", key="id")
        # {"id": "alice", "name": "Alice"} → state["users"]["alice"] = payload
    """

    target: str
    key: str


# =============================================================================
# Convenience folds — compositions of primitives for common patterns
# =============================================================================


@dataclass(frozen=True)
class TopN:
    """Keep top N items by field value (sorted).

    Conceptually: Upsert + sort + slice. Maintains a dict of items keyed by
    a unique identifier, sorted by a numeric field, keeping only the top N.

    Use cases:
        - Top 5 processes by CPU
        - Top 10 users by score
        - Highest N values seen

    Attributes:
        target: State facet name (must be dict).
        key: Payload field to use as unique identifier.
        by: Payload field to sort by (must be numeric).
        n: How many items to keep.
        desc: Sort descending (highest first). Default True.

    Example:
        TopN(target="top_procs", key="pid", by="cpu", n=5)
        # Keeps top 5 processes by CPU usage, keyed by pid

    Implementation note:
        Could be expressed as: Upsert → sort → slice
        But as a primitive, avoids repeated sorting on every read.
    """

    target: str
    key: str
    by: str
    n: int
    desc: bool = True


@dataclass(frozen=True)
class Min:
    """Track minimum value seen.

    Conceptually: fold(min, current, new). Compares incoming field value
    against stored minimum, keeps the smaller.

    Attributes:
        target: State facet name to store minimum.
        field: Payload field to read value from.

    Example:
        Min(target="coldest", field="temp")
        # Tracks lowest temperature seen

    Implementation note:
        Equivalent to: if payload[field] < state[target]: state[target] = payload[field]
        But handles initialization (None → first value) cleanly.
    """

    target: str
    field: str


@dataclass(frozen=True)
class Max:
    """Track maximum value seen.

    Conceptually: fold(max, current, new). Compares incoming field value
    against stored maximum, keeps the larger.

    Attributes:
        target: State facet name to store maximum.
        field: Payload field to read value from.

    Example:
        Max(target="peak", field="memory")
        # Tracks highest memory usage seen

    Implementation note:
        Equivalent to: if payload[field] > state[target]: state[target] = payload[field]
        But handles initialization (None → first value) cleanly.
    """

    target: str
    field: str


# =============================================================================
# Type alias for any fold operation
# =============================================================================

FoldOp = Latest | Count | Sum | Collect | Upsert | TopN | Min | Max
