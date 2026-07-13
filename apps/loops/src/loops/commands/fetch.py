"""Data retrieval — fold (collapsed state) and stream (event history).

Supports key drill-down via two equivalent surfaces:

- ``--key <prefix>`` flag: ``loops read project --kind decision --key design/``
  filters to items whose key field starts with the prefix. Cross-kind operation
  supported when ``--kind`` is omitted (filters all sections by prefix).
- ``kind/key`` embedded syntax (back-compat): ``--kind thread/fold-state-types``
  is equivalent to ``--kind thread --key fold-state-types``.

Matching is prefix-based and case-insensitive — ``--key design/`` matches
``design/lens-is-the-interface``, ``design/derived-keys-as-focus-filter``, etc.
The filter is prefix-only; there is no exact-match mode — typing a full key
just narrows the prefix to a single item. Whether that item then renders
whole-body or as a headline is a separate concern, decided in ``surface.py``
by exact key equality, not by this filter.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atoms import FoldItem, FoldState, TickWindow


def _parse_duration(s: str) -> float:
    """Parse duration string like '7d', '24h', '1h' to seconds."""
    m = re.match(r"^(\d+)([dhms])$", s)
    if not m:
        raise ValueError(f"Invalid duration: {s!r} (expected e.g. '7d', '24h', '1h')")
    value = int(m.group(1))
    unit = m.group(2)
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return value * multipliers[unit]


def _parse_as_of(s: str, now: datetime) -> float:
    """Resolve an ``--as-of`` value to an anchor epoch ``ts`` (SPEC §9.3).

    The anchor is the read's upper bound: facts replay up to it and — the
    equal-cursors default — the ontology resolves at it. Accepts either a
    duration ("ago" from ``now``, same grammar as ``--since``: ``7d``/``24h``)
    or an absolute position (epoch seconds, or an ISO-8601 timestamp). Absolute
    forms matter for a precise rewind — a cursor landing strictly between two
    declaration edits — where a duration-from-now would be timing-fragile.
    """
    if re.match(r"^\d+[dhms]$", s):
        return (now - timedelta(seconds=_parse_duration(s))).timestamp()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(
            f"Invalid --as-of {s!r} (expected a duration e.g. '7d', epoch "
            "seconds, or an ISO-8601 timestamp)"
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _split_kind_key(kind: str | None) -> tuple[str | None, str | None]:
    """Split ``kind/key`` into (kind, key). Plain kind returns (kind, None)."""
    if kind is None:
        return None, None
    if "/" in kind:
        k, v = kind.split("/", 1)
        return k, v
    return kind, None


def _get_key_field(
    vertex_path: Path, kind: str, *, as_of: float | None = None
) -> str | None:
    """Look up the key field for a kind from the vertex's fold declarations.

    Resolves through the store-backed declaration seam (SPEC §9.5), so an
    ``as_of`` ``ts`` cursor picks the fold key in force at that historical
    position (equal-cursors, §9.3). ``as_of=None`` = head.
    """
    from engine import load_declaration
    from lang.ast import FoldBy

    ast = load_declaration(vertex_path, as_of=as_of)
    loop_def = ast.loops.get(kind)
    if loop_def and loop_def.folds:
        fold_decl = loop_def.folds[0]
        if isinstance(fold_decl.op, FoldBy):
            return fold_decl.op.key_field
    return None


def fetch_fold(
    vertex_path: Path,
    kind: str | None = None,
    key: str | None = None,
    observer: str | None = None,
    retain_facts: bool = False,
    refs_depth: int = 0,
) -> "FoldState":
    """Fetch fold state, with optional key prefix drill-down.

    Two equivalent calling conventions for keys:

    - Explicit: ``fetch_fold(vp, kind="decision", key="design/")``
    - Embedded (back-compat): ``fetch_fold(vp, kind="decision/design/")``

    Both produce the same result. Key matching is prefix-based (``.startswith()``,
    case-insensitive) — ``key="design/"`` matches every item whose fold-key field
    starts with ``design/``. There is no exact-match mode here; passing a full
    key just narrows the prefix to a single item. Whole-vs-headline granularity
    is decided separately in ``surface.py`` by exact key equality.

    When ``kind`` is omitted but ``key`` is provided, filtering runs across all
    sections — each section uses its own declared key_field. Sections with no
    matches are dropped.

    ``refs_depth`` controls outbound ref-graph walk. When ``> 0``, walks
    each primary item's outbound ``ref=kind:key`` entries to fetch the
    referenced entities (up to N hops) and includes them in the returned
    state's ``walked`` field. Primary sections are unaffected. See
    decision/atoms/walked-items-as-foldstate-extension for the shape.
    A2 of the trace-dissolution arc — walk is outbound only.
    """
    from atoms import FoldSection, FoldState
    from engine import vertex_fold

    # Back-compat: split embedded kind/key syntax when no explicit key given.
    if kind and key is None and "/" in kind:
        kind, key = _split_kind_key(kind)

    state = vertex_fold(
        vertex_path, observer=observer, kind=kind,
        retain_facts=retain_facts,
    )

    if key is not None:
        # Filter each section's items by the section's own key_field (prefix match).
        # When kind was set, state has one section; when kind was None, state has
        # all sections and we filter each by its own declared key_field.
        filtered: list[FoldSection] = []
        surviving_source_keys: set[str] = set()
        for section in state.sections:
            matches = tuple(
                item for item in section.items
                if _item_matches_key(item, section.key_field, key)
            )
            if matches:
                filtered.append(FoldSection(
                    kind=section.kind,
                    items=matches,
                    sections=section.sections,
                    fold_type=section.fold_type,
                    key_field=section.key_field,
                    scalars=section.scalars,
                    preview_fields=section.preview_fields,
                ))
                if section.key_field:
                    for item in matches:
                        key_value = str(item.payload.get(section.key_field, ""))
                        surviving_source_keys.add(f"{section.kind}/{key_value}")

        # Preserve source_facts for surviving items only (drop entries whose
        # fold item was filtered out). Without this, retain_facts=True + key
        # filtering would silently drop the lifecycle data that retain-facts
        # consumers (the --facts read path) depend on.
        filtered_source_facts = {
            k: v for k, v in state.source_facts.items()
            if k in surviving_source_keys
        }

        state = FoldState(
            sections=tuple(filtered),
            vertex=state.vertex,
            source_facts=filtered_source_facts,
        )

    if refs_depth > 0:
        state = _walk_refs(state, vertex_path, observer, refs_depth)

    return state


def _walk_refs(
    state: "FoldState",
    vertex_path: Path,
    observer: str | None,
    refs_depth: int,
) -> "FoldState":
    """Outbound ref-graph walk from primary items, up to ``refs_depth`` hops.

    For each primary item, parses its ``refs`` tuple (entries in ``kind:key``
    form per the runbook convention; bare or unparseable entries are skipped),
    fetches the referenced entity's fold item, and adds it to the result's
    ``walked`` tuple. depth=1 items are direct refs of primaries; depth=2+
    are refs-of-refs, with ``via_anchor`` preserving the immediate parent so
    lenses can render lineage chains.

    Cycle protection: a ``visited`` set holds all addresses (primaries +
    walked) — once visited, an address is never re-added, preventing both
    cycles and re-rendering an entity twice. The address is the
    ``section_kind/key`` form.

    Implementation note: each walk-hop calls ``fetch_fold`` recursively with
    ``refs_depth=0`` (default), so the inner call doesn't loop. The recursive
    call lets us reuse the kind/key filtering logic unchanged.
    """
    from atoms import FoldState, WalkedItem

    # Build primary visited set + initial frontier
    visited: set[str] = set()
    frontier: list[tuple[str, str, str, int]] = []  # (via_anchor, target_kind, target_key, depth)

    for section in state.sections:
        kf = section.key_field
        if not kf:
            continue
        for item in section.items:
            key_value = str(item.payload.get(kf, ""))
            if not key_value:
                continue
            anchor_addr = f"{section.kind}/{key_value}"
            visited.add(anchor_addr)
            for ref in _outbound_addresses(item):
                parsed = _parse_ref_to_kind_key(ref)
                if parsed is None:
                    continue
                rk, rkey = parsed
                target_addr = f"{rk}/{rkey}"
                if target_addr in visited:
                    continue
                frontier.append((anchor_addr, rk, rkey, 1))

    walked: list[WalkedItem] = []
    while frontier:
        next_frontier: list[tuple[str, str, str, int]] = []
        for via_anchor, target_kind, target_key, depth in frontier:
            target_addr = f"{target_kind}/{target_key}"
            if target_addr in visited:
                continue
            visited.add(target_addr)
            # Fetch this entity (refs_depth=0 so inner call doesn't walk)
            target_state = fetch_fold(
                vertex_path, kind=target_kind, key=target_key,
                observer=observer,
            )
            for tsection in target_state.sections:
                tkf = tsection.key_field
                if not tkf:
                    continue
                for titem in tsection.items:
                    tkey = str(titem.payload.get(tkf, ""))
                    this_addr = f"{tsection.kind}/{tkey}"
                    # The fetched state may include other items (prefix match);
                    # only add the one matching our exact target.
                    if this_addr != target_addr:
                        continue
                    walked.append(WalkedItem(
                        item=titem, section_kind=tsection.kind,
                        key_field=tkf,
                        via_anchor=via_anchor, depth=depth,
                    ))
                    if depth < refs_depth:
                        for ref in _outbound_addresses(titem):
                            parsed = _parse_ref_to_kind_key(ref)
                            if parsed is None:
                                continue
                            rk, rkey = parsed
                            new_addr = f"{rk}/{rkey}"
                            if new_addr in visited:
                                continue
                            next_frontier.append((this_addr, rk, rkey, depth + 1))
        frontier = next_frontier

    return FoldState(
        sections=state.sections,
        vertex=state.vertex,
        unfolded=state.unfolded,
        source_facts=state.source_facts,
        walked=tuple(walked),
    )


def _outbound_addresses(item) -> "list[str]":
    """All outbound edge addresses of an item: ``ref`` union edges + typed edges.

    Typed edges are declaration-lit (``edge <field> targets=<kind>``) and
    normalized to ``kind:key`` at read time, so ``stakeholder=acme`` walks the
    same as an explicit ``ref=person:acme``. Both feed the ref-graph frontier.
    """
    out = list(item.refs)
    out.extend(edge.address for edge in getattr(item, "edges", ()))
    return out


def _parse_ref_to_kind_key(ref: str) -> "tuple[str, str] | None":
    """Parse a ref string into (kind, key). Returns None if unparseable.

    Refs are stored in two forms in the wild:
    * ``kind:key`` (newer runbook convention, fully qualified) — supported
    * ``key`` only (legacy / same-kind-implied) — skipped (ambiguous)

    Items expose their refs as pre-extracted strings; the address format
    follows the ``kind:key`` discipline. Bare-key refs lose the cross-kind
    dispatch info, so we can't safely walk them — the walk would have to
    guess the kind.
    """
    if not ref or ":" not in ref:
        return None
    k, v = ref.split(":", 1)
    if not k or not v:
        return None
    return k, v


def _item_matches_key(item: "FoldItem", key_field: str | None, key: str) -> bool:
    """Check if a fold item's key matches a prefix (case-insensitive).

    Tries the section's declared key_field first, then common label fields
    (topic, name, title, summary). Prefix-only via ``.startswith()`` — a full
    key narrows the prefix to one item, a shorter prefix matches a subtree;
    there is no exact-match branch. Whole-vs-headline granularity is decided
    separately in ``surface.py`` by exact key equality.
    """
    candidates = [key_field] if key_field else []
    candidates.extend(["topic", "name", "title", "summary"])

    key_lower = key.lower()
    for field in candidates:
        if field and field in item.payload:
            val = str(item.payload[field]).lower()
            if val.startswith(key_lower):
                return True
    return False


def fetch_stream(
    vertex_path: Path,
    *,
    kind: str | None = None,
    since: str | None = None,
    observer: str | None = None,
    as_of: str | None = None,
) -> dict:
    """Fetch the temporal event stream (raw facts, reverse-chrono).

    Content search is NOT here anymore — it re-bound onto ``read --match`` (the
    Surface ``search()`` transform, S5). This is the pure temporal-query path:
    raw facts in a time window, optionally narrowed by ``kind``/``observer``.

    Supports ``kind/key`` drill-down: ``--kind thread/fold-state-types``
    returns only facts whose key field payload starts with the prefix
    (case-insensitive). When drilling down, time window defaults to all
    history (not 7d).

    ``as_of`` (SPEC §9.3, equal-cursors default) rewinds the read to a
    historical anchor: facts replay up to it AND the ontology — the fold key
    fields used to extract each row's key — resolves at the SAME anchor. Absent,
    the anchor is ``now`` and the ontology cursor is ``None`` (head): the exact
    pre-S5 path, so ``as_of``=head is byte-identical to current behavior. The
    fact window's lower bound is ``anchor - since``. Tier decoration stays head
    (Q3 — tier is lens/present-session state, SPEC §9.3).

    Returns ``{"facts": list[dict], "fold_meta": dict, "vertex": str}``.
    """
    from engine import load_declaration, vertex_facts
    from lang.ast import FoldBy
    from lang.document import is_internal_kind

    kind_filter, key_filter = _split_kind_key(kind)

    # When drilling into a specific item, default to all history
    default_since = "7d" if key_filter is None else "3650d"
    since_secs = _parse_duration(since or default_since)
    now = datetime.now(timezone.utc)

    # Equal-cursors (SPEC §9.3): one anchor is BOTH the fact-window upper bound
    # and the ontology-as-of cutoff. cursor=None (head) when --as-of is absent
    # keeps the equivalence property exact.
    anchor = _parse_as_of(as_of, now) if as_of else now.timestamp()
    cursor = anchor if as_of else None
    since_ts = anchor - since_secs

    # Explicit --kind _decl.<x> is the SPEC §9.4 escape hatch — it overrides
    # the ambient exclusion of the reserved namespace everywhere else.
    facts = vertex_facts(
        vertex_path, since_ts, anchor, kind=kind_filter,
        observer=observer,
        include_internal=bool(kind_filter and is_internal_kind(kind_filter)),
        as_of=cursor,
    )

    # Key drill-down: filter facts by payload key field value (as-of fold key)
    if key_filter is not None:
        key_field = (
            _get_key_field(vertex_path, kind_filter, as_of=cursor)
            if kind_filter else None
        )
        facts = [
            f for f in facts
            if _fact_matches_key(f, key_field, key_filter)
        ]

    facts.sort(key=lambda f: f["ts"], reverse=True)

    # Normalize timestamps for JSON serialization
    for f in facts:
        if isinstance(f["ts"], datetime):
            f["ts"] = f["ts"].isoformat()

    # Fold declarations for rendering hints — resolved through the store-backed
    # seam at the ontology-as-of cursor so key_field extraction under rewind
    # uses the as-of fold keys, not head's (SPEC §9.3 equal-cursors).
    ast = load_declaration(vertex_path, as_of=cursor)
    fold_meta: dict[str, dict] = {}
    for k, loop_def in ast.loops.items():
        key_field = None
        if loop_def.folds:
            fold_decl = loop_def.folds[0]
            if isinstance(fold_decl.op, FoldBy):
                key_field = fold_decl.op.key_field
        fold_meta[k] = {"key_field": key_field}

    # Tier inheritance (decision:design/tier-one-home-inheritance): fold the
    # WHOLE vertex (unfiltered — the same path `sl read` uses), project the
    # entity Surface compute-only, and derive the (kind,key)→tier map. The
    # rendered rows stay the windowed facts; each inherits its key's tier by
    # lookup. No match → untiered "" (collect id aged out, unfolded kind).
    _tag_facts_with_tier(vertex_path, facts, fold_meta)

    return {"facts": facts, "fold_meta": fold_meta, "vertex": ast.name}


def _tag_facts_with_tier(
    vertex_path: Path, facts: list[dict], fold_meta: dict[str, dict]
) -> None:
    """Stamp each fact dict with an inherited ``tier`` (in place).

    Folds the full vertex once, projects the entity Surface, and looks each
    fact's ``(kind, key)`` up in ``tier_map``. Compute-only: the Surface is
    never rendered — only its tier assignment is borrowed, so the glyph a key
    shows in the stream is the glyph ``sl read`` gives it.
    """
    from loops.surface import project, tier_map

    try:
        surface = project(fetch_fold(vertex_path))
    except Exception:
        # Tier is a decoration; a fold failure must not break the stream.
        for f in facts:
            f["tier"] = ""
        return
    tmap = tier_map(surface)
    for f in facts:
        kind = f.get("kind", "")
        key_field = fold_meta.get(kind, {}).get("key_field")
        key = str(f.get("payload", {}).get(key_field, "")) if key_field else ""
        f["tier"] = tmap.get((kind, key), "") if key else ""


def _fact_matches_key(fact: dict, key_field: str | None, key: str) -> bool:
    """Check if a raw fact's payload matches a key prefix (case-insensitive)."""
    payload = fact.get("payload", {})
    candidates = [key_field] if key_field else []
    candidates.extend(["topic", "name", "title", "summary"])

    key_lower = key.lower()
    for field in candidates:
        if field and field in payload:
            val = str(payload[field]).lower()
            if val.startswith(key_lower):
                return True
    return False


