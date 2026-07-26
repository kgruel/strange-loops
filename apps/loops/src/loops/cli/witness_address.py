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

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.witness import CutSummary, TickAnchor, WitnessPosition


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


# --- Honest seal-cut provenance (0.9.0, S6) ---------------------------------
#
# The head-cut resolution primitive: "which sealed cut (if any) is newest at
# or behind head, is head itself sealed, how many ticks exist, how many
# facts sit beyond the last seal" — for ANY read, not only an explicit --at.
# Reuses the SAME witness machinery above rather than a second store-access
# path (S6 arbitration F3 — S4's --review header/head-cursor disclosure
# MUST reuse this resolution, not stand up its own).


@dataclass(frozen=True)
class CutMeta:
    """Honest seal-cut provenance for one read — the ``cut`` render_context/
    JSON contract (0.9.0 S6).

    ``available=False`` is a genuine, confidently-known state (aggregate
    vertex, no/uncreated store, an --as-of event-time read, or an engine
    resolution failure) — ``reason`` is always stated, never left for a
    consumer to guess from a missing key (the defect this slice closes: the
    external homelab-audit lens's "Live unsealed fold" guess from a bare
    ``projection=None`` default).

    ``tick_total``/``facts_beyond_seal`` are ``None`` when the answering mode
    didn't resolve them — the ``mode="witness"`` case (an active ``--at``
    read) reuses an ALREADY-resolved :class:`~engine.witness.WitnessPosition`
    and deliberately does no extra store I/O, so those two derived counts
    are honestly "not computed here" rather than a guessed value.
    """

    available: bool
    #: "head" (default read), "witness" (--at), "as_of" (--as-of), or
    #: "unavailable" (aggregate / no store / resolution failure).
    mode: str
    anchor: dict | None = None
    sealed_to_head: bool = False
    tick_total: int | None = None
    facts_beyond_seal: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        """JSON-safe, uniformly-shaped dict — every key always present so a
        consumer never has to branch on which keys exist before reading one
        (``reason`` is simply ``None`` when ``available`` is ``True``)."""
        return {
            "available": self.available,
            "mode": self.mode,
            "anchor": self.anchor,
            "sealed_to_head": self.sealed_to_head,
            "tick_total": self.tick_total,
            "facts_beyond_seal": self.facts_beyond_seal,
            "reason": self.reason,
        }


def _anchor_to_dict(anchor: "TickAnchor | None") -> dict | None:
    """JSON-clean projection of a bare :class:`~engine.witness.TickAnchor`.

    Sibling of ``cli.views.fold._anchor_dict`` (which projects off a
    ``WitnessPosition``) — kept separate rather than shared so the existing
    ``--at``/``--as-of`` cursor logic stays untouched by this slice.
    """
    if anchor is None:
        return None
    return {"name": anchor.name, "ts": anchor.ts, "fact_cursor": anchor.fact_cursor}


def unavailable_cut(mode: str, reason: str) -> dict:
    """The ``{"available": False, "reason": ...}`` shape, for every refusal
    path (aggregate, no store, --as-of, resolution failure) — one source so
    the shape never drifts across call sites."""
    return CutMeta(available=False, mode=mode, reason=reason).to_dict()


def cut_from_witness_position(position: "WitnessPosition") -> dict:
    """Cut provenance derived from an ALREADY-RESOLVED witness position —
    zero extra store I/O. Called for an active ``--at`` read (and, per S6
    arbitration F3, the function S4's ``--review``/head-cursor work must
    reuse rather than re-resolving head a second time).

    ``tick_total``/``facts_beyond_seal`` are not resolved here — both need a
    query beyond what the position itself carries, and the whole point of
    this path is to add zero I/O to an already-completed ``--at`` resolution
    (AC7). Use :func:`resolve_cut` for the richer, freshly-resolved default
    (head) read, which affords itself those extra cheap reads.
    """
    anchor = position.anchor
    sealed_to_head = anchor is not None and anchor.fact_cursor == position.fact_id
    return CutMeta(
        available=True,
        mode="witness",
        anchor=_anchor_to_dict(anchor),
        sealed_to_head=sealed_to_head,
        tick_total=None,
        facts_beyond_seal=None,
    ).to_dict()


