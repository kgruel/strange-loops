"""Fact — the observation atom."""

from __future__ import annotations

import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Fact(Generic[T]):
    """An intentional observation — something that happened at a specific time.

    Kind is an open string (no enum, no constrained set). Structure comes
    from Shape, not from kind.

    Attributes:
        kind: Open, domain-specific routing key ("heartbeat", "deploy", etc.)
        ts: Epoch seconds (float) — when observed. Display formatting is caller's problem.
        payload: The details — Shape knows the structure
        observer: Who produced this observation (required)
        origin: Which loop/vertex produced this fact ("" for external observations,
                non-empty for derived facts from tick-to-fact bridging)
    """

    kind: str
    ts: float
    payload: T
    observer: str
    origin: str = ""

    def __post_init__(self) -> None:
        """Wrap dict payloads in MappingProxyType for immutability."""
        if isinstance(self.payload, dict):
            object.__setattr__(
                self, "payload", MappingProxyType(dict(self.payload))
            )

    @classmethod
    def of(cls, kind: str, observer: str, *, origin: str = "", **data: Any) -> Fact[dict]:
        """Create a Fact with auto-timestamp and dict payload.

        Args:
            kind: Domain-specific routing key
            observer: Who produced this observation
            origin: Which loop produced this (empty for external observations)
            **data: Keyword arguments become the dict payload
        """
        return cls(kind=kind, ts=time.time(), payload=data, observer=observer, origin=origin)

    @classmethod
    def tick(cls, name: str, observer: str, *, origin: str = "", **data: Any) -> Fact[dict]:
        """Create a boundary-related Fact with tick. prefix.

        Args:
            name: Boundary name — auto-prefixed to kind="tick.{name}"
            observer: Who produced this observation
            origin: Which loop produced this (empty for external observations)
            **data: Keyword arguments become the dict payload
        """
        return cls(kind=f"tick.{name}", ts=time.time(), payload=data, observer=observer, origin=origin)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for serialization."""
        payload = dict(self.payload) if isinstance(self.payload, MappingProxyType) else self.payload
        return {
            "kind": self.kind,
            "ts": self.ts,
            "payload": payload,
            "observer": self.observer,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Fact:
        """Reconstruct a Fact from a dict."""
        return cls(
            kind=d["kind"],
            ts=float(d["ts"]),
            payload=d["payload"],
            observer=d["observer"],
            origin=d.get("origin", ""),
        )

    def is_kind(self, *kinds: str) -> bool:
        """Check if this fact's kind matches any of the given kinds."""
        return self.kind in kinds