def fetch_fact_by_id(
    vertex_path: Path,
    fact_id: str,
) -> dict | None:
    """Fetch a single fact by ID or ID prefix.

    Returns the full fact dict with id, kind, ts, observer, origin, payload.
    Returns None if not found. Raises ValueError on ambiguous prefix.
    """
    from engine import vertex_fact_by_id

    return vertex_fact_by_id(vertex_path, fact_id)


def fetch_ticks(
    vertex_path: Path,
    *,
    since: str | None = None,
    as_of: str | None = None,
) -> dict:
    """Fetch tick history from a vertex's store.

    Returns ``{"ticks": list[dict], "vertex": str}``.
    Each tick dict has: name, ts, since, origin, payload, fact_count, kind_counts.
    Ticks are returned newest-first.

    ``as_of`` (SPEC §9.3, equal-cursors) rewinds the tick-window read to a
    historical anchor: the window upper bound and the ontology cursor are the
    same value. Absent → anchor ``now`` / cursor ``None`` (head). Tier stays
    head (Q3, lens state). A tick DRILL (``--ticks <idx>``) interprets its own
    snapshot under ``as_of = tick.ts`` regardless — that lives in
    ``engine.vertex_tick_fold``, not here.
    """
    from engine import load_declaration, vertex_ticks

    since_secs = _parse_duration(since or "30d")
    now = datetime.now(timezone.utc)
    anchor = _parse_as_of(as_of, now) if as_of else now.timestamp()
    cursor = anchor if as_of else None
    since_ts = anchor - since_secs

    ticks = vertex_ticks(vertex_path, since_ts, anchor, as_of=cursor)

    ast = load_declaration(vertex_path, as_of=cursor)
    fold_meta = _get_fold_meta(vertex_path, as_of=cursor)

    # Tier inheritance for tick windows (decision:design/tier-one-home-
    # inheritance + salience-max-propagation): a tick is a tree-cut container
    # whose tier is the MAX over the tiers of the keys it touched. Same tier_map
    # as stream — folded once, never re-computed. Best-effort: a fold failure
    # leaves ticks untiered rather than breaking the history read.
    tmap: dict = {}
    try:
        from loops.surface import project, tier_map

        tmap = tier_map(project(fetch_fold(vertex_path)))
    except Exception:
        tmap = {}

    # Convert Tick objects to dicts with summary info derived from payload
    tick_dicts = []
    for tick in reversed(ticks):  # newest first
        payload = tick.payload if isinstance(tick.payload, dict) else {}
        # Derive kind counts from payload keys (fold state has kind -> items)
        kind_counts: dict[str, int] = {}
        for k, v in payload.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and "items" in v:
                kind_counts[k] = len(v["items"])
            elif isinstance(v, list):
                kind_counts[k] = len(v)
        boundary = payload.get("_boundary", {})

        tick_dicts.append({
            "name": tick.name,
            "ts": tick.ts.isoformat(),
            "since": tick.since.isoformat() if tick.since else None,
            "origin": tick.origin,
            "boundary": boundary,
            "kind_counts": kind_counts,
            "tier": _window_tier(vertex_path, tick, tmap, fold_meta) if tmap else "",
        })

    return {"ticks": tick_dicts, "vertex": ast.name}


