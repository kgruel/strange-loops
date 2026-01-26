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
    """

    kind: str
    ts: float
    payload: T

    def __post_init__(self) -> None:
        """Wrap dict payloads in MappingProxyType for immutability."""
        if isinstance(self.payload, dict):
            object.__setattr__(
                self, "payload", MappingProxyType(dict(self.payload))
            )

    @classmethod
    def of(cls, kind: str, **data: Any) -> Fact[dict]:
        """Create a Fact with auto-timestamp and dict payload.

        Args:
            kind: Domain-specific routing key
            **data: Keyword arguments become the dict payload
        """
        return cls(kind=kind, ts=time.time(), payload=data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for serialization."""
        payload = dict(self.payload) if isinstance(self.payload, MappingProxyType) else self.payload
        return {
            "kind": self.kind,
            "ts": self.ts,
            "payload": payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Fact:
        """Reconstruct a Fact from a dict."""
        return cls(
            kind=d["kind"],
            ts=float(d["ts"]),
            payload=d["payload"],
        )

    def is_kind(self, *kinds: str) -> bool:
        """Check if this fact's kind matches any of the given kinds."""
        return self.kind in kinds
