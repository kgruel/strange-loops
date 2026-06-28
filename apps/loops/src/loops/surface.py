"""surface — the typed, addressable projection between fetch and render.

The keystone of the structured-fact-surface redesign. One frozen ``Surface``
value sits between ``data = op.fn()`` and ``call_lens`` at the dispatch seam:
a FLAT ordered list of ``Row``s (each a fact made *addressable* by ``kind/key``,
with salience/inbound *materialized* onto it), a per-kind ``schema`` of render
hints, and a ``Window`` recording what got sliced or hidden.

Every measured agent need is a pure transform over this value — applied BEFORE
either encoder runs:

    project()  : FoldState -> Surface   (the constructor; materializes salience)
    search()   : Surface   -> Surface   (event-axis rows from a content match)
    filter()   : Surface   -> Surface   (kind / key-prefix / where / observer)
    select()   : Surface   -> Surface   (narrow payloads to a field projection)
    budget()   : Surface   -> Surface   (limit / last-N slice, recorded in Window)
    count()    : Surface   -> Surface   (aggregate into count-rows)
    whole()    : Surface   -> Surface   (force full-payload granularity)

Two encoders are the last step: a render lens (``Surface -> Block``) and
``to_dict`` (``Surface -> dict`` for ``--json``). Same Surface in, so plain and
json carry the SAME rows in the SAME (faithful fold) order — ranking is an
opt-in transform (``budget(limit)``), not the base order (see ``project``).

This module is PAINTED-FREE and imports nothing from ``loops.lenses`` — it is a
leaf so the lens can depend on it, not the reverse. The salience/inbound math is
COPIED byte-for-byte from ``lenses/fold.py`` (not imported) so the lens can later
delete its copies and read the materialized scalars.

NOT a store (holds no facts, persists nothing), NOT a query language (a fixed set
of typed transforms over the existing ``kind/key`` + ULID address grammar), NOT a
new fetch path (it composes the existing fetch_fold / vertex_search outputs).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atoms import FoldItem, FoldState


# ---------------------------------------------------------------------------
# Data model — four frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KindView:
    """Per-kind render hints, lifted off FoldSection so the lens needs no
    FoldState to render a Row. Carried in ``Surface.schema`` keyed by kind."""

    key_field: str | None = None
    fold_type: str = "collect"  # "by" | "collect"
    preview_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class Row:
    """The addressable unit — a thin typed view of one fact, NOT a new fact.

    A Row IS a FoldItem plus two materialized scalars (inbound, salience), its
    address, and its granularity. Event rows (from search) reuse the same shape
    with ``axis="event"``.
    """

    address: str  # "kind/key" (entity) or "kind/<id>" (event/collect)
    kind: str
    payload: dict[str, Any]
    key: str | None = None  # fold-key value; None for collect/event rows
    key_field: str | None = None  # the fold-key FIELD name (label hint; carries
    # walked-row kinds whose schema entry is absent under a --kind filter)
    axis: str = "entity"  # "entity" (folded) | "event" (raw fact)
    id: str | None = None  # ULID
    ts: float | None = None
    observer: str = ""
    origin: str = ""
    n: int = 1  # compression count (1 for event rows)
    refs: tuple[str, ...] = ()  # OUTBOUND, verbatim
    inbound: int = 0  # MATERIALIZED (lifted from the lens) — was render-only
    salience: int = 0  # MATERIALIZED = n + inbound (lifted from _salience)
    depth: int = 0  # >0 for ref-walk rows
    via_anchor: str | None = None  # the anchor whose ref pulled a walked row in
    granularity: str = "headline"  # "whole" | "headline"


@dataclass(frozen=True)
class Window:
    """Provenance of what was sliced or hidden — the ``--json`` contract fix.

    Makes budgeting/windowing VISIBLE and serializable, so both encoders agree
    on what the human is (or isn't) seeing.
    """

    total: int = 0  # rows before budget
    shown: int = 0  # rows after
    limited_by: str | None = None  # "limit" | "last" | "salience" | None
    query: str | None = None  # the search string if search() ran
    fields: tuple[str, ...] | None = None  # the projection if select() ran
    granularity: str = "headline"  # derived summary: "whole" | "headline" | "mixed"
    unindexed: tuple[str, ...] = ()  # kinds with facts but no FTS coverage (S5)


@dataclass(frozen=True)
class Surface:
    """The keystone value — a flat ordered list of Rows + render schema +
    coverage signal + source facts + a Window provenance record."""

    rows: tuple[Row, ...]
    vertex: str
    schema: dict[str, KindView] = field(default_factory=dict)
    unfolded: dict[str, int] = field(default_factory=dict)
    source_facts: dict[str, list[dict]] = field(default_factory=dict)
    inbound_edges: dict[str, list[str]] = field(default_factory=dict)
    """target "kind/key" → [source "kind/key", ...] for --refs edge expansion.
    Materialized ONCE in project() from the fold-order sections (via the lifted
    _compute_inbound_edges), so the render reads it instead of rebuilding from
    salience-ordered rows — which would reorder the per-target source lists."""
    window: Window = field(default_factory=Window)


# ---------------------------------------------------------------------------
# Salience / inbound — LIFTED byte-for-byte from lenses/fold.py:756-819.
# Copied (not imported) to keep this module a painted-free leaf and let the
# lens delete its copies in S2. The dual-form bare-vs-kind-qualified match in
# _inbound_count is load-bearing: dropping the bare-key branch silently halves
# salience for namespaced keys.
# ---------------------------------------------------------------------------


def _compute_inbound_refs(data: FoldState) -> Counter:
    """Count inbound references across all sections."""
    inbound: Counter = Counter()
    for section in data.sections:
        for item in section.items:
            for ref in item.refs:
                inbound[ref] += 1
    return inbound


def _compute_inbound_edges(data: FoldState) -> dict[str, list[str]]:
    """Build adjacency map: target → [source, ...] for edge expansion."""
    edges: dict[str, list[str]] = {}
    for section in data.sections:
        kf = section.key_field
        for item in section.items:
            if not item.refs:
                continue
            source = _item_full_key(item, kf, section.kind)
            if not source:
                continue
            for ref in item.refs:
                edges.setdefault(ref, []).append(source)
    return edges


def _item_full_key(item: FoldItem, key_field: str | None, kind: str = "") -> str:
    """Build the full kind/key reference for an item (e.g. 'decision/atoms/n-on-fold-item')."""
    if not key_field:
        return ""
    key = item.payload.get(key_field, "")
    if not key:
        return ""
    return f"{kind}/{key}" if kind else str(key)


def _salience(item: FoldItem, key_field: str | None, inbound: Counter) -> int:
    """Salience = n + inbound ref count."""
    return item.n + _inbound_count(item, key_field, inbound)


def _inbound_count(item: FoldItem, key_field: str | None, inbound: Counter) -> int:
    """Look up inbound ref count for this item.

    Matches refs in three forms:
    * Kind-qualified colon — ``<fact-kind>:<key>`` (CANONICAL — e.g.
      ``decision:design/foo``, ``thread:arc-name``)
    * Kind-qualified slash — ``<fact-kind>/<key>`` (legacy — e.g. ``decision/design/foo``)
    * Bare — the key_field value itself (e.g. ``design/foo``)

    The colon form is the documented ref convention; matching only the slash
    and bare forms silently dropped EVERY ``kind:key`` inbound ref from
    salience — the dominant form in practice (the read-side twin of the
    emit-time colon-blindness fixed in resolve.py). The bare form matters when
    the key contains a namespace slash: ``endswith("/foo")`` alone misses it.
    """
    if not key_field:
        return 0
    key = item.payload.get(key_field, "")
    if not key:
        return 0
    count = 0
    suffix_slash = f"/{key}"
    suffix_colon = f":{key}"
    for ref_key, ref_count in inbound.items():
        if (
            ref_key == key
            or ref_key.endswith(suffix_slash)
            or ref_key.endswith(suffix_colon)
        ):
            count += ref_count
    return count


# ---------------------------------------------------------------------------
# Predicate engine — eq + comma-OR(in) ONLY (all net-new; no engine exists today)
# ---------------------------------------------------------------------------


def _predicate_match(payload: dict, predicates: dict[str, tuple[str, ...]]) -> bool:
    """True iff the payload satisfies every predicate (case-insensitive).

    Each predicate is ``field -> (allowed, values...)``. A field matches when
    the payload's value (str-coerced, lowercased) is IN the allowed set —
    comma-OR within a field, AND across fields. Missing field → no match.
    """
    for fld, allowed in predicates.items():
        val = str(payload.get(fld, "")).lower()
        allowed_lower = tuple(a.lower() for a in allowed)
        if val not in allowed_lower:
            return False
    return True


def _row_matches_key(row: Row, key: str) -> bool:
    """Prefix match for a Row's key, mirroring fetch._item_matches_key.

    Tries the row's fold key first, then common label fields in the payload
    (topic, name, title, summary), case-insensitive ``startswith``.
    """
    key_lower = key.lower()
    if row.key is not None and str(row.key).lower().startswith(key_lower):
        return True
    for fld in ("topic", "name", "title", "summary"):
        if fld in row.payload:
            if str(row.payload[fld]).lower().startswith(key_lower):
                return True
    return False


def _payload_text(payload: dict) -> str:
    """Concatenate a payload's non-empty string values for substring search."""
    return " ".join(str(v) for v in payload.values() if v)


def _granularity(
    key_field: str | None, key: str | None, queried_key: str | None, full: bool
) -> str:
    """Resolve a Row's granularity by ADDRESS SPECIFICITY, not a flag.

    "whole" iff ``--full`` OR the row is a COMPLETE-key address — the queried
    key equals this row's fold-key value exactly (case-insensitive), not merely
    a prefix that happens to match it. Decisive: adding a 2nd fact under the
    same prefix never flips an existing complete-key read's granularity.
    """
    if full:
        return "whole"
    if key_field and queried_key is not None and key is not None:
        if str(key).lower() == queried_key.lower():
            return "whole"
    return "headline"


def _window_granularity(rows: tuple[Row, ...]) -> str:
    """Derive the surface-level granularity summary from its rows."""
    grans = {r.granularity for r in rows}
    if grans == {"whole"}:
        return "whole"
    if not grans or grans == {"headline"}:
        return "headline"
    return "mixed"


def _row_group(row: Row, by: str) -> str:
    """The group value for count(by=): a Row attribute first, else a payload field."""
    if hasattr(row, by):
        return str(getattr(row, by))
    return str(row.payload.get(by, ""))


# ---------------------------------------------------------------------------
# project — the constructor (FoldState -> Surface)
# ---------------------------------------------------------------------------


def _row_key(item: FoldItem, key_field: str | None) -> str | None:
    """The fold-key value for an item, or None for collect/keyless items.

    Uses TRUTHINESS (``if not val``) to gate emptiness, byte-matching the lens's
    old ``_item_full_key`` / ``_inbound_count`` (``if not key``): a falsy fold
    value (None, "", 0, False) is treated as no-key, so Row.key is None and the
    address falls back to ``kind/<id>``. Gating only on ``None``/``""`` would
    make a key of int ``0`` resolve to ``kind/0`` and spuriously hit the
    edge/facts lookups the old lens skipped.
    """
    if not key_field:
        return None
    val = item.payload.get(key_field)
    if not val:
        return None
    return str(val)


def _address(kind: str, key: str | None, item_id: str | None) -> str:
    """The existing address grammar: kind/key (entity) or kind/<id> (collect/event)."""
    if key:
        return f"{kind}/{key}"
    if item_id:
        return f"{kind}/{item_id}"
    return f"{kind}/"


def project(
    state: FoldState,
    *,
    queried_key: str | None = None,
    full: bool = False,
    fields: tuple[str, ...] | None = None,
) -> Surface:
    """Walk a FoldState into a Surface, materializing inbound/salience ONCE.

    Row order is the FAITHFUL FOLD ORDER — items in their section order, sections
    in vertex declaration order, walked (ref-graph) rows last with depth>0. This
    is deliberate: today's fold lens derives the namespace-group tiebreak (equal
    group-salience-sum → first-appearance order) AND the --refs edge-source
    ordering from fold order, so a salience pre-sort here would make the lens
    render diverge byte-for-byte. Ranking is a TRANSFORM (budget(limit=N) takes
    the salience head); the base surface stays a faithful projection, and the
    lens applies its own sort/group/window reading the materialized scalars.

    inbound_edges is materialized here (from the fold-order sections) so --refs
    reads it instead of rebuilding from reordered rows. Windowing is NOT applied
    — project() yields every row; the lens/budget transform decides what to hide.
    """
    inbound = _compute_inbound_refs(state)
    schema: dict[str, KindView] = {}
    rows: list[Row] = []

    for section in state.sections:
        kf = section.key_field
        schema[section.kind] = KindView(
            key_field=kf,
            fold_type=section.fold_type,
            preview_fields=section.preview_fields,
        )
        for item in section.items:
            key = _row_key(item, kf)
            inbound_count = _inbound_count(item, kf, inbound)
            payload = dict(item.payload)
            if fields:
                payload = {k: payload[k] for k in fields if k in payload}
            rows.append(
                Row(
                    address=_address(section.kind, key, item.id),
                    kind=section.kind,
                    key=key,
                    key_field=kf,
                    payload=payload,
                    axis="entity",
                    id=item.id,
                    ts=item.ts,
                    observer=item.observer,
                    origin=item.origin,
                    n=item.n,
                    refs=tuple(item.refs),
                    inbound=inbound_count,
                    salience=item.n + inbound_count,
                    depth=0,
                    via_anchor=None,
                    granularity=_granularity(kf, key, queried_key, full),
                )
            )

    # Walked items (ref-graph reach) follow the primaries, preserving lineage.
    for w in state.walked:
        item = w.item
        kf = w.key_field
        key = _row_key(item, kf)
        inbound_count = _inbound_count(item, kf, inbound)
        payload = dict(item.payload)
        if fields:
            payload = {k: payload[k] for k in fields if k in payload}
        rows.append(
            Row(
                address=_address(w.section_kind, key, item.id),
                kind=w.section_kind,
                key=key,
                key_field=kf,
                payload=payload,
                axis="entity",
                id=item.id,
                ts=item.ts,
                observer=item.observer,
                origin=item.origin,
                n=item.n,
                refs=tuple(item.refs),
                inbound=inbound_count,
                salience=item.n + inbound_count,
                depth=w.depth,
                via_anchor=w.via_anchor,
                granularity=_granularity(kf, key, queried_key, full),
            )
        )

    row_tuple = tuple(rows)
    window = Window(
        total=len(row_tuple),
        shown=len(row_tuple),
        limited_by=None,
        query=None,
        fields=tuple(fields) if fields else None,
        granularity=_window_granularity(row_tuple),
    )
    return Surface(
        rows=row_tuple,
        vertex=state.vertex,
        schema=schema,
        unfolded=dict(state.unfolded),
        source_facts=dict(state.source_facts),
        inbound_edges=_compute_inbound_edges(state),
        window=window,
    )


# ---------------------------------------------------------------------------
# Transforms — Surface -> Surface, applied before either encoder
# ---------------------------------------------------------------------------


def _event_row(fact: dict) -> Row:
    """Build an event-axis Row from a ``vertex_search`` / ``vertex_facts`` dict.

    These are RAW facts (one per write, the event axis) — ``{kind, ts, observer,
    origin, id, payload}`` — with ``ts`` a ``datetime`` and no top-level
    ``refs``. The address is ``kind/<id>`` (no fold key on the event axis).
    """
    from datetime import datetime

    ts = fact.get("ts")
    if isinstance(ts, datetime):
        ts = ts.timestamp()
    fid = fact.get("id")
    kind = fact.get("kind", "")
    return Row(
        address=_address(kind, None, fid),
        kind=kind,
        payload=dict(fact.get("payload", {})),
        key=None,
        axis="event",
        id=fid,
        ts=ts,
        observer=fact.get("observer", ""),
        origin=fact.get("origin", ""),
        n=1,
        refs=(),
        inbound=0,
        salience=1,
        granularity="headline",
    )


def _indexed_kinds(vertex_path) -> set[str]:
    """The kinds FTS-indexed in a vertex (those declaring ``search`` fields).

    Returns an empty set on any parse failure or when ``vertex_path`` is None —
    callers then treat every present kind as un-indexed (substring fallback).
    """
    if vertex_path is None:
        return set()
    try:
        from lang import parse_vertex_file

        ast = parse_vertex_file(vertex_path)
    except Exception:
        return set()
    return {kind for kind, ld in ast.loops.items() if getattr(ld, "search", ())}


def search(surface: Surface, query: str, *, vertex_path=None) -> Surface:
    """CONTENT-SEARCH → event-axis rows: FTS5 for indexed kinds, substring for
    the rest, with a coverage signal for the gap.

    Two disjoint sources, combined and ordered ts-desc:

    * FTS path — ``engine.vertex_search`` over the kinds that declare ``search``
      fields. These return RAW facts (the event axis: every matching write, not
      the folded item), converted to event Rows.
    * Substring path — for kinds with NO ``search`` declaration (which FTS can't
      see), a case-insensitive substring scan over the already-projected rows,
      re-tagged ``axis="event"``. Folded-granularity, but it covers undeclared
      kinds at all.

    ``Window.unindexed`` records every present kind that lacked FTS coverage (the
    superset-of-``unfolded`` coverage-K), so the lens can footer ``(K not
    indexed)`` — the honesty signal that those kinds were substring-scanned, not
    FTS-searched. The two sets are disjoint by construction (a kind is indexed
    XOR not), so no fact is double-counted.
    """
    indexed = _indexed_kinds(vertex_path)
    present = {r.kind for r in surface.rows}
    # FTS covers present-AND-indexed; substring covers present-AND-not-indexed.
    # Scoping to ``present`` respects the fetch-time --kind narrowing (which only
    # shrank the surface, not vertex_search's view) — else FTS would leak hits
    # from other indexed kinds the user filtered out.
    fts_kinds = present & indexed
    unindexed = tuple(sorted(present - indexed))

    rows: list[Row] = []

    # FTS path — only meaningful when the vertex is known and a present kind is
    # indexed.
    if vertex_path is not None and fts_kinds:
        try:
            from engine import vertex_search

            facts = vertex_search(vertex_path, query)
        except Exception:
            facts = []
        rows.extend(_event_row(f) for f in facts if f.get("kind") in fts_kinds)

    # Substring path — over the projected rows of UN-indexed kinds only (disjoint
    # from the FTS set).
    q = query.lower()
    rows.extend(
        replace(r, axis="event")
        for r in surface.rows
        if r.kind in unindexed and q in _payload_text(r.payload).lower()
    )

    rows.sort(key=lambda r: (r.ts if r.ts is not None else 0.0), reverse=True)
    row_tuple = tuple(rows)
    window = replace(
        surface.window,
        query=query,
        total=len(row_tuple),
        shown=len(row_tuple),
        unindexed=unindexed,
    )
    return replace(surface, rows=row_tuple, window=window)


def filter(  # noqa: A001 — domain verb; the shadow of builtins.filter is intentional
    surface: Surface,
    *,
    kind: str | None = None,
    key: str | None = None,
    key_or: tuple[str, ...] | None = None,
    where: dict[str, tuple[str, ...]] | None = None,
    observer: str | None = None,
) -> Surface:
    """FILTER rows by kind / key-prefix / where-predicate / observer (all AND).

    ``key`` is a single prefix; ``key_or`` is comma-OR — a row survives if ANY
    of its prefixes match (the ``--key a,b`` grammar). They compose by AND when
    both are given, but the view supplies exactly one (a lone ``--key`` value is
    routed to ``project(queried_key=)`` for granularity; a comma list arrives
    here as ``key_or`` for pure filtering).
    """
    rows = list(surface.rows)
    if kind is not None:
        rows = [r for r in rows if r.kind == kind]
    if key is not None:
        rows = [r for r in rows if _row_matches_key(r, key)]
    if key_or:
        rows = [r for r in rows if any(_row_matches_key(r, k) for k in key_or)]
    if where:
        rows = [r for r in rows if _predicate_match(r.payload, where)]
    if observer is not None:
        rows = [r for r in rows if r.observer == observer]
    row_tuple = tuple(rows)
    window = replace(
        surface.window,
        shown=len(row_tuple),
        granularity=_window_granularity(row_tuple),
    )
    return replace(surface, rows=row_tuple, window=window)


def select(surface: Surface, fields: tuple[str, ...]) -> Surface:
    """PROJECTION — narrow each Row's payload to ``fields``. Records Window.fields."""
    rows = tuple(
        replace(r, payload={k: r.payload[k] for k in fields if k in r.payload})
        for r in surface.rows
    )
    window = replace(surface.window, fields=tuple(fields))
    return replace(surface, rows=rows, window=window)


def budget(
    surface: Surface,
    *,
    limit: int | None = None,
    last: int | None = None,
    salience_window: bool = False,
) -> Surface:
    """BUDGET — slice the row set and record the cut into the Window.

    - ``last=N``  → newest N by ts (the confirm primitive; ts-desc then take N).
    - ``limit=N`` → top N by salience (the agent's "just the head" primitive).
    - ``salience_window`` → keep only salience>1 (fallback: top-1) — the
      namespace-windowing policy, available explicitly to an agent.

    last and limit are mutually ordered: ``last`` wins (it reorders by recency);
    otherwise ``limit`` takes the salience head.
    """
    rows = list(surface.rows)
    limited_by = surface.window.limited_by

    if salience_window and len(rows) > 0:
        kept = [r for r in rows if r.salience > 1]
        rows = kept if kept else rows[:1]
        limited_by = "salience"

    if last is not None:
        rows = sorted(rows, key=lambda r: (r.ts if r.ts is not None else 0.0), reverse=True)
        rows = rows[:last]
        limited_by = "last"
    elif limit is not None:
        rows = sorted(rows, key=lambda r: r.salience, reverse=True)
        rows = rows[:limit]
        limited_by = "limit"

    row_tuple = tuple(rows)
    window = replace(
        surface.window,
        shown=len(row_tuple),
        limited_by=limited_by,
        granularity=_window_granularity(row_tuple),
    )
    return replace(surface, rows=row_tuple, window=window)


def count(surface: Surface, *, by: str | None = None) -> Surface:
    """AGGREGATE — collapse rows into count-rows.

    ``by=None`` → one total row. ``by="kind"`` (or any Row attr / payload field)
    → one row per group, count-desc. Count-rows are ``axis="event"`` synthetic
    rows carrying ``{by: value, "count": n}`` (or ``{"count": n}`` for the total).
    """
    if by is None:
        total = len(surface.rows)
        rows: tuple[Row, ...] = (
            Row(
                address="count/total",
                kind="count",
                key="total",
                payload={"count": total},
                axis="event",
                salience=total,
            ),
        )
    else:
        counter: Counter = Counter(_row_group(r, by) for r in surface.rows)
        rows = tuple(
            Row(
                address=f"count/{value}",
                kind="count",
                key=str(value),
                payload={by: value, "count": n},
                axis="event",
                salience=n,
            )
            for value, n in counter.most_common()
        )
    window = replace(
        surface.window, total=len(rows), shown=len(rows), limited_by=None
    )
    return replace(surface, rows=rows, window=window)


def whole(surface: Surface, address: str | None = None) -> Surface:
    """FACT-WHOLE — force "whole" granularity (full body) on rows.

    ``address=None`` forces every surviving row whole (the ``--full`` transform
    form); an explicit address forces just that one. Honors a prior filter/budget
    — it flips granularity, it does not re-add hidden rows.
    """
    def flip(r: Row) -> Row:
        if address is None or r.address == address:
            return replace(r, granularity="whole")
        return r

    rows = tuple(flip(r) for r in surface.rows)
    window = replace(surface.window, granularity=_window_granularity(rows))
    return replace(surface, rows=rows, window=window)


# ---------------------------------------------------------------------------
# to_dict — the structured encoder (--json). Explicit, not reflection.
# ---------------------------------------------------------------------------


def _row_to_dict(row: Row) -> dict:
    return {
        "address": row.address,
        "kind": row.kind,
        "key": row.key,
        "key_field": row.key_field,
        "payload": dict(row.payload),
        "axis": row.axis,
        "id": row.id,
        "ts": row.ts,
        "observer": row.observer,
        "origin": row.origin,
        "n": row.n,
        "refs": list(row.refs),
        "inbound": row.inbound,
        "salience": row.salience,
        "depth": row.depth,
        "via_anchor": row.via_anchor,
        "granularity": row.granularity,
    }


def _window_to_dict(window: Window) -> dict:
    return {
        "total": window.total,
        "shown": window.shown,
        "limited_by": window.limited_by,
        "query": window.query,
        "fields": list(window.fields) if window.fields is not None else None,
        "granularity": window.granularity,
        "unindexed": list(window.unindexed),
    }


def to_dict(surface: Surface) -> dict:
    """The Surface's native JSON encoding — same ranked rows the lens renders.

    Explicit field-by-field (FoldItem/Row are frozen and we want a stable,
    documented wire shape, not whatever ``dataclasses.asdict`` reflects).
    """
    return {
        "vertex": surface.vertex,
        "rows": [_row_to_dict(r) for r in surface.rows],
        "schema": {
            kind: {
                "key_field": kv.key_field,
                "fold_type": kv.fold_type,
                "preview_fields": list(kv.preview_fields),
            }
            for kind, kv in surface.schema.items()
        },
        "unfolded": dict(surface.unfolded),
        "source_facts": {
            addr: [dict(f) for f in facts]
            for addr, facts in surface.source_facts.items()
        },
        "window": _window_to_dict(surface.window),
    }