def _window_tier(
    vertex_path: Path, tick, tmap: dict, fold_meta: dict[str, dict]
) -> str:
    """MAX tier over the keys a tick's window touched (tree-cut propagation)."""
    start = tick.since.timestamp() if tick.since else 0.0
    return window_stats(vertex_path, start, tick.ts.timestamp(), tmap, fold_meta)["tier"]


def stamp_window_stats(vertex_path: Path, window_dicts: list[dict]) -> None:
    """Stamp window-scoped attention stats onto TickWindow dicts, in place.

    Adds ``win_facts`` / ``win_kinds`` / ``tier`` / ``touched`` per window
    (see :func:`window_stats`). Best-effort: a fold failure leaves the dicts
    unstamped — the lens renders unstamped windows without a count claim
    rather than a false zero.
    """
    from loops.surface import project, tier_map

    try:
        tmap = tier_map(project(fetch_fold(vertex_path)))
        fold_meta = _get_fold_meta(vertex_path)
    except Exception:
        return
    if not (tmap or fold_meta):
        return
    for wd in window_dicts:
        stats = window_stats(
            vertex_path, wd.get("since") or 0.0, wd["ts"], tmap, fold_meta
        )
        wd["win_facts"] = stats["facts"]
        wd["win_kinds"] = stats["kinds"]
        wd["tier"] = stats["tier"]
        wd["touched"] = stats["touched"]


def window_stats(
    vertex_path: Path,
    start: float,
    end: float,
    tmap: dict,
    fold_meta: dict[str, dict],
) -> dict:
    """Window-scoped attention summary for one tick's ``since..ts`` interval.

    One fact query yields the whole projection — a tick row answers "what did
    this session touch", so every stat here is scoped to the WINDOW, not the
    cumulative fold snapshot the tick payload carries (TickWindow.kind_summary
    / total_facts are cumulative; these are the per-window complements):

    - ``facts``: fact count inside the window
    - ``kinds``: per-kind window counts, descending
    - ``tier``: MAX tier over touched keys (decision:design/
      salience-max-propagation — a container is as hot as its hottest member;
      all-untiered or keyless windows are untiered "")
    - ``touched``: [(kind, key, n), ...] keyed facts by touch count,
      descending — the -v drill toward the promised hot key

    Best-effort: a query failure returns the empty projection rather than
    breaking the history read.
    """
    from collections import Counter

    from engine import vertex_facts

    from loops.surface import tier_max

    empty = {"facts": 0, "kinds": {}, "tier": "", "touched": []}
    try:
        facts = vertex_facts(vertex_path, start, end)
    except Exception:
        return empty
    kinds: Counter = Counter()
    touched: Counter = Counter()
    tiers: list[str] = []
    for f in facts:
        kind = f.get("kind", "")
        kinds[kind] += 1
        key_field = fold_meta.get(kind, {}).get("key_field")
        if not key_field:
            continue
        key = str(f.get("payload", {}).get(key_field, ""))
        if key:
            touched[(kind, key)] += 1
            tiers.append(tmap.get((kind, key), ""))
    return {
        "facts": sum(kinds.values()),
        "kinds": dict(kinds.most_common()),
        "tier": tier_max(tiers),
        "touched": [(k, key, n) for (k, key), n in touched.most_common()],
    }


