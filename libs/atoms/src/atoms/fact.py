"""Fact — the observation atom.

Manual implementation (no @dataclass) to avoid importing the dataclasses
module (~13ms) at import time. Provides frozen-dataclass-compatible behavior
including dataclasses.replace() support via __replace__.
"""

from __future__ import annotations

import time
from types import MappingProxyType


class _LazyDataclassFields:
    """Descriptor that installs __dataclass_fields__ on first access."""

    def __set_name__(self, owner, name):
        self._name = name
        self._owner = owner

    def __get__(self, obj, objtype=None):
        cls = objtype or type(obj)
        # Install real __dataclass_fields__ and __dataclass_params__
        import dataclasses
        fields = {}
        for name, default in [("kind", dataclasses.MISSING), ("ts", dataclasses.MISSING),
                               ("payload", dataclasses.MISSING), ("observer", dataclasses.MISSING),
                               ("origin", "")]:
            if default is dataclasses.MISSING:
                f = dataclasses.field()
            else:
                f = dataclasses.field(default=default)
            f.name = name
            f._field_type = dataclasses._FIELD
            fields[name] = f
        cls.__dataclass_fields__ = fields
        cls.__dataclass_params__ = dataclasses._DataclassParams(
            init=True, repr=True, eq=True, order=False, unsafe_hash=False, frozen=True,
            match_args=True, kw_only=False, slots=True, weakref_slot=False,
        )
        return fields


class Fact:
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

    __slots__ = ("kind", "ts", "payload", "observer", "origin")
    __match_args__ = ("kind", "ts", "payload", "observer", "origin")
    __dataclass_fields__ = _LazyDataclassFields()

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, kind: str, ts: float, payload=None, observer: str = "", origin: str = "") -> None:
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "ts", ts)
        if isinstance(payload, dict):
            object.__setattr__(self, "payload", MappingProxyType(dict(payload)))
        else:
            object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "observer", observer)
        object.__setattr__(self, "origin", origin)

    def __setattr__(self, name, value):
        from dataclasses import FrozenInstanceError
        raise FrozenInstanceError("cannot assign to field")

    def __delattr__(self, name):
        from dataclasses import FrozenInstanceError
        raise FrozenInstanceError("cannot assign to field")

    def __eq__(self, other):
        if not isinstance(other, Fact):
            return NotImplemented
        return (self.kind, self.ts, self.payload, self.observer, self.origin) == \
               (other.kind, other.ts, other.payload, other.observer, other.origin)

    def __hash__(self):
        try:
            return hash((self.kind, self.ts, self.payload, self.observer, self.origin))
        except TypeError:
            return hash((self.kind, self.ts, id(self.payload), self.observer, self.origin))

    def __repr__(self):
        return (f"Fact(kind={self.kind!r}, ts={self.ts!r}, payload={self.payload!r}, "
                f"observer={self.observer!r}, origin={self.origin!r})")

    def __replace__(self, **changes):
        """Support dataclasses.replace() and copy.replace()."""
        return type(self)(
            kind=changes.get("kind", self.kind),
            ts=changes.get("ts", self.ts),
            payload=changes.get("payload", self.payload),
            observer=changes.get("observer", self.observer),
            origin=changes.get("origin", self.origin),
        )

    @classmethod
    def of(cls, kind: str, observer: str, *, origin: str = "", ts: float | None = None, **data) -> Fact:
        """Create a Fact with auto-timestamp and dict payload."""
        return cls(kind=kind, ts=ts if ts is not None else time.time(), payload=data, observer=observer, origin=origin)

    @classmethod
    def tick(cls, name: str, observer: str, *, origin: str = "", ts: float | None = None, **data) -> Fact:
        """Create a boundary-related Fact with tick. prefix."""
        return cls(kind=f"tick.{name}", ts=ts if ts is not None else time.time(), payload=data, observer=observer, origin=origin)

    def to_dict(self) -> dict:
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
    def from_dict(cls, d: dict) -> Fact:
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
