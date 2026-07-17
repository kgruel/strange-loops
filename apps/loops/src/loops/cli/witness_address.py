"""cli.witness_address — the ``--at`` address grammar (0.8.0 temporal cursor, C1).

Maps the user-facing address forms onto a single fact id, then hands it to
``engine.resolve_witness_position`` — which owns identity resolution
(primary-key lookup only, A3), the receipt-group guard (A2), the adoption
marker (N1), and the tick anchor (A12). This module is CLI-layer address
PARSING only; it never re-implements witness resolution itself.

Address grammar (SPEC session-1 contract, s1-arbitration.md):

  head          — the newest received fact (frozen once resolved)
  fact:ID       — a full fact id, or an unambiguous prefix of one
  seq:N         — the Nth receipt ordinal (1-based, ``_decl.*`` included)
  tick:ID       — a tick's own id; resolves via its ``fact_cursor``
  <ISO date/datetime> — wall-clock, snapped to the tick FLOOR (A5): the last
                  sealed, chained tick at-or-before the mark. No usable tick
                  ⇒ refuse with teaching (never a silent ts-approximation;
                  the caller retypes ``--as-of`` for the event-time mode).

Aggregates (combine/discover): witness positions are per-store (A1/A9) —
every ``--at`` form is refused here, before ever reaching the engine, with a
message tailored to the form (member-scoped handles vs. "not yet built").
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.witness import WitnessPosition


class AddressError(Exception):
    """A malformed or unresolvable ``--at``/``--diff`` address — CLI-layer,
    exit 2 with a teaching message. Distinct from the engine's
    ``WitnessResolutionError`` family (which this module lets propagate
    unchanged for anything already engine-shaped: unknown handle, mid-group,
    aggregate-unsupported)."""


def is_aggregate_vertex(vertex_path: Path) -> bool:
    """True when the vertex declares ``combine``/``discover`` (no single store)."""
    from lang import parse_vertex_file

    ast = parse_vertex_file(vertex_path)
    return ast.combine is not None or ast.discover is not None


def classify_address_form(address: str) -> str:
    """Which grammar form ``address`` names — for aggregate-refusal messaging
    and dispatch, before any store I/O."""
    if address == "head":
        return "head"
    if address.startswith("fact:"):
        return "fact"
    if address.startswith("seq:"):
        return "seq"
    if address.startswith("tick:"):
        return "tick"
    return "wallclock"


#: Teaching messages for --at against an aggregate vertex, by address form
#: (A9: seq:/fact: are member-scoped; tick:/wall-clock/head need per-member
#: cursor vectors, designed but not built in 0.8.0 — honest deferral, A9).
_AGGREGATE_REFUSAL = {
    "seq": (
        "--at seq:/fact: handles are member-scoped — this vertex is an "
        "aggregate (combine/discover) with no shared witness order across "
        "members (A1/A9). Address a member vertex directly."
    ),
    "fact": (
        "--at seq:/fact: handles are member-scoped — this vertex is an "
        "aggregate (combine/discover) with no shared witness order across "
        "members (A1/A9). Address a member vertex directly."
    ),
    "tick": (
        "--at against an aggregate needs one cursor per member store — "
        "per-member cursor vectors are designed but not yet implemented "
        "(0.8.0). Use --as-of for a uniform event-time read across members, "
        "or address a member vertex directly."
    ),
    "wallclock": (
        "--at against an aggregate needs one cursor per member store — "
        "per-member cursor vectors are designed but not yet implemented "
        "(0.8.0). Use --as-of for a uniform event-time read across members, "
        "or address a member vertex directly."
    ),
    "head": (
        "--at against an aggregate needs one cursor per member store — "
        "per-member cursor vectors are designed but not yet implemented "
        "(0.8.0). Use --as-of for a uniform event-time read across members, "
        "or address a member vertex directly."
    ),
}


def refuse_aggregate_at(address: str) -> AddressError:
    """Build the teaching refusal for ``--at`` against an aggregate vertex."""
    form = classify_address_form(address)
    return AddressError(_AGGREGATE_REFUSAL[form])


def _expand_fact_prefix(store_path: Path, prefix: str) -> str:
    """Resolve a (possibly partial) fact id to its full canonical id.

    Exact match first, then unambiguous prefix — mirrors
    ``StoreReader.fact_by_id``'s exact-then-prefix resolution.
    ``include_internal=True``: witness identity is over ALL rows regardless
    of kind (a ``_decl.*`` row is still a valid, addressable position — the
    receipt-group guard, not kind, is what may refuse it).
    """
    from engine.store_reader import StoreReader

    if not prefix:
        raise AddressError(
            "`--at fact:` needs an id (e.g. `--at fact:01J...`)"
        )
    with StoreReader(store_path) as reader:
        try:
            found = reader.fact_by_id(prefix, include_internal=True)
        except ValueError as exc:
            raise AddressError(str(exc)) from exc
    if found is None:
        raise AddressError(
            f"no fact matches `fact:{prefix}` in this store"
        )
    return found["id"]


def _parse_wallclock(address: str) -> float:
    """Parse a strict ISO-8601 date-or-datetime to an epoch ts (UTC default).

    Distinct from ``--as-of``'s duration-friendly parsing (``7d`` etc.) — the
    ``--at`` wall-clock form is only the address grammar's dated form, which
    then snaps to the tick floor (A5); a relative duration has no meaningful
    "floor" semantics here.
    """
    try:
        dt = datetime.fromisoformat(address)
    except ValueError as exc:
        raise AddressError(
            f"`--at {address!r}` is not a recognized address — expected "
            "head / fact:ID / seq:N / tick:ID / an ISO-8601 date or datetime"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def resolve_at_address(store_path: Path, address: str) -> "WitnessPosition":
    """Resolve a ``--at`` address to a :class:`~engine.witness.WitnessPosition`.

    Maps each grammar form onto a fact id and calls
    ``resolve_witness_position`` for the actual position — the receipt-group
    guard, adoption marker, and tick anchor all come from that single engine
    seam regardless of which form produced the id. For a wall-clock/``tick:``
    snap, the resulting position's ``.anchor`` IS the tick that was resolved
    (the anchor recomputation lands on the exact same tick), so the snap is
    reported for free by rendering ``.anchor`` — no separate bookkeeping.

    Propagates engine errors unchanged (``UnknownWitnessHandle``,
    ``MidReceiptGroupPosition``, ``SeqOutOfRange``, ``UnknownTickHandle``,
    ``NoWitnessAnchor``); raises :class:`AddressError` for CLI-layer grammar
    problems (empty/malformed forms, ambiguous fact prefix).
    """
    from engine.witness import (
        resolve_seq,
        resolve_tick_cursor,
        resolve_tick_floor,
        resolve_witness_position,
    )

    form = classify_address_form(address)

    if form == "head":
        return resolve_witness_position(store_path, "head")

    if form == "fact":
        fid = _expand_fact_prefix(store_path, address[len("fact:"):])
        return resolve_witness_position(store_path, fid)

    if form == "seq":
        raw = address[len("seq:"):]
        try:
            n = int(raw)
        except ValueError as exc:
            raise AddressError(
                f"`--at seq:{raw}` needs an integer receipt ordinal"
            ) from exc
        fid = resolve_seq(store_path, n)
        return resolve_witness_position(store_path, fid)

    if form == "tick":
        raw = address[len("tick:"):]
        if not raw:
            raise AddressError("`--at tick:` needs a tick id (e.g. `--at tick:01J...`)")
        fid, _name, _ts = resolve_tick_cursor(store_path, raw)
        return resolve_witness_position(store_path, fid)

    # wall-clock — ISO date-or-datetime, snap to the tick floor (A5).
    mark_ts = _parse_wallclock(address)
    fid, _name, _ts = resolve_tick_floor(store_path, mark_ts)
    return resolve_witness_position(store_path, fid)