def fetch_confluence(
    vertex_path: Path,
    *,
    kind: str | None = None,
    observer: str | None = None,
) -> dict:
    """Observer-cut projection — the store as a social object (Confluence).

    The third axis: fold cuts by kind, stream/ticks cut by time; Confluence
    cuts by observer. One ``vertex_facts`` scan yields the whole projection —
    per observer: fact count, kind census, distinct keys touched, the touched
    ``(kind, key, n)`` list (the -v drill), first/last activity, and a tier
    inherited from the one tier home (an observer is a container cut — MAX
    over the tiers of the keys it touched, decision:design/
    salience-max-propagation; an observer who touched no folded key is
    untiered "").

    Observer names stay BARE strings (decision:design/
    observer-typing-dissolves-to-declared-peer) — grouping of ``a/b``
    delegation-path compounds is a render concern, not encoded here.

    Returns a JSON-clean dict::

        {"vertex": str, "total_facts": int,
         "observers": [{"name", "count", "kinds", "keys", "touched",
                        "first", "last", "tier"}, ...]}  # count-desc
    """
    from collections import Counter

    from engine import vertex_facts
    from lang import parse_vertex_file
    from lang.document import is_internal_kind

    from loops.surface import tier_max

    ast = parse_vertex_file(vertex_path)
    fold_meta = _get_fold_meta(vertex_path)
    now = datetime.now(timezone.utc).timestamp()
    # Explicit --kind _decl.<x> is the SPEC §9.4 escape hatch (see fetch_stream).
    facts = vertex_facts(
        vertex_path, 0.0, now, kind=kind, observer=observer,
        include_internal=bool(kind and is_internal_kind(kind)),
    )

    # Tier decoration is best-effort — a fold failure leaves observers
    # untiered rather than breaking the read (same stance as stream/ticks).
    tmap: dict = {}
    try:
        from loops.surface import project, tier_map

        tmap = tier_map(project(fetch_fold(vertex_path)))
    except Exception:
        tmap = {}

    per: dict[str, dict] = {}
    for f in facts:
        obs = f.get("observer") or ""
        entry = per.setdefault(
            obs,
            {"kinds": Counter(), "touched": Counter(), "first": None, "last": None},
        )
        k = f.get("kind", "")
        entry["kinds"][k] += 1
        ts = f.get("ts")
        if isinstance(ts, datetime):
            if entry["first"] is None or ts < entry["first"]:
                entry["first"] = ts
            if entry["last"] is None or ts > entry["last"]:
                entry["last"] = ts
        key_field = fold_meta.get(k, {}).get("key_field")
        if key_field:
            key = str(f.get("payload", {}).get(key_field, ""))
            if key:
                entry["touched"][(k, key)] += 1

    observers = []
    for name, e in per.items():
        observers.append({
            "name": name,
            "count": sum(e["kinds"].values()),
            "kinds": dict(e["kinds"].most_common()),
            "keys": len(e["touched"]),
            "touched": [[k, key, n] for (k, key), n in e["touched"].most_common()],
            "first": e["first"].isoformat() if e["first"] else None,
            "last": e["last"].isoformat() if e["last"] else None,
            "tier": tier_max([tmap.get(kk, "") for kk in e["touched"]]),
        })
    observers.sort(key=lambda o: (-o["count"], o["name"]))

    return {
        "vertex": ast.name,
        "total_facts": len(facts),
        "observers": observers,
    }


# Recursion-depth safety valve. Termination is guaranteed by the per-path cycle
# guard (a back-edge to an ancestor is skipped), so this only bounds the length
# of a single SIMPLE path against Python's call stack. It is deliberately well
# above realistic chain lengths (the live project vertex tops out near 60). When
# the cap DOES halt expansion the resulting chain is marked ``truncated`` and the
# result is not cached (a cap hit taints, same rule as a skipped back-edge) so no
# later reuse inherits the shortened path. The design entry's provisional "32"
# was a pre-implementation guess that predated seeing real chain depths.
_CHAIN_DEPTH_CAP = 128

# Total node-visit budget across the whole traversal — a blowup guard for a
# pathological fan-out where taint (see below) forces heavy recomputation. If
# exhausted the traversal stops expanding and the payload is flagged
# ``chains_approximate`` so both registers disclose that the walk was cut short.
_CHAIN_VISIT_BUDGET = 200_000


def _longest_chains(
    adjacency: dict[str, list[tuple[str, str]]],
    *,
    cap: int = _CHAIN_DEPTH_CAP,
    budget: int = _CHAIN_VISIT_BUDGET,
) -> tuple[dict[str, list[str]], set[str], bool]:
    """Longest downstream chain starting at each node — taint-aware memoized DFS.

    ``adjacency`` maps source address → [(target address, predicate), ...] over
    the RESOLVED graph (targets that exist as nodes). Refs point temporally
    backward so the graph is a near-DAG; a per-path ``stack`` guard skips
    back-edges (a target already on the current path — a cycle) so a cyclic
    fixture never recurses forever.

    Memoization invariant — a node's result is cached ONLY when its entire
    downstream exploration was *clean*: no on-stack back-edge was skipped and no
    depth-cap truncation occurred anywhere beneath it. A back-edge skip makes the
    result path-dependent (the same node reached along a different path may not
    close that cycle and can extend further), so a *tainted* result is returned
    but never cached — it is recomputed per reaching path. Caching a tainted
    result is exactly the poisoning bug this guards against.

    Returns ``(chains, truncated, exhausted)`` — ``chains`` maps node → its
    longest chain (including the node); ``truncated`` is the set of start nodes
    whose winning chain was cut by the depth cap; ``exhausted`` is True if the
    visit budget ran out (results then approximate). Neighbours are walked in
    sorted order and ties break lexicographically, so the result is
    deterministic.
    """
    memo: dict[str, tuple[list[str], bool]] = {}
    visits = 0
    exhausted = False

    def dfs(node: str, stack: set[str]) -> tuple[list[str], bool, bool]:
        """Return (best_path, truncated, clean) for ``node``.

        ``truncated`` marks the winning path as cut by the depth cap; ``clean``
        marks the whole subtree as free of back-edge skips AND truncation (i.e.
        cacheable).
        """
        nonlocal visits, exhausted
        if node in memo:
            path, trunc = memo[node]
            return path, trunc, True
        visits += 1
        if visits > budget:
            exhausted = True
            return [node], False, False  # tainted — not cached
        best: list[str] = [node]
        best_trunc = False
        clean = True
        hit_cap = False
        stack.add(node)
        if len(stack) < cap:
            targets = sorted({t for t, _ in adjacency.get(node, ())})
            for tgt in targets:
                if tgt in stack:
                    clean = False  # back-edge skipped — result is path-dependent
                    continue
                sub, sub_trunc, sub_clean = dfs(tgt, stack)
                clean = clean and sub_clean
                cand = [node, *sub]
                if len(cand) > len(best) or (
                    len(cand) == len(best) and cand < best
                ):
                    best = cand
                    best_trunc = sub_trunc
        elif adjacency.get(node):
            hit_cap = True  # cap halted expansion at a node that HAS targets
        stack.discard(node)
        node_trunc = best_trunc or hit_cap
        if clean and not node_trunc:
            memo[node] = (best, node_trunc)
        return best, node_trunc, clean

    chains: dict[str, list[str]] = {}
    truncated: set[str] = set()
    for n in adjacency:
        path, trunc, _ = dfs(n, set())
        chains[n] = path
        if trunc:
            truncated.add(n)
    return chains, truncated, exhausted


def _top_chains(
    chains: dict[str, list[str]],
    truncated: set[str],
    *,
    limit: int = 10,
) -> list[dict]:
    """Distinct longest chains, longest-first, dropping sub-chains of picks.

    A chain needs at least one edge (length ≥ 2). Candidates sort by
    ``(-len, path)``; a candidate that is a contiguous sub-path of an
    already-selected chain is dropped (it adds no new membership). Each pick is
    returned as ``{"path": [...], "truncated": bool}`` — ``truncated`` is set
    when the depth cap cut this start node's chain.
    """
    cands = sorted(
        ((node, p) for node, p in chains.items() if len(p) >= 2),
        key=lambda np: (-len(np[1]), np[1]),
    )

    def _is_subpath(short: list[str], long: list[str]) -> bool:
        n = len(short)
        return any(long[i : i + n] == short for i in range(len(long) - n + 1))

    picked: list[dict] = []
    for node, c in cands:
        if any(_is_subpath(c, sel["path"]) for sel in picked):
            continue
        picked.append({"path": c, "truncated": node in truncated})
        if len(picked) >= limit:
            break
    return picked


