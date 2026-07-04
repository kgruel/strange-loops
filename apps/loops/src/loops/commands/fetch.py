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


def _split_kind_key(kind: str | None) -> tuple[str | None, str | None]:
    """Split ``kind/key`` into (kind, key). Plain kind returns (kind, None)."""
    if kind is None:
        return None, None
    if "/" in kind:
        k, v = kind.split("/", 1)
        return k, v
    return kind, None


def _get_key_field(vertex_path: Path, kind: str) -> str | None:
    """Look up the key field for a kind from the vertex's fold declarations."""
    from lang import parse_vertex_file
    from lang.ast import FoldBy

    ast = parse_vertex_file(vertex_path)
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
) -> dict:
    """Fetch the temporal event stream (raw facts, reverse-chrono).

    Content search is NOT here anymore — it re-bound onto ``read --match`` (the
    Surface ``search()`` transform, S5). This is the pure temporal-query path:
    raw facts in a time window, optionally narrowed by ``kind``/``observer``.

    Supports ``kind/key`` drill-down: ``--kind thread/fold-state-types``
    returns only facts whose key field payload starts with the prefix
    (case-insensitive). When drilling down, time window defaults to all
    history (not 7d).

    Returns ``{"facts": list[dict], "fold_meta": dict, "vertex": str}``.
    """
    from engine import vertex_facts
    from lang import parse_vertex_file
    from lang.ast import FoldBy

    kind_filter, key_filter = _split_kind_key(kind)

    # When drilling into a specific item, default to all history
    default_since = "7d" if key_filter is None else "3650d"
    since_secs = _parse_duration(since or default_since)
    now = datetime.now(timezone.utc)
    since_ts = (now - timedelta(seconds=since_secs)).timestamp()

    facts = vertex_facts(
        vertex_path, since_ts, now.timestamp(), kind=kind_filter,
        observer=observer,
    )

    # Key drill-down: filter facts by payload key field value
    if key_filter is not None:
        key_field = _get_key_field(vertex_path, kind_filter) if kind_filter else None
        facts = [
            f for f in facts
            if _fact_matches_key(f, key_field, key_filter)
        ]

    facts.sort(key=lambda f: f["ts"], reverse=True)

    # Normalize timestamps for JSON serialization
    for f in facts:
        if isinstance(f["ts"], datetime):
            f["ts"] = f["ts"].isoformat()

    # Get fold declarations for rendering hints
    ast = parse_vertex_file(vertex_path)
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
) -> dict:
    """Fetch tick history from a vertex's store.

    Returns ``{"ticks": list[dict], "vertex": str}``.
    Each tick dict has: name, ts, since, origin, payload, fact_count, kind_counts.
    Ticks are returned newest-first.
    """
    from engine import vertex_ticks
    from lang import parse_vertex_file

    since_secs = _parse_duration(since or "30d")
    now = datetime.now(timezone.utc)
    since_ts = (now - timedelta(seconds=since_secs)).timestamp()

    ticks = vertex_ticks(vertex_path, since_ts, now.timestamp())

    ast = parse_vertex_file(vertex_path)
    fold_meta = _get_fold_meta(vertex_path)

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

    from loops.surface import tier_max

    ast = parse_vertex_file(vertex_path)
    fold_meta = _get_fold_meta(vertex_path)
    now = datetime.now(timezone.utc).timestamp()
    facts = vertex_facts(vertex_path, 0.0, now, kind=kind, observer=observer)

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
# guard (a back-edge to an ancestor is skipped), so this only protects Python's
# call stack against a pathologically long SIMPLE path. It is deliberately well
# above realistic chain lengths (the live project vertex tops out near 60) so it
# never truncates a real chain — a lower bound would make results order-dependent
# (a node first reached past the cap would memoize a truncated path and poison
# every later reuse), which is exactly what "longest chain" must not do. The
# design entry's provisional "32" was a pre-implementation guess that predated
# seeing real chain depths (judgment call, flagged in the build report).
_CHAIN_DEPTH_CAP = 128


