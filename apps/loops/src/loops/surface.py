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
leaf so the lens can depend on it, not the reverse. The salience/inbound math
lives HERE as the single source of truth: the built-in fold lens (build-1) and
the three orient lenses (session_start / session_landing / identity_prompt, the
salience-lens-migration fast-follow) read the materialized ``Row.salience`` /
``Row.inbound`` and no longer carry their own copies.

NOT a store (holds no facts, persists nothing), NOT a query language (a fixed set
of typed transforms over the existing ``kind/key`` + ULID address grammar), NOT a
new fetch path (it composes the existing fetch_fold / vertex_search outputs).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atoms import Edge, FoldItem, FoldState


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
    level: str = "key"  # containment-tree node type: "key" (folded entity) |
    # "fact" (raw event) | "tick" (tick-window tree-cut). ``axis`` carries the
    # entity/event TIME semantics the transforms key on; ``level`` is the node
    # type in the containment tree (a tick row is axis="event", level="tick").
    # Possible future dissolution: axis folds into level once no transform needs
    # the time-axis distinction independently — not now (residue note, §7A).
    id: str | None = None  # ULID
    ts: float | None = None
    observer: str = ""
    origin: str = ""
    n: int = 1  # compression count (1 for event rows)
    refs: tuple[str, ...] = ()  # OUTBOUND ref edges, verbatim (union predicate)
    edges: tuple["Edge", ...] = ()  # OUTBOUND typed edges (predicate + address)
    inbound: int = 0  # MATERIALIZED (lifted from the lens) — was render-only
    inbound_predicates: tuple[tuple[str, int], ...] = ()  # ←N broken out by
    # predicate, e.g. (("stakeholder", 3), ("ref", 2)); sums to ``inbound``
    salience: int = 0  # MATERIALIZED = n + inbound (lifted from _salience)
    depth: int = 0  # >0 for ref-walk rows
    via_anchor: str | None = None  # the anchor whose ref pulled a walked row in
    granularity: str = "headline"  # "whole" | "headline"
    tier: str = "mid"  # rail tier: "high" | "mid" | "tail" — quantile bucket of
    # salience within the projected population (decision:design/
    # salience-tier-scope-vertex; "stale" overlay arrives with the lifecycle
    # declaration). Assigned once in project(); transforms preserve it, so the
    # glyph a row got is the glyph every view shows.


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
    inbound_edges: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    """target "kind/key" → [(source "kind/key", predicate), ...] for --refs edge
    expansion. Materialized ONCE in project() from the fold-order sections (via
    the lifted _compute_inbound_edges), so the render reads it instead of
    rebuilding from salience-ordered rows. ``predicate`` is the edge field name
    ("ref" for the grandfathered union edge, else the declared edge field)."""
    window: Window = field(default_factory=Window)


# ---------------------------------------------------------------------------
# Salience / inbound — the single source of truth (originally lifted from
# lenses/fold.py). Kept painted-free so every consumer can depend on it: the
# built-in fold lens and the orient lenses (session_start / session_landing /
# identity_prompt) all read the materialized Row scalars and carry no copies.
# The three-form match in _inbound_count (bare ``key`` / ``/key`` / ``:key``) is
# load-bearing: dropping the bare-key branch silently halves salience for
# namespaced keys, and dropping the colon branch drops the dominant ref form.
# ---------------------------------------------------------------------------


def _edge_corpus(data: FoldState) -> list[tuple[str, str, str]]:
    """Flatten every OUTBOUND edge in the fold into ``(address, predicate, source)``.

    Two edge kinds share one corpus so counts, predicate breakdowns, and the
    ``--refs`` adjacency all derive from the SAME matching semantic:

    * ``ref`` — the grandfathered union edge (predicate ``"ref"``), one per
      accumulated ``item.refs`` value.
    * typed edges — declared ``edge <field> targets=<kind>`` projections
      (predicate = field name), one per ``item.edges`` entry.

    ``source`` is the emitting item's ``kind/key`` address (fold-order), so the
    adjacency map preserves per-target source ordering.
    """
    corpus: list[tuple[str, str, str]] = []
    for section in data.sections:
        kf = section.key_field
        for item in section.items:
            if not item.refs and not item.edges:
                continue
            source = _item_full_key(item, kf, section.kind)
            if not source:
                # collect/keyless rows still contribute inbound to their targets
                source = ""
            for ref in item.refs:
                corpus.append((ref, "ref", source))
            for edge in item.edges:
                corpus.append((edge.address, edge.predicate, source))
    return corpus