def fetch_graph(
    vertex_path: Path,
    *,
    kind: str | None = None,
    observer: str | None = None,
) -> dict:
    """Ref/edge-graph projection — the store as a directed graph (Graph view).

    A pure projection over the entity ``Surface`` (``project(fetch_fold())``);
    zero engine SQL beyond the fold fetch. Nodes are folded entities, edges are
    their outbound refs + typed edges RESOLVED to another node (dangling refs —
    pointing at no node — are counted, not walked). Three cuts:

    * **hubs** — nodes by inbound count desc; the ``←N`` sinks. Each hub also
      carries its RESOLVED outbound degree ``→M`` + neighbor addresses on both
      arms (``in_addrs``/``out_addrs``, node→node only — dangling refs excluded,
      symmetric with ``edges``); ranking stays inbound-only, ``→M`` is context
      (decision:design/graph-outbound-resolved-only). Predicate mix (``ref`` vs
      declared typed-edge field names) is where typed edges become VISIBLE, per
      decision:design/graph-build1-scope.
    * **chains** — longest directed ref paths (net-new traversal; taint-aware
      memoized DFS with a per-path cycle guard + depth cap 128 + visit budget).
    * **orphans** — nodes with no inbound AND no outbound refs/edges (isolated).

    ``edges`` counts node→node RESOLVED edges only; ``unsourced_inbound``
    discloses how much of the hubs' summed ``←N`` arrives from keyless/sourceless
    facts (refs with no node address to resolve a source edge from).

    Returns a JSON-clean dict (all counts/paths serializable; ``last`` is a
    float epoch like the confluence cut)::

        {"vertex", "nodes", "edges", "typed_edges", "orphans", "dangling",
         "unsourced_inbound", "chains_approximate",
         "hubs": [{address, kind, key, tier, inbound, outbound,
                   predicates:[[p,n]..], in_addrs:[addr..], out_addrs:[addr..],
                   last, observer}, ...],
         "orphan_list": [address, ...],
         "census": [[predicate, count, typed], ...],
         "chains": [{"path": [address, ...], "truncated": bool}, ...]}
    """
    from loops.surface import project

    surface = project(fetch_fold(vertex_path, kind=kind, observer=observer))
    rows = surface.rows
    node_addrs = {r.address for r in rows}

    # Reverse the materialized inbound adjacency into RESOLVED outbound edges:
    # target ← (source, predicate) becomes source → (target, predicate). Both
    # endpoints are "kind/key" node addresses, so no re-matching is needed.
    outbound: dict[str, list[tuple[str, str]]] = {}
    resolved_edges = 0
    typed_edges = 0
    census: dict[str, int] = {}
    for target, sources in surface.inbound_edges.items():
        if target not in node_addrs:
            continue
        for source, pred in sources:
            if source not in node_addrs:
                continue
            outbound.setdefault(source, []).append((target, pred))
            resolved_edges += 1
            census[pred] = census.get(pred, 0) + 1
            if pred != "ref":
                typed_edges += 1

    # Total outbound refs+edges across nodes; the shortfall vs resolved is the
    # dangling count (refs pointing at no node in this vertex).
    total_outbound = sum(len(r.refs) + len(r.edges) for r in rows)
    dangling = max(0, total_outbound - resolved_edges)

    # Per-node RESOLVED neighbor addresses (node→node only, dangling excluded —
    # symmetric with ``edges``/chains/orphans). Outbound reuses the reversed
    # adjacency; inbound reuses the materialized ``inbound_edges``. Sorted +
    # deduped so the -v neighbor lists are deterministic; the lens caps for TTY,
    # piped carries them whole.
    out_neighbors = {
        src: sorted({t for t, _ in tgts}) for src, tgts in outbound.items()
    }
    in_neighbors = {
        target: sorted({s for s, _ in sources if s in node_addrs})
        for target, sources in surface.inbound_edges.items()
        if target in node_addrs
    }

    hubs = [
        {
            "address": r.address,
            "kind": r.kind,
            "key": r.key,
            "tier": r.tier,
            "inbound": r.inbound,
            "outbound": len(outbound.get(r.address, [])),
            "predicates": [[p, n] for p, n in r.inbound_predicates],
            "in_addrs": in_neighbors.get(r.address, []),
            "out_addrs": out_neighbors.get(r.address, []),
            "last": r.ts,
            "observer": r.observer,
        }
        for r in sorted(rows, key=lambda r: (-r.inbound, r.address))
        if r.inbound > 0
    ]

    orphan_list = [
        r.address
        for r in rows
        if r.inbound == 0 and not r.refs and not r.edges
    ]

    census_rows = sorted(
        ([p, n, p != "ref"] for p, n in census.items()),
        key=lambda c: (-c[1], c[0]),
    )

    raw_chains, truncated_nodes, exhausted = _longest_chains(outbound)
    chains = _top_chains(raw_chains, truncated_nodes)

    # ``edges`` counts only node→node RESOLVED edges; a hub's ``←N`` sums
    # Surface Row.inbound, which also counts refs arriving from keyless/sourceless
    # facts (no node address to resolve a source edge from). The gap is disclosed,
    # not redefined — ``←N`` stays the true attention count.
    total_inbound = sum(r.inbound for r in rows)
    sourced_inbound = sum(len(surface.inbound_edges.get(r.address, [])) for r in rows)
    unsourced_inbound = max(0, total_inbound - sourced_inbound)

    return {
        "vertex": surface.vertex,
        "nodes": len(rows),
        "edges": resolved_edges,
        "typed_edges": typed_edges,
        "orphans": len(orphan_list),
        "dangling": dangling,
        "unsourced_inbound": unsourced_inbound,
        "hubs": hubs,
        "orphan_list": orphan_list,
        "census": census_rows,
        "chains": chains,
        "chains_approximate": exhausted,
    }


def _boundary_shape(boundary) -> dict:
    """Describe an AST boundary (BoundaryWhen/After/Every) as a JSON-clean dict.

    The three shapes fold to a common ``mode`` key: ``when`` (kind-triggered)
    carries the trigger kind, payload ``match`` pairs, and fold-state
    ``conditions``; ``after``/``every`` carry a numeric ``count``. This is the
    honest projection of what the declaration says — no runtime state.
    """
    from lang.ast import BoundaryAfter, BoundaryEvery, BoundaryWhen

    if isinstance(boundary, BoundaryWhen):
        return {
            "mode": "when",
            "trigger_kind": boundary.kind,
            "match": [[k, v] for k, v in boundary.match],
            "conditions": [
                [c.target, c.op, c.value] for c in boundary.conditions
            ],
            "count": None,
        }
    if isinstance(boundary, (BoundaryAfter, BoundaryEvery)):
        return {
            "mode": "every" if isinstance(boundary, BoundaryEvery) else "after",
            "trigger_kind": None,
            "match": [],
            "conditions": [],
            "count": boundary.count,
        }
    raise TypeError(f"unknown boundary shape: {type(boundary).__name__}")


def _newest_tick_ts(vertex_path: Path, name: str, now_ts: float) -> float | None:
    """Newest sealed tick timestamp for a series ``name`` — None if never sealed.

    Ticks carry the loop name (per-loop boundary) or the vertex name
    (vertex-level boundary) — see ``Loop.fire`` / ``Vertex._fire_vertex_boundary``.
    Spans the full history (from epoch) so a long-dormant series still reports
    its last seal honestly.
    """
    from engine import vertex_ticks

    ticks = vertex_ticks(vertex_path, 0.0, now_ts, name=name)
    if not ticks:
        return None
    return max(t.ts.timestamp() for t in ticks)