def resolve_cut(vertex_path: Path) -> dict:
    """The default (head) read's honest seal-cut provenance dict.

    Wraps :func:`is_aggregate_vertex` + store-path resolution +
    ``engine.witness.resolve_cut_summary(store_path)`` (head position + tick
    total + anchor ordinal, ONE read transaction — sol P1) into the
    JSON-safe :class:`CutMeta` shape. NEVER raises — every failure mode
    (aggregate vertex, no/uncreated store, a malformed ``.vertex`` file, any
    ``WitnessResolutionError``, or any other unexpected exception) degrades
    to ``available=False`` with a stated reason instead of propagating: a
    provenance-resolution failure must never abort the read itself (S6
    arbitration F1/F4). The outer try/except is the belt to
    ``_resolve_cut_body``'s more specific suspenders — it exists because
    even the FIRST step (``is_aggregate_vertex``, which parses the vertex
    file) can raise on a malformed declaration, a case a plain read must
    survive too.

    CALLER CONTRACT (sol P1 — binds the claim to what's actually rendered):
    this function does real store I/O and so must be called AFTER the fold
    it accompanies has already been fetched, never before/concurrently with
    it. The store is append-only (rowid never shrinks, no updates/deletes),
    so resolving cut strictly after the fold fetch completes guarantees this
    function's head position is equal-to-or-LATER than whatever the fold
    actually witnessed — never earlier. That ordering is what makes
    ``sealed_to_head``/``facts_beyond_seal`` safe to report alongside a fold
    that may have been fetched a moment earlier: a concurrent append landing
    in between can only make this answer MORE conservative (report MORE
    unsealed tail than the render actually shows, or correctly refuse
    ``sealed_to_head`` when the render's true extent is in fact still
    sealed) — it can never flip a genuinely-unsealed render to a false
    ``sealed_to_head=True`` claim. See ``cli.dispatch.dispatch`` (the
    ``cut_resolver`` call site, invoked only after ``op.fn()`` returns) and
    ``cli.views.fold.run`` (which hands a resolver closure rather than a
    precomputed dict for exactly this reason).
    """
    try:
        return _resolve_cut_body(vertex_path)
    except Exception as exc:
        return unavailable_cut("unavailable", f"unexpected: {exc}")


def _resolve_cut_body(vertex_path: Path) -> dict:
    if is_aggregate_vertex(vertex_path):
        return unavailable_cut(
            "unavailable",
            "aggregate vertex — no single witness cut across members",
        )

    from loops.commands.resolve import _resolve_vertex_store_path

    try:
        store_path = _resolve_vertex_store_path(vertex_path)
    except Exception as exc:  # VertexNotFound / VertexParseError etc.
        return unavailable_cut("unavailable", f"vertex could not be resolved: {exc}")
    if store_path is None:
        return unavailable_cut(
            "unavailable",
            "this vertex has no store configured — nothing to seal",
        )
    if not store_path.exists():
        return unavailable_cut(
            "unavailable", "this vertex's store has not been created yet",
        )

    from engine.witness import WitnessResolutionError, resolve_cut_summary

    try:
        summary = resolve_cut_summary(store_path)
    except WitnessResolutionError as exc:
        return unavailable_cut("unavailable", str(exc))
    except Exception as exc:
        # A genuine unexpected failure (not one of the named engine
        # resolution errors) — still degrades rather than aborting the read,
        # but tagged distinctly ("unexpected:") so a test asserting a healthy
        # store never hits this branch catches a real regression here rather
        # than it silently blending into the honest-refusal cases forever
        # (risk mitigation noted in the S6 brief).
        return unavailable_cut("unavailable", f"unexpected: {exc}")

    return _cut_from_summary(summary)


def _cut_from_summary(summary: "CutSummary") -> dict:
    """The ``head``-mode :class:`CutMeta` dict derived from a resolved
    :class:`~engine.witness.CutSummary` — the shared tail of the default-read
    (:func:`resolve_cut`) and the S4 review-head (:func:`resolve_review_head`)
    paths, so both report seal provenance identically from one resolution."""
    position = summary.position
    anchor = position.anchor
    sealed_to_head = anchor is not None and anchor.fact_cursor == position.fact_id
    if anchor is None:
        # Nothing sealed yet — the whole store (by receipt count) is the
        # unsealed tail.
        facts_beyond_seal: int | None = position.seq
    elif summary.anchor_seq is not None:
        facts_beyond_seal = position.seq - summary.anchor_seq
    else:
        # resolve_cut_summary already degraded this ONE field on a failed
        # anchor-ordinal lookup — the position/sealed_to_head answer above
        # is still sound, so only facts_beyond_seal goes unknown.
        facts_beyond_seal = None

    return CutMeta(
        available=True,
        mode="head",
        anchor=_anchor_to_dict(anchor),
        sealed_to_head=sealed_to_head,
        tick_total=summary.tick_total,
        facts_beyond_seal=facts_beyond_seal,
    ).to_dict()


# --- Review head disclosure (0.9.0, S4) -------------------------------------
#
# The --review header discloses the read's HEAD cursor position alongside its
# seal cut. Both derive from ONE head resolution — S6's single-transaction
# ``resolve_cut_summary`` primitive (arbiter S4-F3: a second independent
# head-resolve path is a refusable finding). So the cursor and the cut can
# never describe two different head states.


