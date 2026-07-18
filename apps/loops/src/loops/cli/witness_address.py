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

    Store access belongs to the engine — the resolution is
    ``engine.expand_fact_prefix`` (exact-then-prefix over all rows); this thin
    wrapper only handles the CLI-grammar concerns: the empty ``fact:`` form and
    turning the engine's no-match / ambiguous-prefix errors into an
    :class:`AddressError`.
    """
    from engine.witness import UnknownWitnessHandle, expand_fact_prefix

    if not prefix:
        raise AddressError(
            "`--at fact:` needs an id (e.g. `--at fact:01J...`)"
        )
    try:
        return expand_fact_prefix(store_path, prefix)
    except ValueError as exc:  # ambiguous prefix (two facts share it)
        raise AddressError(str(exc)) from exc
    except UnknownWitnessHandle as exc:
        raise AddressError(
            f"no fact matches `fact:{prefix}` in this store"
        ) from exc


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
    guard and adoption marker come from that single engine seam regardless of
    which form produced the id. For a wall-clock/``tick:`` snap the tick we
    resolved IS the anchor to report, so it is passed through as ``anchor=`` and
    PRESERVED on the position — re-deriving it from the cursor could name a
    different tick when several ticks seal the same ``fact_cursor``, one of them
    possibly after the requested mark (review finding 7a).

    Propagates engine errors unchanged (``UnknownWitnessHandle``,
    ``MidReceiptGroupPosition``, ``SeqOutOfRange``, ``UnknownTickHandle``,
    ``NoWitnessAnchor``); raises :class:`AddressError` for CLI-layer grammar
    problems (empty/malformed forms, ambiguous fact prefix).
    """
    from engine.witness import (
        TickAnchor,
        resolve_seq,
        resolve_tick_cursor,
        resolve_tick_floor,
        resolve_witness_position,
    )

    form = classify_address_form(address)

    if form == "head":
        return resolve_witness_position(store_path, "head")

    if form == "fact":
        raw = address[len("fact:"):]
        if "/" in raw:
            # Durable, lineage-qualified handle `fact:<lineage>/<id>` (A10, B1).
            # The lineage guards cross-store reuse: resolve the id in THIS store
            # and refuse unless this store's own lineage matches — so the same
            # advertised handle can never silently mean a different prefix after
            # a merge copies the fact into another lineage.
            lineage_q, _, id_part = raw.partition("/")
            if not lineage_q or not id_part:
                raise AddressError(
                    "`--at fact:<lineage>/<id>` needs both a lineage and an id"
                )
            fid = _expand_fact_prefix(store_path, id_part)
            pos = resolve_witness_position(store_path, fid)
            if pos.unadopted:
                raise AddressError(
                    f"`--at fact:{lineage_q}/…` is a lineage-qualified handle but "
                    "this store is unadopted (no lineage) — the handle cannot "
                    "belong here. Adopt the store, or address it in-session."
                )
            if pos.lineage != lineage_q:
                raise AddressError(
                    f"`--at fact:{lineage_q}/…` does not match this store's "
                    f"lineage ({pos.lineage}) — a durable handle resolves only "
                    "against its own lineage (A10)."
                )
            return pos
        fid = _expand_fact_prefix(store_path, raw)
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
        fid, name, ts = resolve_tick_cursor(store_path, raw)
        # Floor boundary mode (M3): a tick/wall-clock snap lands where the
        # SEALED tick left off, not on a user-named exact row — the ratified
        # contract snaps these floor forms before a ceremony's first row
        # rather than refusing (fact:/seq: keep the "refuse" default; they
        # name an exact row, so landing mid-ceremony IS a user error).
        return resolve_witness_position(
            store_path, fid,
            anchor=TickAnchor(name=name, ts=ts, fact_cursor=fid),
            group_boundary="floor",
        )

    # wall-clock — ISO date-or-datetime, snap to the tick floor (A5).
    mark_ts = _parse_wallclock(address)
    fid, name, ts = resolve_tick_floor(store_path, mark_ts)
    return resolve_witness_position(
        store_path, fid,
        anchor=TickAnchor(name=name, ts=ts, fact_cursor=fid),
        group_boundary="floor",
    )