def fetch_horizon(
    vertex_path: Path,
    *,
    kind: str | None = None,
    observer: str | None = None,
) -> dict:
    """Horizon — each armed loop's OPEN (unsealed) window against its boundary.

    Fold cuts by kind, stream/ticks by time, confluence by observer, graph by
    connection; Horizon cuts by CYCLE PROXIMITY — how close each boundaried loop
    is to its next seal. One row per loop that DECLARES a boundary (a vertex-level
    boundary is one row over the whole vertex); loops covered by no trigger at
    all roll up as ``unarmed`` (see below — amending the omission stance of
    decision:design/horizon-build1-scope).

    The net-new piece is read-side reconstruction of the open window: TickWindow
    models sealed ticks only and ``_vertex_period_start`` is runtime-only, so the
    unsealed window is rebuilt here — newest tick ts for the series (or epoch if
    never sealed), then the facts strictly after it aggregated by kind. No
    invented signal: count-based boundaries get numeric proximity (n/N),
    kind-based boundaries get a fact-count + trigger-kind + last-seal recency and
    NEVER a fake progress meter (hlab is 100% kind-based).

    ``kind``/``observer`` are accepted for signature parity with the other
    composition-lens fetches; they do not filter the boundary roster (a loop's
    armed-ness is a declaration property, not a fact-window one).

    UNARMED = uncovered by ANY declared trigger (decision:design/
    horizon-unarmed-rollup, as ratified): a loop is unarmed only when it has no
    boundary of its own AND the vertex declares no vertex-level boundary. A
    vertex-level boundary's tick sweeps the entire window (all kinds), so every
    loop under it is COVERED — its accumulation is bounded by the armed vertex
    row, not silent; listing it as unarmed would double-report that row's
    unsealed window. Unarmed loops roll up into an ``unarmed`` list, each
    carrying the SAME open-window reconstruction the armed rows use: an unarmed
    loop has no tick series, so its window is all history scoped to its own
    kind (honest — nothing has ever sealed it).

    Returns a JSON-clean dict (``last_sealed`` is a float epoch or None)::

        {"vertex", "now", "armed": int, "total_unsealed": int,
         "last_sealed": float | None, "unarmed_facts": int,
         "loops": [{name, scope, mode, trigger_kind, match, conditions, count,
                    last_sealed, never_sealed, window_facts, window_kinds}, ...],
         "unarmed": [{name, window_facts, window_kinds}, ...]}
    """
    from collections import Counter

    from engine import vertex_facts
    from engine.declaration import load_declaration

    ast = load_declaration(vertex_path)
    now_ts = datetime.now(timezone.utc).timestamp()

    # Roster of armed loops: the vertex-level boundary (one row over every kind)
    # plus each per-loop boundary. A vertex declaring both is unusual but honest
    # — both rows render, each against its own tick series.
    armed: list[tuple[str, str, object, str | None]] = []
    for vboundary in ast.boundary:
        # Vertex-level: tick series is named for the vertex; window spans all
        # kinds (the seal snapshots every loop). A vertex may declare more than
        # one (e.g. `session closed` and `seal`) — each is its own honest row
        # over the same shared tick series, distinguished by its trigger.
        armed.append((ast.name, "vertex", vboundary, None))
    for kname, loop_def in ast.loops.items():
        if loop_def.boundary is not None:
            armed.append((kname, "loop", loop_def.boundary, kname))

    loops: list[dict] = []
    total_unsealed = 0
    seals: list[float] = []
    for name, scope, boundary, window_kind in armed:
        last_sealed = _newest_tick_ts(vertex_path, name, now_ts)
        never = last_sealed is None
        since = last_sealed if last_sealed is not None else 0.0
        facts = vertex_facts(vertex_path, since, now_ts, kind=window_kind)
        # facts_between is inclusive on the lower bound, so the fact that
        # triggered the last seal (ts == tick.ts) would re-appear — drop
        # anything at or before the seal to keep the window strictly open.
        window = Counter(
            f["kind"]
            for f in facts
            if never or _fact_epoch(f.get("ts")) > since
        )
        window_facts = sum(window.values())
        total_unsealed += window_facts
        if last_sealed is not None:
            seals.append(last_sealed)

        row = _boundary_shape(boundary)
        row.update({
            "name": name,
            "scope": scope,
            "last_sealed": last_sealed,
            "never_sealed": never,
            "window_facts": window_facts,
            "window_kinds": dict(window.most_common()),
        })
        loops.append(row)

    # Proximity sort (decision:design/horizon-proximity-sort). The loop nearest
    # its boundary rises. Three strata, honest about comparability:
    #   (0) count-based & sealed — by window_facts/count ratio DESC
    #   (1) kind-based & sealed  — by raw window_facts DESC (no ratio exists)
    #   (2) never-sealed         — last (no meaningful proximity yet)
    # Deterministic tie-break: ratio/facts -> declaration order -> name, so two
    # reads of an unchanged store are byte-identical on BOTH registers. Order is
    # information and is applied here (the fetch) so --json carries it too.
    for i, r in enumerate(loops):
        r["_decl"] = i
    loops.sort(key=_horizon_sort_key)
    for r in loops:
        del r["_decl"]

    # Unarmed roster — loops uncovered by ANY declared trigger: no boundary of
    # their own AND no vertex-level boundary over them (decision:design/
    # horizon-unarmed-rollup, ratified coverage rule). A vertex-level boundary's
    # tick sweeps the entire window, so every loop under it is covered — its
    # accumulation is already the armed vertex row's unsealed window, and
    # listing it here would double-report that. The window mirrors the armed
    # reconstruction EXACTLY: an unarmed loop owns no tick series, so
    # ``_newest_tick_ts`` is None → the window is all history scoped to the
    # loop's kind.
    unarmed: list[dict] = []
    unarmed_facts = 0
    if not ast.boundary:
        for kname, loop_def in ast.loops.items():
            if loop_def.boundary is not None:
                continue
            last_tick = _newest_tick_ts(vertex_path, kname, now_ts)
            never = last_tick is None
            since = last_tick if last_tick is not None else 0.0
            facts = vertex_facts(vertex_path, since, now_ts, kind=kname)
            window = Counter(
                f["kind"]
                for f in facts
                if never or _fact_epoch(f.get("ts")) > since
            )
            wf = sum(window.values())
            unarmed_facts += wf
            unarmed.append({
                "name": kname,
                "window_facts": wf,
                "window_kinds": dict(window.most_common()),
            })
        # Accumulation-desc, then name — deterministic so --json/both registers
        # agree.
        unarmed.sort(key=lambda r: (-r["window_facts"], r["name"]))

    return {
        "vertex": ast.name,
        "now": now_ts,
        "armed": len(loops),
        "total_unsealed": total_unsealed,
        "last_sealed": max(seals) if seals else None,
        "unarmed_facts": unarmed_facts,
        "loops": loops,
        "unarmed": unarmed,
    }


def _horizon_sort_key(r: dict) -> tuple:
    """Proximity sort key — three strata, then ratio/facts, decl order, name.

    See decision:design/horizon-proximity-sort. Never-sealed loops have no
    meaningful proximity and fall to the last stratum; count-based sealed loops
    rank by their unsealed/count ratio, kind-based sealed loops by raw window
    fact count (no numerator to form a ratio). Negated metrics give DESC within
    a stratum; ``_decl`` (declaration order) then ``name`` break ties.

    Strata consequence, deliberate: a 1/10 count loop outranks a kind loop
    with 50 window facts — ratio and raw count share no numerator, so the
    strata never interleave on incomparable metrics (comparability over
    global "urgency").
    """
    if r["never_sealed"]:
        return (2, 0.0, r["_decl"], r["name"])
    if r["mode"] == "when":
        return (1, -float(r["window_facts"]), r["_decl"], r["name"])
    count = r.get("count") or 0
    ratio = r["window_facts"] / count if count > 0 else 0.0
    return (0, -ratio, r["_decl"], r["name"])


def _fact_epoch(ts: object) -> float:
    """Coerce a fact ts (datetime / epoch / ISO) to epoch seconds; -inf if none.

    ``vertex_facts`` yields datetimes, but combined/aggregate reads and JSON
    round-trips can carry ISO strings or floats — coerce uniformly so the
    strictly-open-window filter never crashes on a shape it did not expect.
    """
    if isinstance(ts, datetime):
        return ts.timestamp()
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts).timestamp()
        except ValueError:
            return float("-inf")
    return float("-inf")


def _get_fold_meta(
    vertex_path: Path, *, as_of: float | None = None
) -> dict[str, dict]:
    """Extract fold key_field metadata from a vertex's loop declarations.

    Resolves through the store-backed seam (SPEC §9.5); an ``as_of`` ``ts``
    cursor picks the fold keys in force at that historical position
    (equal-cursors, §9.3), so a rewound tick listing derives tier/touched under
    the cursor ontology rather than head. ``as_of=None`` = head.
    """
    from engine import load_declaration
    from lang.ast import FoldBy

    ast = load_declaration(vertex_path, as_of=as_of)
    fold_meta: dict[str, dict] = {}
    for k, loop_def in ast.loops.items():
        key_field = None
        if loop_def.folds:
            fold_decl = loop_def.folds[0]
            if isinstance(fold_decl.op, FoldBy):
                key_field = fold_decl.op.key_field
        fold_meta[k] = {"key_field": key_field}
    return fold_meta


def _load_ticks_newest(
    vertex_path: Path,
    since: str | None = None,
    *,
    with_envelope: bool = False,
):
    """Load ticks newest-first from a vertex store.

    With ``with_envelope=True``, items are ``(Tick, envelope)`` pairs —
    the witness-era attestation metadata (see StoreReader.ticks_between).
    """
    from engine import vertex_ticks

    since_secs = _parse_duration(since or "30d")
    now = datetime.now(timezone.utc)
    since_ts = (now - timedelta(seconds=since_secs)).timestamp()

    ticks = vertex_ticks(
        vertex_path, since_ts, now.timestamp(), with_envelope=with_envelope
    )
    return list(reversed(ticks))


