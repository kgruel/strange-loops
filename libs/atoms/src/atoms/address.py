"""Address — the entity-reference value-object (kind, key).

One frozen ``(kind, key)`` pair with two constructors, replacing the five
ad-hoc string helpers that used to split, suffix-match, and qualify addresses
across resolve / vertex_reader / surface. Every parse/build/match boundary
converges here; the *stored/rendered* address stays the canonical ``kind:key``
string (``__str__``), so this is a contained value-object, not a typed field
(the ``Edge.address`` field remains ``str`` — arbiter S1-F1, STR-STAYS).

Two populations, two parse rules — deliberate, not duplication:

* :meth:`parse` is for the SELF-DESCRIBING ref corpus (``item.refs``, cited
  addresses). The address carries its own kind: ``kind:key`` (colon), or the
  legacy ``kind/key`` (first-slash), or a bare separator-less key of unknown
  kind. The colon binds tighter than any ``/`` inside the key, so
  ``decision:design/foo`` is ``(decision, design/foo)``, not ``(decision,
  design)``. The legacy-slash branch is load-bearing and preserved
  indefinitely (arbiter S1-F2): live stores hold hundreds of ``kind/key``
  refs (``decision/atoms/n-on-fold-item`` → ``(decision, atoms/n-on-fold-item)``)
  that must keep resolving. Do not "simplify" the slash branch away.

* :meth:`for_edge` is for DECLARATION-QUALIFIED edge values (``edge <field>
  targets=<kind>``). The declaration supplies the kind, so a bare value is
  licensed — ``stakeholder=acme`` with ``targets=person`` is ``(person,
  acme)``. A slashed value is qualified WHOLE, never split:
  ``stakeholder=design/foo`` is ``(person, design/foo)``, matching what the
  read-time edge lift produces. Only an explicit colon overrides the declared
  kind (``org:acme`` stays ``(org, acme)``).

Unifying the two rules would reintroduce the emit/read disagreement this
module exists to fix: :meth:`parse` would slash-split a declared-edge
``design/foo`` into ``(design, foo)`` while the read lift qualifies it into
``(person, design/foo)`` — the two paths would build different edges from the
same value. Keep them distinct.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Address:
    """A resolved entity reference: a ``kind`` and a ``key``.

    ``kind`` is ``""`` for a bare (separator-less) key whose kind is unknown —
    such an address matches any kind bearing the key (the bare fallback in
    inbound matching). Equality is exact on ``(kind, key)``; a bare key never
    aliases a kind-qualified one.
    """

    kind: str
    key: str

    def __str__(self) -> str:
        """The canonical rendered form: ``kind:key``, or the bare key."""
        return f"{self.kind}:{self.key}" if self.kind else self.key

    @classmethod
    def parse(cls, raw: str) -> Address | None:
        """Parse a SELF-DESCRIBING ref address into ``(kind, key)``.

        Colon-first (the colon binds tighter than key slashes), then the
        legacy first-slash form, else a bare separator-less key with
        ``kind=""``. Returns ``None`` for an empty value or a separator with
        an empty half (``:key`` / ``kind:`` / ``/key`` / ``kind/``).
        """
        v = raw.strip()
        if not v:
            return None
        if ":" in v:
            kind, key = v.split(":", 1)
        elif "/" in v:
            kind, key = v.split("/", 1)
        else:
            return cls(kind="", key=v)
        if not kind or not key:
            return None
        return cls(kind=kind, key=key)

    @classmethod
    def for_edge(cls, value: str, target_kind: str) -> Address | None:
        """Parse a DECLARATION-QUALIFIED edge value into ``(kind, key)``.

        An explicit colon is honored verbatim (kind before the first colon);
        otherwise the WHOLE value is qualified with ``target_kind`` — the
        declaration licenses a bare or slashed key without splitting it.
        Returns ``None`` for an empty value.
        """
        v = value.strip()
        if not v:
            return None
        if ":" in v:
            kind, key = v.split(":", 1)
            return cls(kind=kind, key=key)
        return cls(kind=target_kind, key=v)
