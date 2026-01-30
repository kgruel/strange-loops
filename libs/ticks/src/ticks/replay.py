"""Replay: recover vertex state from stored facts.

On startup, replay feeds stored facts back into the vertex in order.
The vertex routes and folds as normal, reconstructing state from history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from facts import Fact
    from .store import Store
    from .vertex import Vertex


def replay(vertex: Vertex, store: "Store[Fact]", *, from_cursor: int = 0) -> int:
    """Replay stored facts into vertex, return cursor position after replay.

    Facts are received with grant=None — they were already permitted when
    first recorded. The vertex routes by kind and folds as normal.

    Args:
        vertex: The vertex to replay into
        store: Store containing facts to replay
        from_cursor: Start from this position (for incremental replay)

    Returns:
        Cursor position after replay (store.total)
    """
    for fact in store.since(from_cursor):
        vertex.receive(fact, grant=None)
    return store.total
