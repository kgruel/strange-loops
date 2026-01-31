"""Tick — the temporal atom."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Tick(Generic[T]):
    """Frozen temporal snapshot: the output primitive of a loop.

    A Tick is what a loop produces when a temporal boundary fires.
    It carries what cycle completed (name), when (ts), the folded
    state at that boundary (payload), and which vertex produced it
    (origin). The tree of origins is reconstructable from nested
    payloads — each Tick is a node, not the tree.

    The payload is generic:
      Tick[Event]       — single fact, stamped with observation time
      Tick[list[Event]] — batch of facts grouped into a time window
      Tick[dict]        — folded state snapshot at a boundary
    """

    name: str
    ts: datetime
    payload: T
    origin: str = ""