# ---------------------------------------------------------------------------
# Promotion candidates — the schema-side of the log→friction promotion pattern.
# Surfaces UNDECLARED payload fields that already carry resolvable addresses,
# so a reconcile pass can decide whether they earn an `edge` declaration.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromotionCandidate:
    """An undeclared field carrying resolvable addresses — an edge candidate."""

    field: str
    count: int                      # facts carrying a resolvable address here
    target_kinds: tuple[str, ...]   # declared kinds its addresses point at
    source_kinds: tuple[str, ...]   # kinds whose facts carry the field


def _candidate_addr_kind(value: object) -> str | None:
    """The addr-kind of an address-looking value, else None.

    Mirrors resolve._is_addr_candidate + _split_addr (kept local so surface
    stays a leaf): must be separator-bearing, whitespace-free; returns the
    ``kind`` half of ``kind:key`` / ``kind/key``.
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v or any(c.isspace() for c in v):
        return None
    if ":" in v:
        return v.split(":", 1)[0] or None
    if "/" in v:
        return v.split("/", 1)[0] or None
    return None


def promotion_candidates(
    state: FoldState, *, min_facts: int = 3
) -> list[PromotionCandidate]:
    """Undeclared address-bearing fields worth considering for an edge decl.

    A field is a candidate when — across at least ``min_facts`` folded items —
    it carries a value whose ``kind:key`` address resolves against a kind
    DECLARED in this fold, and the field is NOT already ``ref``, a declared
    edge, or the kind's own fold key (self-identity). This mechanizes the
    log→friction promotion pattern for schema: capture stays declaration-free,
    reconcile surfaces what has earned a declaration. Returns count-desc.
    """
    declared_kinds = {s.kind for s in state.sections}
    counts: Counter = Counter()
    targets: dict[str, set] = {}
    sources: dict[str, set] = {}

    for section in state.sections:
        edge_fields = {f for f, _ in section.edge_fields}
        skip = {"ref"} | edge_fields
        if section.key_field:
            skip.add(section.key_field)
        for item in section.items:
            for fld, value in item.payload.items():
                if fld in skip or fld.endswith("_ref") or fld.startswith("_"):
                    continue
                addr_kind = _candidate_addr_kind(value)
                if addr_kind is None or addr_kind not in declared_kinds:
                    continue
                counts[fld] += 1
                targets.setdefault(fld, set()).add(addr_kind)
                sources.setdefault(fld, set()).add(section.kind)

    out = [
        PromotionCandidate(
            field=fld,
            count=count,
            target_kinds=tuple(sorted(targets[fld])),
            source_kinds=tuple(sorted(sources[fld])),
        )
        for fld, count in counts.items()
        if count >= min_facts
    ]
    out.sort(key=lambda c: (-c.count, c.field))
    return out


def _compute_inbound_refs(data: FoldState) -> Counter:
    """Count inbound references (ref + typed edges) across all sections."""
    inbound: Counter = Counter()
    for addr, _pred, _src in _edge_corpus(data):
        inbound[addr] += 1
    return inbound


def _address_matches_key(addr: str, key: str) -> bool:
    """Three-form match (bare / ``/key`` / ``:key``) — the ref/edge semantic."""
    return addr == key or addr.endswith(f"/{key}") or addr.endswith(f":{key}")


def _compute_inbound_edges(data: FoldState) -> dict[str, list[tuple[str, str]]]:
    """Build adjacency map: target ``kind/key`` → [(source, predicate), ...].

    Uses the three-form match (``_address_matches_key``) so an edge in any ref
    form — bare key, ``kind/key``, or the canonical ``kind:key`` — resolves to
    the target row's address, and the ``←`` expansion agrees with the ``←N``
    salience count (both read the same corpus + matcher). Typed edges carry
    their declared field as the predicate; ref edges carry ``"ref"``.
    """
    corpus = _edge_corpus(data)
    edges: dict[str, list[tuple[str, str]]] = {}
    for section in data.sections:
        kf = section.key_field
        for item in section.items:
            key = _row_key(item, kf)
            if not key:
                continue
            target = _address(section.kind, key, item.id)
            for addr, pred, source in corpus:
                if source and _address_matches_key(addr, key):
                    edges.setdefault(target, []).append((source, pred))
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


def _inbound_predicates(
    item: FoldItem,
    key_field: str | None,
    corpus: list[tuple[str, str, str]],
) -> tuple[tuple[str, int], ...]:
    """Break an item's inbound count out by predicate, count-desc then name.

    Scans the SAME corpus + three-form matcher as ``_inbound_count`` (which
    keys off ``_compute_inbound_refs``), so the breakdown SUMS to the ``←N``
    total — the render can show ``←5 (3 via stakeholder, 2 via ref)`` and the
    parts always reconcile. Keyless (collect) sources contribute here exactly
    as they contribute to the count, even though they cannot be named in the
    ``← source`` adjacency expansion.
    """
    key = _row_key(item, key_field)
    if not key:
        return ()
    counts: Counter = Counter()
    for addr, pred, _src in corpus:
        if _address_matches_key(addr, key):
            counts[pred] += 1
    return tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


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


def _tier_thresholds(saliences: list[int]) -> tuple[int, int] | None:
    """Quantile thresholds (q90, q50) for rail-tier assignment.

    The default dial (decision:design/spine-options-ratified §5a): ``high``
    = top decile of salience within the population, ``mid`` = above median,
    ``tail`` = the rest. Quantiles stay informative across a 9-key and a
    516-key vertex alike, which is the point of vertex scope.

    Returns None when the distribution has no spread — a flat population
    has no "hot" rows, so callers tier everything ``mid`` rather than
    rendering all-◆ noise.
    """
    if not saliences:
        return None
    lo, hi = min(saliences), max(saliences)
    if lo == hi:
        return None
    s = sorted(saliences)
    n = len(s)
    q90 = s[int(0.9 * (n - 1) + 0.5)]
    q50 = s[int(0.5 * (n - 1) + 0.5)]
    return q90, q50


def _tier_for(salience: int, thresholds: tuple[int, int] | None) -> str:
    if thresholds is None:
        return "mid"
    q90, q50 = thresholds
    if salience >= q90:
        return "high"
    if salience >= q50:
        return "mid"
    return "tail"


def _assign_tiers(rows: list[Row]) -> list[Row]:
    """Materialize Row.tier from salience quantiles over the population.

    Scope caveat (named residue, not silent): tiers are vertex-scoped only
    when the fetch was unfiltered — the default read. A fetch-level
    ``--kind``/``--key`` cut yields a state whose population IS the cut, so
    tiers degrade to cut-scope there until thresholds are hoisted to a
    full-vertex query (thread:static-honest-060-spine).
    """
    thresholds = _tier_thresholds([r.salience for r in rows])
    return [replace(r, tier=_tier_for(r.salience, thresholds)) for r in rows]


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
    corpus = _edge_corpus(state)
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
                    edges=tuple(item.edges),
                    inbound=inbound_count,
                    inbound_predicates=_inbound_predicates(item, kf, corpus),
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
                edges=tuple(item.edges),
                inbound=inbound_count,
                inbound_predicates=_inbound_predicates(item, kf, corpus),
                salience=item.n + inbound_count,
                depth=w.depth,
                via_anchor=w.via_anchor,
                granularity=_granularity(kf, key, queried_key, full),
            )
        )

    row_tuple = tuple(_assign_tiers(rows))
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


def tier_map(surface: Surface) -> dict[tuple[str, str], str]:
    """Map ``(kind, key)`` → tier from a projected surface's ENTITY rows.

    The single inheritance handle (decision:design/tier-one-home-inheritance):
    tier is assigned exactly once, in ``project()`` via ``_assign_tiers`` over
    the entity projection. Every other axis — stream events, tick windows —
    INHERITS through this map, never re-computing. Keyless (collect) rows carry
    no ``(kind, key)`` handle, so they are absent here and their events render
    UNTIERED (honest absence, not an invented "mid").
    """
    return {
        (r.kind, r.key): r.tier
        for r in surface.rows
        if r.level == "key" and r.key is not None
    }


def _event_row(fact: dict, tier: str = "") -> Row:
    """Build an event-axis Row from a ``vertex_search`` / ``vertex_facts`` dict.

    These are RAW facts (one per write, the event axis) — ``{kind, ts, observer,
    origin, id, payload}`` — with ``ts`` a ``datetime`` and no top-level
    ``refs``. The address is ``kind/<id>`` (no fold key on the event axis).

    ``tier`` is INHERITED from the entity projection via ``tier_map`` (the
    default ``""`` is UNTIERED — no matching folded entity; the JSON must not
    claim "mid" and the TTY renders the blank gutter, not a rail glyph).
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
        level="fact",
        id=fid,
        ts=ts,
        observer=fact.get("observer", ""),
        origin=fact.get("origin", ""),
        n=1,
        refs=(),
        inbound=0,
        salience=1,
        tier=tier,
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
        "level": row.level,
        "id": row.id,
        "ts": row.ts,
        "observer": row.observer,
        "origin": row.origin,
        "n": row.n,
        "refs": list(row.refs),
        "edges": [{"predicate": e.predicate, "address": e.address} for e in row.edges],
        "inbound": row.inbound,
        "inbound_predicates": [
            {"predicate": p, "count": c} for p, c in row.inbound_predicates
        ],
        "salience": row.salience,
        "tier": row.tier,
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
