"""Tick — the temporal atom."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Tick(Generic[T]):
    """Frozen temporal snapshot: timestamp + payload.

    A Tick wraps any payload with the timestamp of when a temporal
    boundary fell.  It is the output of folding events through a Shape
    over a time period.

    The payload is generic:
      Tick[Event]       — single fact, stamped with observation time
      Tick[list[Event]] — batch of facts grouped into a time window
      Tick[dict]        — folded state snapshot at a boundary
    """

    ts: datetime
    payload: T