def fetch_tick_facts(
    vertex_path: Path,
    tick_index: int,
    *,
    since: str | None = None,
) -> dict:
    """Fetch the facts that contributed to a specific tick (drill-down).

    *tick_index* is 0-based from most recent. Returns the same shape as
    ``fetch_stream`` so the stream lens can render it, plus tick metadata.
    """
    from engine import load_declaration, vertex_facts

    ticks_newest = _load_ticks_newest(vertex_path, since, with_envelope=True)

    if tick_index < 0 or tick_index >= len(ticks_newest):
        return {
            "facts": [], "fold_meta": {}, "vertex": "",
            "_tick_error": f"Tick index {tick_index} out of range (have {len(ticks_newest)} ticks)",
        }

    tick, envelope = ticks_newest[tick_index]

    # Retrieve facts in the tick's window, interpreted under the ontology in
    # force at the tick's boundary (as_of=tick.ts, equal-cursors §9.3) — the
    # raw-fact drill must render under the same ontology vertex_tick_fold uses.
    # Engine invariant: tick.since is always set to the period's first-fact
    # timestamp — the engine sets _vertex_period_start before firing a boundary.
    tick_ts = tick.ts.timestamp()
    facts = vertex_facts(
        vertex_path,
        tick.since.timestamp(),  # type: ignore[union-attr]
        tick_ts,
        as_of=tick_ts,
    )

    facts.sort(key=lambda f: f["ts"], reverse=True)

    for f in facts:
        if isinstance(f["ts"], datetime):
            f["ts"] = f["ts"].isoformat()

    ast = load_declaration(vertex_path, as_of=tick_ts)

    return {
        "facts": facts,
        "fold_meta": _get_fold_meta(vertex_path, as_of=tick_ts),
        "vertex": ast.name,
        "_tick": _tick_metadata(
            tick, index=tick_index, total=len(ticks_newest), envelope=envelope,
        ),
    }


def fetch_tick_range(
    vertex_path: Path,
    start: int,
    end: int,
    *,
    since: str | None = None,
) -> dict:
    """Fetch facts across a range of ticks (e.g. 0:3 = ticks 0, 1, 2).

    Unions the fact windows from all ticks in [start, end). Returns the
    same shape as ``fetch_tick_facts`` with ``_tick`` metadata covering
    the range.
    """
    from engine import load_declaration, vertex_facts

    ticks_newest = _load_ticks_newest(vertex_path, since)

    if not ticks_newest:
        return {
            "facts": [], "fold_meta": {}, "vertex": "",
            "_tick_error": "No ticks in the given time range",
        }

    # Clamp range to available ticks
    end = min(end, len(ticks_newest))
    if start >= end or start < 0:
        return {
            "facts": [], "fold_meta": {}, "vertex": "",
            "_tick_error": f"Tick range {start}:{end} out of range (have {len(ticks_newest)} ticks)",
        }

    selected = ticks_newest[start:end]

    # The whole range renders under ONE ontology — the range's upper boundary
    # (selected[0], the newest tick, since ticks_newest is newest-first). This
    # matches fetch_tick_range_fold, which folds selected[0]'s snapshot under
    # as_of=selected[0].ts (§9.3 equal-cursors); a single fold_meta cannot
    # honestly carry two ontologies, so the range upper is the coherent choice.
    range_ts = selected[0].ts.timestamp()

    # Union facts across all tick windows, all under the range-upper ontology.
    all_facts: list[dict] = []
    for tick in selected:
        if tick.since is not None:
            facts = vertex_facts(
                vertex_path,
                tick.since.timestamp(),
                tick.ts.timestamp(),
                as_of=range_ts,
            )
            all_facts.extend(facts)

    # Fact IDs are ULIDs (unique per write), so no dedup needed.
    all_facts.sort(key=lambda f: f["ts"], reverse=True)

    for f in all_facts:
        if isinstance(f["ts"], datetime):
            f["ts"] = f["ts"].isoformat()

    ast = load_declaration(vertex_path, as_of=range_ts)

    # Collect boundary info from all ticks in range
    boundaries = []
    for tick in selected:
        boundary = tick.payload.get("_boundary", {}) if isinstance(tick.payload, dict) else {}
        boundaries.append({
            "name": boundary.get("name", tick.name),
            "status": boundary.get("status", ""),
        })

    return {
        "facts": all_facts,
        "fold_meta": _get_fold_meta(vertex_path, as_of=range_ts),
        "vertex": ast.name,
        "_tick": {
            "name": selected[0].name,
            "ts": selected[0].ts.isoformat(),
            "since": selected[-1].since.isoformat() if selected[-1].since else None,
            "boundary": boundaries[0] if boundaries else {},
            "index": start,
            "total": len(ticks_newest),
            "range_end": end,
            "range_boundaries": boundaries,
        },
    }


def _tick_metadata(tick, *, index: int, total: int, envelope: dict | None = None) -> dict:
    """Build tick metadata dict for a single tick.

    *envelope* is the witness-era attestation metadata (chained, signed,
    cursor dereference). Included under ``"envelope"`` only when provided —
    absence means "not read", not "not attested".
    """
    boundary = tick.payload.get("_boundary", {}) if isinstance(tick.payload, dict) else {}
    meta = {
        "name": tick.name,
        "ts": tick.ts.isoformat(),
        "since": tick.since.isoformat() if tick.since else None,
        "boundary": boundary,
        "index": index,
        "total": total,
    }
    if envelope is not None:
        meta["envelope"] = envelope
    return meta


def _tick_range_metadata(selected, *, start: int, end: int, total: int) -> dict:
    """Build tick metadata dict for a range of ticks."""
    boundaries = []
    for tick in selected:
        boundary = tick.payload.get("_boundary", {}) if isinstance(tick.payload, dict) else {}
        boundaries.append({
            "name": boundary.get("name", tick.name),
            "status": boundary.get("status", ""),
        })
    return {
        "name": selected[0].name,
        "ts": selected[0].ts.isoformat(),
        "since": selected[-1].since.isoformat() if selected[-1].since else None,
        "boundary": boundaries[0] if boundaries else {},
        "index": start,
        "total": total,
        "range_end": end,
        "range_boundaries": boundaries,
    }


def fetch_tick_fold(
    vertex_path: Path,
    tick_index: int,
    *,
    since: str | None = None,
) -> dict:
    """Fetch the fold state snapshot from a tick's payload.

    Unlike ``fetch_tick_facts`` which re-queries the facts table for the
    tick's time window, this returns the actual fold state stored in the
    tick — the full accumulated state at that boundary.

    Returns ``{"fold_state": FoldState, "_tick": {...}}``.
    """
    from engine import vertex_tick_fold

    ticks_newest = _load_ticks_newest(vertex_path, since, with_envelope=True)

    if tick_index < 0 or tick_index >= len(ticks_newest):
        return {
            "fold_state": None,
            "_tick_error": f"Tick index {tick_index} out of range (have {len(ticks_newest)} ticks)",
        }

    tick, envelope = ticks_newest[tick_index]
    fold_state = vertex_tick_fold(vertex_path, tick)

    return {
        "fold_state": fold_state,
        "_tick": _tick_metadata(
            tick, index=tick_index, total=len(ticks_newest), envelope=envelope,
        ),
    }


def fetch_tick_range_fold(
    vertex_path: Path,
    start: int,
    end: int,
    *,
    since: str | None = None,
) -> dict:
    """Fetch fold state from the most recent tick in a range.

    For ``--ticks 0:3``, returns the fold snapshot from tick 0 (most recent).
    The range metadata captures all ticks for header rendering.
    """
    from engine import vertex_tick_fold

    ticks_newest = _load_ticks_newest(vertex_path, since)

    if not ticks_newest:
        return {
            "fold_state": None,
            "_tick_error": "No ticks in the given time range",
        }

    end = min(end, len(ticks_newest))
    if start >= end or start < 0:
        return {
            "fold_state": None,
            "_tick_error": f"Tick range {start}:{end} out of range (have {len(ticks_newest)} ticks)",
        }

    selected = ticks_newest[start:end]
    # Use the most recent tick (index `start`) for fold state
    tick = selected[0]
    fold_state = vertex_tick_fold(vertex_path, tick)

    return {
        "fold_state": fold_state,
        "_tick": _tick_range_metadata(selected, start=start, end=end, total=len(ticks_newest)),
    }


# ---------------------------------------------------------------------------
# TickWindow plumbing — derive density-and-depth summaries from tick payloads.
#
# Stats pass produces an intermediate per-kind map of {key → _n}. This is the
# authoritative structure: delta computation compares current vs. previous to
# distinguish *added* (new keys) from *updated* (existing keys whose _n grew).
# Collect-folds have no per-item identity — they contribute to count-level
# deltas only; their key maps stay empty.
# ---------------------------------------------------------------------------