def _longest_chains(
    adjacency: dict[str, list[tuple[str, str]]], *, cap: int = _CHAIN_DEPTH_CAP
) -> dict[str, list[str]]:
    """Longest downstream chain starting at each node — memoized DFS.

    ``adjacency`` maps source address → [(target address, predicate), ...] over
    the RESOLVED graph (targets that exist as nodes). Refs point temporally
    backward so the graph is a near-DAG; a per-path ``stack`` guard skips
    back-edges (a target already on the current path — a cycle) so a cyclic
    fixture never recurses forever. ``cap`` bounds live recursion depth as a
    safety valve (see the module constant) — set high enough that realistic
    chains are never truncated, so the result is a true longest path.

    Returns node → the address path (including the node) of its longest chain.
    Neighbours are walked in sorted order and ties break lexicographically, so
    the result is deterministic. Memoization is DAG-safe: a skipped edge only
    ever points at an ancestor (a cycle), so a node's longest downstream path is
    independent of the path that reached it.
    """
    memo: dict[str, list[str]] = {}

    def dfs(node: str, stack: set[str]) -> list[str]:
        if node in memo:
            return memo[node]
        best: list[str] = [node]
        stack.add(node)
        if len(stack) < cap:
            targets = sorted({t for t, _ in adjacency.get(node, ())})
            for tgt in targets:
                if tgt in stack:
                    continue  # back-edge — would close a cycle
                sub = dfs(tgt, stack)
                cand = [node, *sub]
                if len(cand) > len(best) or (
                    len(cand) == len(best) and cand < best
                ):
                    best = cand
        stack.discard(node)
        memo[node] = best
        return best

    for n in adjacency:
        dfs(n, set())
    return memo


