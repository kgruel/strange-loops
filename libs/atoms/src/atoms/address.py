"""Address — the entity-reference value-object (kind, key).

One frozen ``(kind, key)`` pair with two constructors, replacing the five
ad-hoc string helpers that used to split, suffix-match, and qualify addresses
across resolve / vertex_reader / surface. Every parse/build/match boundary
converges here; the *stored/rendered* address stays the canonical ``kind:key``
string (``__str__``), so this is a contained value-object, not a typed field
(the ``Edge.address`` field remains ``str`` — arbiter S1-F1, STR-STAYS).

Three constructors — a single-answer parse, an all-interpretations reading
set, and a declaration-qualified edge builder — deliberate, not duplication:

* :meth:`parse` is the CANONICAL single answer for the self-describing ref
  corpus (``item.refs``, cited addresses) where one interpretation is needed —
  emit-time resolution and candidate-kind detection. ``kind:key`` (colon), the
  legacy ``kind/key`` (first-slash), or a bare separator-less key of unknown
  kind. The colon binds tighter than any ``/`` inside the key, so
  ``decision:design/foo`` is ``(decision, design/foo)``, not ``(decision,
  design)``. The legacy-slash branch is load-bearing and preserved
  indefinitely (arbiter S1-F2): live stores hold hundreds of ``kind/key``
  refs (``decision/atoms/n-on-fold-item`` → ``(decision, atoms/n-on-fold-item)``)
  that must keep resolving. Do not "simplify" the slash branch away.

* :meth:`readings` is for the MATCH/read path (inbound counting, ``←``
  adjacency), where a slash address is GENUINELY AMBIGUOUS and matches under
  EITHER interpretation, content-independently (no store lookup): ``x/y``
  yields BOTH ``(kind=x, key=y)`` (legacy kind-qualified) AND ``(kind='',
  key='x/y')`` (bare namespaced key). This is the sol-P1 correction: the
  namespace-prefix/kind-name collision is real (``design`` is both a topic
  prefix and a declared kind), so ``ref=design/foo`` must keep counting toward
  a ``decision`` keyed ``design/foo`` (bare reading) WITHOUT resurrecting the
  cross-kind colon alias (colon stays single, exact). The eventual
  disambiguator is the colon-form rewrite-at-rest migration ceremony, deferred
  per F2. ``parse`` returns ``readings()[0]`` — the primary (legacy) reading.

* :meth:`for_edge` is for DECLARATION-QUALIFIED edge values (``edge <field>
  targets=<kind>``). The declaration supplies the kind, so a bare value is
  licensed — ``stakeholder=acme`` with ``targets=person`` is ``(person,
  acme)``. A slashed value is qualified WHOLE, never split:
  ``stakeholder=design/foo`` is ``(person, design/foo)``, matching what the
  read-time edge lift produces. Only an explicit colon overrides the declared
  kind (``org:acme`` stays ``(org, acme)``).

Unifying parse and for_edge would reintroduce the emit/read disagreement this
module exists to fix: parse would slash-split a declared-edge ``design/foo``
into ``(design, foo)`` while the read lift qualifies it into ``(person,
design/foo)`` — the two paths would build different edges from the same value.
Keep them distinct.
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

        The STRICT canonical answer for single-answer call sites (emit
        resolution, candidate-kind detection). It equals ``readings()[0]`` for
        every well-formed address; the two diverge only on an empty-half slash
        (``/key``), where ``parse`` rejects (``None``) but ``readings`` keeps
        the degenerate bare whole-key reading for matching.
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
    def readings(cls, raw: str) -> tuple[Address, ...]:
        """ALL valid interpretations of a self-describing address, for MATCHING.

        Content-independent (no store lookup); a row matches an address if ANY
        reading matches it (exact ``(kind, key)``, or a bare ``kind=''`` reading
        matching the row's key under any kind). Ordered primary-first:

        * colon ``x:y`` → one reading ``kind=x, key=y`` — EXACT, single. Colon
          declares the kind unambiguously, so cross-kind aliases stay dead.
        * slash ``x/y`` → TWO readings: ``kind=x, key=y`` legacy kind-qualified
          (primary) AND ``kind='', key='x/y'`` bare namespaced key. The genuine
          ambiguity — ``design/foo`` may name a ``design``-kind ``foo`` OR a
          bare-keyed ``design/foo`` — is preserved, not guessed.
        * bare ``z`` (no separator) → one reading ``kind='', key=z``.

        Empty value, or a colon with an empty half, yields ``()``.
        """
        v = raw.strip()
        if not v:
            return ()
        if ":" in v:
            kind, key = v.split(":", 1)
            if not kind or not key:
                return ()
            return (cls(kind=kind, key=key),)
        if "/" in v:
            head, tail = v.split("/", 1)
            bare = cls(kind="", key=v)
            if head and tail:
                return (cls(kind=head, key=tail), bare)
            return (bare,)
        return (cls(kind="", key=v),)

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