def _tick_payload_stats(payload: dict) -> dict:
    """Extract density and per-key item maps from a tick's fold-state payload.

    A tick payload produced by a vertex-level boundary has the shape
    ``{kind: {"items": ...}, ..., "_boundary": {...}}`` where ``items`` is
    either a dict (by-folds, keyed by the fold key) or a list (collect-folds).

    Returns a dict with:
        ``total_items``: sum of item counts across kinds
        ``total_facts``: sum of ``_n`` values across items
        ``kind_counts``: ``dict[kind, int]`` item count per kind
        ``kind_compression``: ``dict[kind, float]`` avg ``_n`` per kind
        ``ref_count``: number of items with a non-empty ``_refs`` field
        ``kind_items``: ``dict[kind, dict[key, n]]`` — per-kind, per-key ``_n``.
            Empty dict for collect-folds. Used by delta computation.
    """
    total_items = 0
    total_facts = 0
    ref_count = 0
    kind_counts: dict[str, int] = {}
    kind_compression: dict[str, float] = {}
    kind_items: dict[str, dict[str, int]] = {}

    for kind, kind_data in payload.items():
        if kind.startswith("_"):
            continue
        if not isinstance(kind_data, dict):
            continue

        items_raw = kind_data.get("items")
        if items_raw is None:
            continue

        per_key_n: dict[str, int] = {}
        items_list: list
        if isinstance(items_raw, dict):
            # by-fold — keyed by fold key, value is the item dict
            items_list = list(items_raw.values())
            for key, item in items_raw.items():
                if isinstance(item, dict):
                    n = item.get("_n", 1)
                    per_key_n[str(key)] = n if isinstance(n, int) else 1
                else:
                    # Defensive — by-fold values are always dicts in practice
                    # (payload + _n). This branch catches malformed payloads
                    # from legacy data or round-trip encoding drift without
                    # crashing the whole derivation.
                    per_key_n[str(key)] = 1
        elif isinstance(items_raw, list):
            # collect-fold — no keying, no per-item identity
            items_list = items_raw
        else:
            continue

        count = len(items_list)
        kind_counts[kind] = count
        total_items += count
        kind_items[kind] = per_key_n

        n_sum = 0
        for item in items_list:
            if isinstance(item, dict):
                n = item.get("_n", 1)
                n_sum += n if isinstance(n, int) else 1
                if item.get("_refs"):
                    ref_count += 1
            else:
                n_sum += 1

        total_facts += n_sum
        if count > 0:
            kind_compression[kind] = round(n_sum / count, 1)

    return {
        "total_items": total_items,
        "total_facts": total_facts,
        "kind_counts": kind_counts,
        "kind_compression": kind_compression,
        "ref_count": ref_count,
        "kind_items": kind_items,
    }


def _tick_delta(
    current: dict,
    previous: dict,
) -> tuple[int, int, dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Compute added / updated deltas between two ``_tick_payload_stats`` results.

    Returns ``(delta_added, delta_updated, added_keys, updated_keys)``:
        - ``delta_added``: total new items across all kinds. For by-folds this
          counts newly-keyed entries; for collect-folds it counts item-count
          growth (since there is no key identity).
        - ``delta_updated``: total keys whose ``_n`` grew. By-folds only
          (collect-folds contribute 0).
        - ``added_keys``: per-kind tuples of newly-added keys (sorted). Empty
          for collect-folds and for kinds with no new keys.
        - ``updated_keys``: per-kind tuples of keys whose ``_n`` grew (sorted).
          Empty for collect-folds and for kinds with no growth.
    """
    curr_items = current["kind_items"]
    prev_items = previous["kind_items"]
    curr_counts = current["kind_counts"]
    prev_counts = previous["kind_counts"]

    added_keys: dict[str, tuple[str, ...]] = {}
    updated_keys: dict[str, tuple[str, ...]] = {}

    by_added_total = 0
    by_updated_total = 0
    collect_added = 0

    all_kinds = set(curr_counts) | set(prev_counts) | set(curr_items) | set(prev_items)
    for kind in all_kinds:
        curr = curr_items.get(kind, {})
        prev = prev_items.get(kind, {})

        # by-fold signature: non-empty per-key map on either side
        if curr or prev:
            new = tuple(sorted(k for k in curr if k not in prev))
            grew = tuple(
                sorted(k for k in curr if k in prev and curr[k] > prev[k])
            )
            if new:
                added_keys[kind] = new
                by_added_total += len(new)
            if grew:
                updated_keys[kind] = grew
                by_updated_total += len(grew)
            continue

        # collect-fold signature: kind present but kind_items empty on both
        # sides. Added count comes from item-count growth.
        growth = curr_counts.get(kind, 0) - prev_counts.get(kind, 0)
        if growth > 0:
            collect_added += growth

    return (
        by_added_total + collect_added,
        by_updated_total,
        added_keys,
        updated_keys,
    )


def fetch_tick_windows(
    vertex_path: Path,
    *,
    name: str | None = None,
    since: str | None = "30d",
    all_names: bool = False,
) -> "tuple[TickWindow, ...]":
    """Build ``TickWindow`` objects for a vertex's recent ticks.

    When *name* is None or empty, resolves to the vertex name — the tick
    series produced by the vertex-level boundary. Otherwise filters to
    the named loop's tick series.

    *all_names* spans EVERY tick series in the store (no name filter) —
    the full hash chain, which links all appended ticks regardless of
    name (genesis/rebirth ticks carry a different name than the vertex
    boundary series, so the name filter would silently drop them). This
    is what ``store ticks --chain`` needs to agree with ``store verify``.
    Because cross-series adjacency is not a real delta, ``delta_*`` are
    zeroed when *all_names* is set — they are a same-series concept.
    *all_names* takes precedence over *name*.

    *since* is a duration window (``"30d"``, ``"24h"``); pass ``None`` for
    the full history (all ticks from epoch). The attestation-chain read
    (``store ticks --chain``) wants the whole chain — genesis and the
    legacy-era boundary are exactly the interesting cases — not a recent
    slice.

    Returns newest-first. ``delta_*`` on index *i* compares against index
    *i + 1* (the next-older tick). The oldest tick in the returned slice
    has zero deltas by construction.
    """
    from atoms import TickWindow
    from engine import vertex_ticks
    from lang import parse_vertex_file

    if all_names:
        name = None  # no filter — span the full chain across every series
    elif not name:
        ast = parse_vertex_file(vertex_path)
        name = ast.name

    now = datetime.now(timezone.utc)
    if since is None:
        since_ts = 0.0
    else:
        since_ts = (now - timedelta(seconds=_parse_duration(since))).timestamp()

    pairs = vertex_ticks(
        vertex_path, since_ts, now.timestamp(), name=name, with_envelope=True
    )
    pairs_newest = list(reversed(pairs))  # newest first
    ticks_newest = [t for t, _ in pairs_newest]
    envelopes_newest = [e for _, e in pairs_newest]

    # One stats pass per tick, reused for density fields and delta comparison.
    payload_stats = [
        _tick_payload_stats(
            tick.payload if isinstance(tick.payload, dict) else {}
        )
        for tick in ticks_newest
    ]

    windows: list[TickWindow] = []
    for i, tick in enumerate(ticks_newest):
        stats = payload_stats[i]

        ts_epoch = tick.ts.timestamp()
        since_epoch = tick.since.timestamp() if tick.since else None
        duration = (ts_epoch - since_epoch) if since_epoch is not None else None

        payload = tick.payload if isinstance(tick.payload, dict) else {}
        boundary = payload.get("_boundary", {}) or {}
        observer = str(boundary.get("name", ""))
        status = str(boundary.get("status", ""))
        trigger = f"{observer} {status}".strip() if observer else ""

        if all_names:
            # Cross-series adjacency is not a meaningful delta — zero it.
            delta_added, delta_updated, added, updated = 0, 0, {}, {}
        elif i + 1 < len(payload_stats):
            delta_added, delta_updated, added, updated = _tick_delta(
                stats, payload_stats[i + 1],
            )
        else:
            delta_added, delta_updated, added, updated = 0, 0, {}, {}

        env = envelopes_newest[i]
        windows.append(TickWindow(
            index=i,
            name=tick.name,
            ts=ts_epoch,
            since=since_epoch,
            duration_secs=duration,
            observer=observer,
            boundary_trigger=trigger,
            total_items=stats["total_items"],
            total_facts=stats["total_facts"],
            kind_summary=dict(stats["kind_counts"]),
            kind_compression=dict(stats["kind_compression"]),
            ref_count=stats["ref_count"],
            delta_added=delta_added,
            delta_updated=delta_updated,
            added_keys=added,
            updated_keys=updated,
            chained=env.get("chained", False),
            signed=env.get("signed", False),
            fact_cursor=env.get("fact_cursor", ""),
            cursor_kind=env.get("cursor_kind", ""),
            cursor_preview=env.get("cursor_preview", ""),
        ))

    return tuple(windows)