def _top_chains(memo: dict[str, list[str]], *, limit: int = 10) -> list[list[str]]:
    """Distinct longest chains, longest-first, dropping sub-chains of picks.

    A chain needs at least one edge (length ≥ 2). Candidates sort by
    ``(-len, path)``; a candidate that is a contiguous sub-path of an
    already-selected chain is dropped (it adds no new membership).
    """
    cands = sorted(
        (p for p in memo.values() if len(p) >= 2),
        key=lambda p: (-len(p), p),
    )

    def _is_subpath(short: list[str], long: list[str]) -> bool:
        n = len(short)
        return any(long[i : i + n] == short for i in range(len(long) - n + 1))

    picked: list[list[str]] = []
    for c in cands:
        if any(_is_subpath(c, p) for p in picked):
            continue
        picked.append(c)
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

    * **hubs** — nodes by inbound count desc; the ``←N`` sinks. Predicate mix
      (``ref`` vs declared typed-edge field names) is where typed edges become
      VISIBLE, per decision:design/graph-build1-scope.
    * **chains** — longest directed ref paths (net-new traversal; memoized DFS
      with a per-path cycle guard + depth cap 32).
    * **orphans** — nodes with no inbound AND no outbound refs/edges (isolated).

    Returns a JSON-clean dict (all counts/paths serializable; ``last`` is a
    float epoch like the confluence cut)::

        {"vertex", "nodes", "edges", "typed_edges", "orphans", "dangling",
         "hubs": [{address, kind, key, tier, inbound, predicates:[[p,n]..],
                   last, observer}, ...],
         "orphan_list": [address, ...],
         "census": [[predicate, count, typed], ...],
         "chains": [[address, ...], ...]}
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

    hubs = [
        {
            "address": r.address,
            "kind": r.kind,
            "key": r.key,
            "tier": r.tier,
            "inbound": r.inbound,
            "predicates": [[p, n] for p, n in r.inbound_predicates],
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

    chains = _top_chains(_longest_chains(outbound))

    return {
        "vertex": surface.vertex,
        "nodes": len(rows),
        "edges": resolved_edges,
        "typed_edges": typed_edges,
        "orphans": len(orphan_list),
        "dangling": dangling,
        "hubs": hubs,
        "orphan_list": orphan_list,
        "census": census_rows,
        "chains": chains,
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
    boundary is one row over the whole vertex); loops with no boundary never
    seal and are OMITTED (honest absence, decision:design/horizon-build1-scope).

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

    Returns a JSON-clean dict (``last_sealed`` is a float epoch or None)::

        {"vertex", "now", "armed": int, "total_unsealed": int,
         "last_sealed": float | None,
         "loops": [{name, scope, mode, trigger_kind, match, conditions, count,
                    last_sealed, never_sealed, window_facts, window_kinds}, ...]}
    """
    from collections import Counter

    from engine import vertex_facts
    from lang import parse_vertex_file

    ast = parse_vertex_file(vertex_path)
    now_ts = datetime.now(timezone.utc).timestamp()

    # Roster of armed loops: the vertex-level boundary (one row over every kind)
    # plus each per-loop boundary. A vertex declaring both is unusual but honest
    # — both rows render, each against its own tick series.
    armed: list[tuple[str, str, object, str | None]] = []
    if ast.boundary is not None:
        # Vertex-level: tick series is named for the vertex; window spans all
        # kinds (the seal snapshots every loop).
        armed.append((ast.name, "vertex", ast.boundary, None))
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

    # Order: vertex-level first, then per-loop by name — stable and readable.
    loops.sort(key=lambda r: (r["scope"] != "vertex", r["name"]))

    return {
        "vertex": ast.name,
        "now": now_ts,
        "armed": len(loops),
        "total_unsealed": total_unsealed,
        "last_sealed": max(seals) if seals else None,
        "loops": loops,
    }


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


def _get_fold_meta(vertex_path: Path) -> dict[str, dict]:
    """Extract fold key_field metadata from a vertex's loop declarations."""
    from lang import parse_vertex_file
    from lang.ast import FoldBy

    ast = parse_vertex_file(vertex_path)
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
    from engine import vertex_facts
    from lang import parse_vertex_file

    ticks_newest = _load_ticks_newest(vertex_path, since, with_envelope=True)

    if tick_index < 0 or tick_index >= len(ticks_newest):
        return {
            "facts": [], "fold_meta": {}, "vertex": "",
            "_tick_error": f"Tick index {tick_index} out of range (have {len(ticks_newest)} ticks)",
        }

    tick, envelope = ticks_newest[tick_index]

    # Retrieve facts in the tick's window.
    # Engine invariant: tick.since is always set to the period's first-fact
    # timestamp — the engine sets _vertex_period_start before firing a boundary.
    facts = vertex_facts(
        vertex_path,
        tick.since.timestamp(),  # type: ignore[union-attr]
        tick.ts.timestamp(),
    )

    facts.sort(key=lambda f: f["ts"], reverse=True)

    for f in facts:
        if isinstance(f["ts"], datetime):
            f["ts"] = f["ts"].isoformat()

    ast = parse_vertex_file(vertex_path)

    return {
        "facts": facts,
        "fold_meta": _get_fold_meta(vertex_path),
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
    from engine import vertex_facts
    from lang import parse_vertex_file

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

    # Union facts across all tick windows
    all_facts: list[dict] = []
    for tick in selected:
        if tick.since is not None:
            facts = vertex_facts(
                vertex_path,
                tick.since.timestamp(),
                tick.ts.timestamp(),
            )
            all_facts.extend(facts)

    # Fact IDs are ULIDs (unique per write), so no dedup needed.
    all_facts.sort(key=lambda f: f["ts"], reverse=True)

    for f in all_facts:
        if isinstance(f["ts"], datetime):
            f["ts"] = f["ts"].isoformat()

    ast = parse_vertex_file(vertex_path)

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
        "fold_meta": _get_fold_meta(vertex_path),
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
