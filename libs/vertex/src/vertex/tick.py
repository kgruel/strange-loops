"""Tick — the temporal atom."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

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

    Fidelity traversal:
      If `since` is set, the tick represents the period [since, ts].
      Use Store.between(tick.since, tick.ts) to retrieve the facts
      that were folded to produce this tick's payload.
    """

    name: str
    ts: datetime
    payload: T
    origin: str = ""
    since: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ts": self.ts.timestamp(),
            "payload": self.payload,
            "origin": self.origin,
            "since": self.since.timestamp() if self.since else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Tick:
        return cls(
            name=d["name"],
            ts=datetime.fromtimestamp(d["ts"], tz=timezone.utc),
            payload=d["payload"],
            origin=d.get("origin", ""),
            since=datetime.fromtimestamp(d["since"], tz=timezone.utc) if d.get("since") else None,
        )