def _head_cursor_meta(vertex_path: Path, position: "WitnessPosition") -> dict:
    """Build the head cursor disclosure from an already-resolved position.

    Same machine-readable shape as the ``--at`` cursor (``cli.views.fold.
    _resolve_cursor``) — ``mode``/``status``/``fact_id``/``seq``/``unadopted``/
    ``lineage``/``durable_handle``/``portable``/``anchor`` — plus ``address:
    "head"`` and a ``head: True`` marker so a consumer can phrase "at head"
    distinctly from an explicit rewind. Reuses ``load_declaration_status`` for
    the ontology-provenance label (a declaration read, NOT a second witness
    head-resolve) and ``durable_handle`` for portability (A10: only an adopted
    store yields a portable ``fact:<lineage>/<id>`` handle)."""
    from engine import durable_handle, load_declaration_status

    _ast, status = load_declaration_status(vertex_path, at=position)
    handle = durable_handle(position)
    return {
        "mode": "witness",
        "address": "head",
        "head": True,
        "status": status,
        "fact_id": position.fact_id,
        "seq": position.seq,
        "unadopted": position.unadopted,
        "lineage": position.lineage,
        "durable_handle": handle,
        "portable": handle is not None,
        "anchor": _anchor_to_dict(position.anchor),
    }


def resolve_review_head(vertex_path: Path) -> tuple[dict | None, dict]:
    """Head cursor + seal cut for a ``--review`` read, from ONE head resolution.

    Returns ``(cursor_meta | None, cut_dict)``. Reuses
    ``engine.witness.resolve_cut_summary`` — the SAME single-transaction engine
    primitive :func:`resolve_cut` wraps (arbiter S4-F3: no second independent
    head-resolve) — and derives BOTH the head-cursor disclosure and the seal cut
    from the one resolved :class:`~engine.witness.WitnessPosition`.

    Degrades honestly, never raises: an aggregate vertex, a store-less vertex, an
    uncreated store, or an engine resolution failure yields ``cursor=None`` and
    ``cut`` = ``available=False`` with a stated reason — the same refusal paths
    (and reason strings) as :func:`resolve_cut`, so the review header's cut is
    identical to what a plain read would disclose.

    CALLER CONTRACT (sol P1-a): the returned ``position`` is the binding handle.
    A caller pairing this disclosure with a fold must FOLD AT that position
    (``fetch_fold(at=position)``), not fold separately and hope the two agree.
    The previous contract here — "resolve strictly AFTER the fetch, so the head
    can only OVER-report" — was ordering-as-mitigation: it narrowed the window
    but still let the review advertise a cursor newer than the rows it rendered.
    Folding at the resolved position closes it by construction: the rows ARE the
    prefix the cursor names, whatever concurrent writers do.
    """
    if is_aggregate_vertex(vertex_path):
        return None, unavailable_cut(
            "unavailable",
            "aggregate vertex — no single witness cut across members",
        )

    from loops.commands.resolve import _resolve_vertex_store_path

    try:
        store_path = _resolve_vertex_store_path(vertex_path)
    except Exception as exc:  # VertexNotFound / VertexParseError etc.
        return None, unavailable_cut("unavailable", f"vertex could not be resolved: {exc}")
    if store_path is None:
        return None, unavailable_cut(
            "unavailable", "this vertex has no store configured — nothing to seal",
        )
    if not store_path.exists():
        return None, unavailable_cut(
            "unavailable", "this vertex's store has not been created yet",
        )

    from engine.witness import WitnessResolutionError, resolve_cut_summary

    try:
        summary = resolve_cut_summary(store_path)
    except WitnessResolutionError as exc:
        return None, unavailable_cut("unavailable", str(exc))
    except Exception as exc:
        return None, unavailable_cut("unavailable", f"unexpected: {exc}")

    cursor = _head_cursor_meta(vertex_path, summary.position)
    return cursor, _cut_from_summary(summary)


def resolve_review_head_position(
    vertex_path: Path,
) -> tuple["WitnessPosition | None", dict | None, dict]:
    """:func:`resolve_review_head` plus the POSITION the disclosure describes.

    Returns ``(position | None, cursor_meta | None, cut_dict)``. The position is
    what lets the caller fold at exactly what it disclosed (sol P1-a);
    ``None`` on every degrade path (aggregate, store-less, uncreated store,
    resolution failure), where there is no position to pin a fold to and the
    caller folds at head unpinned, as before.
    """
    if is_aggregate_vertex(vertex_path):
        return None, None, unavailable_cut(
            "unavailable",
            "aggregate vertex — no single witness cut across members",
        )

    from loops.commands.resolve import _resolve_vertex_store_path

    try:
        store_path = _resolve_vertex_store_path(vertex_path)
    except Exception as exc:
        return None, None, unavailable_cut(
            "unavailable", f"vertex could not be resolved: {exc}")
    if store_path is None:
        return None, None, unavailable_cut(
            "unavailable", "this vertex has no store configured — nothing to seal",
        )
    if not store_path.exists():
        return None, None, unavailable_cut(
            "unavailable", "this vertex's store has not been created yet",
        )

    from engine.witness import WitnessResolutionError, resolve_cut_summary

    try:
        summary = resolve_cut_summary(store_path)
    except WitnessResolutionError as exc:
        return None, None, unavailable_cut("unavailable", str(exc))
    except Exception as exc:
        return None, None, unavailable_cut("unavailable", f"unexpected: {exc}")

    cursor = _head_cursor_meta(vertex_path, summary.position)
    return summary.position, cursor, _cut_from_summary(summary)
