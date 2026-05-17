"""Data retrieval — fold (collapsed state) and stream (event history).

Supports key drill-down via two equivalent surfaces:

- ``--key <prefix>`` flag: ``loops read project --kind decision --key design/``
  filters to items whose key field starts with the prefix. Cross-kind operation
  supported when ``--kind`` is omitted (filters all sections by prefix).
- ``kind/key`` embedded syntax (back-compat): ``--kind thread/fold-state-types``
  is equivalent to ``--kind thread --key fold-state-types``.

Matching is prefix-based and case-insensitive — ``--key design/`` matches
``design/lens-is-the-interface``, ``design/derived-keys-as-focus-filter``, etc.
For exact match, type the full key (a unique full key matches only itself via
``.startswith()``).
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
    starts with ``design/``. For exact match, pass the full key (a unique full
    key is a prefix of only itself).

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
                ))
                if section.key_field:
                    for item in matches:
                        key_value = str(item.payload.get(section.key_field, ""))
                        surviving_source_keys.add(f"{section.kind}/{key_value}")

        # Preserve source_facts for surviving items only (drop entries whose
        # fold item was filtered out). Without this, retain_facts=True + key
        # filtering would silently drop the lifecycle data that callers like
        # fetch_trace depend on.
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
            for ref in item.refs:
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
                        for ref in titem.refs:
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


def _parse_ref_to_kind_key(ref: str) -> "tuple[str, str] | None":
    """Parse a ref string into (kind, key). Returns None if unparseable.

    Refs are stored in two forms in the wild:
    * ``kind:key`` (newer runbook convention, fully qualified) — supported
    * ``key`` only (legacy / same-kind-implied) — skipped (ambiguous)

    Trace's ``_parse_fact_refs`` uses the same rule for fact-payload refs.
    This parser is the fold-item analog — items expose their refs as
    pre-extracted strings, but the address format follows the same
    discipline. Bare-key refs lose the cross-kind dispatch info, so we
    can't safely walk them — the walk would have to guess the kind.
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
    (topic, name, title, summary). Uses ``.startswith()`` — type the full key
    to match a single item; type a prefix to match a subtree.
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
    query: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    observer: str | None = None,
) -> dict:
    """Fetch event stream with three orthogonal filters.

    Unifies log + search into a single fetch. When *query* is provided,
    uses FTS5 search; otherwise returns raw facts in reverse-chrono order.

    Supports ``kind/key`` drill-down: ``--kind thread/fold-state-types``
    returns only facts whose key field payload starts with the prefix
    (case-insensitive). When drilling down, time window defaults to all
    history (not 7d).

    Returns ``{"facts": list[dict], "fold_meta": dict, "vertex": str}``.
    """
    from engine import vertex_facts, vertex_search
    from lang import parse_vertex_file
    from lang.ast import FoldBy

    kind_filter, key_filter = _split_kind_key(kind)

    # When drilling into a specific item, default to all history
    default_since = "7d" if key_filter is None else "3650d"
    since_secs = _parse_duration(since or default_since)
    now = datetime.now(timezone.utc)
    since_ts = (now - timedelta(seconds=since_secs)).timestamp()

    if query:
        facts = vertex_search(
            vertex_path, query, kind=kind_filter, since=since_ts, limit=100,
            observer=observer,
        )
    else:
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

    return {"facts": facts, "fold_meta": fold_meta, "vertex": ast.name}


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


def _source_payload_to_fact_dict(payload: dict, kind: str) -> dict:
    """Adapt source_facts payload shape to fact-dict shape.

    ``source_facts`` entries are flat payloads with metadata under-prefixed
    (``_ts``, ``_observer``, ``_origin``, ``_id``) — see ``vertex_reader.py``
    around line 911. The ``stream_view`` lens (and most lens consumers)
    expect the nested fact-dict shape ``{kind, ts, observer, origin, id,
    payload}``. This adapter is the consumer-side boundary: it keeps the
    lens API decoupled from the engine-internal ``source_facts`` shape.

    Anchored by decision:implementation/trace-source-facts-shape-adapter.
    """
    nested_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    ts = payload.get("_ts")
    if isinstance(ts, datetime):
        ts = ts.isoformat()
    return {
        "kind": kind,
        "ts": ts,
        "observer": payload.get("_observer", ""),
        "origin": payload.get("_origin", ""),
        "id": payload.get("_id"),
        "payload": nested_payload,
    }


def fetch_trace(
    vertex_path: Path,
    kind: str,
    key: str,
    *,
    observer: str | None = None,
    refs_depth: int = 0,
) -> dict:
    """Fetch the source-fact lifecycle for one or more ``kind/key`` entities.

    Returns the same shape as ``fetch_stream``: ``{"facts": [...],
    "fold_meta": {...}, "vertex": str}``, plus a ``_trace`` metadata entry
    naming the queried kind/key. Facts are returned in **ASC** order
    (oldest first, changelog-style) — the inverse of ``fetch_stream``,
    because trace renders a single entity's lifecycle as a forward
    narrative rather than a recency-ranked log.

    Uses ``vertex_fold(retain_facts=True)`` under the hood via ``fetch_fold``
    — the same key-prefix semantics apply (``key="design/"`` matches every
    item under that namespace, exact key matches just one). When the key
    matches multiple items, all their source facts are interleaved by
    timestamp, producing a merged lifecycle view across the namespace.

    When ``refs_depth > 0``, walks the outbound ref graph: for each fact's
    ``ref`` field, follows ``kind/key`` addresses to fetch those entities'
    lifecycles too, recursing up to ``refs_depth`` hops. Each fact carries
    an ``_entity`` field marking which ``kind/key`` it belongs to, so the
    lens can group or label. Cycles are protected by a visited set keyed
    on ``kind/key`` addresses.
    """
    from lang import parse_vertex_file
    from lang.ast import FoldBy

    # Combine/discover vertices: now supported via engine retain_facts
    # walking _combined_read's per-kind payloads (vertex_reader.py
    # _populate_source_facts). No special-case needed at the consumer.

    # Fold metadata for the lens (key_field per kind) — used during ref walk
    # too, to derive the per-entity address for each source fact.
    ast = parse_vertex_file(vertex_path)
    fold_meta: dict[str, dict] = {}
    for k, loop_def in ast.loops.items():
        kf = None
        if loop_def.folds:
            fold_decl = loop_def.folds[0]
            if isinstance(fold_decl.op, FoldBy):
                kf = fold_decl.op.key_field
        fold_meta[k] = {"key_field": kf}

    facts: list[dict] = []
    visited: set[str] = set()
    # Frontier holds (kind, key) pairs to walk in the next hop. Initial
    # frontier is the primary entity, regardless of whether key is a
    # full match or a prefix — we expand it via fetch_fold's filter.
    frontier: list[tuple[str, str]] = [(kind, key)]

    # Walk up to refs_depth + 1 layers (primary + N hops of refs).
    layers = refs_depth + 1
    for hop in range(layers):
        next_frontier: list[tuple[str, str]] = []
        for ent_kind, ent_key in frontier:
            for fact, fact_refs in _fetch_entity_facts(
                vertex_path, ent_kind, ent_key, observer=observer,
                visited=visited,
            ):
                facts.append(fact)
                # On non-final hops, refs become next frontier (deduped via visited)
                if hop < layers - 1:
                    for ref_kind, ref_key in fact_refs:
                        addr = f"{ref_kind}/{ref_key}"
                        if addr in visited:
                            continue
                        next_frontier.append((ref_kind, ref_key))
        frontier = next_frontier
        if not frontier:
            break

    # ASC ordering — oldest first (changelog-style). Tie-break by id to keep
    # deterministic order across calls.
    facts.sort(key=lambda f: (f["ts"] or "", f.get("id") or ""))

    return {
        "facts": facts,
        "fold_meta": fold_meta,
        "vertex": ast.name,
        "_trace": {"kind": kind, "key": key, "refs_depth": refs_depth},
    }


def _fetch_entity_facts(
    vertex_path: Path,
    kind: str,
    key: str,
    *,
    observer: str | None,
    visited: set[str],
) -> "list[tuple[dict, list[tuple[str, str]]]]":
    """Fetch source facts for one entity address; collect outbound refs.

    Returns a list of (fact_dict, ref_addresses) tuples. Each fact dict
    carries an ``_entity`` field with the matched ``kind/key``. Marks each
    matched entity address as visited (prevents cycles and re-fetches).
    """
    state = fetch_fold(
        vertex_path, kind=kind, key=key,
        observer=observer, retain_facts=True,
    )

    results: list[tuple[dict, list[tuple[str, str]]]] = []
    for section in state.sections:
        kf = section.key_field
        if not kf:
            continue
        for item in section.items:
            key_value = str(item.payload.get(kf, ""))
            addr = f"{section.kind}/{key_value}"
            if addr in visited:
                continue
            visited.add(addr)
            source_key = addr
            for p in state.source_facts.get(source_key, []):
                fact = _source_payload_to_fact_dict(p, section.kind)
                fact["_entity"] = addr
                refs = _parse_fact_refs(fact["payload"].get("ref"))
                results.append((fact, refs))
    return results


def _parse_fact_refs(value: object) -> "list[tuple[str, str]]":
    """Parse a fact's ``ref`` field into a list of (kind, key) tuples.

    Refs are written as ``kind:key`` (e.g. ``decision:design/foo``) — colon
    separates kind from key, key itself may contain slashes (namespace
    prefixes like ``design/``). This is the runbook convention and the
    same shape that ``_resolve_entity_refs`` resolves at emit time.

    Accepts the comma-separated string form (``kind:key,kind:key``) and
    the list form (already split). Items lacking a ``:`` separator are
    skipped — they aren't well-formed entity addresses.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts = [str(v).strip() for v in value]
    else:
        parts = [r.strip() for r in str(value).split(",")]
    out: list[tuple[str, str]] = []
    for p in parts:
        if not p or ":" not in p:
            continue
        k, v = p.split(":", 1)
        out.append((k, v))
    return out


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
        })

    return {"ticks": tick_dicts, "vertex": ast.name}


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


def _load_ticks_newest(vertex_path: Path, since: str | None = None):
    """Load ticks newest-first from a vertex store."""
    from engine import vertex_ticks

    since_secs = _parse_duration(since or "30d")
    now = datetime.now(timezone.utc)
    since_ts = (now - timedelta(seconds=since_secs)).timestamp()

    ticks = vertex_ticks(vertex_path, since_ts, now.timestamp())
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

    ticks_newest = _load_ticks_newest(vertex_path, since)

    if tick_index < 0 or tick_index >= len(ticks_newest):
        return {
            "facts": [], "fold_meta": {}, "vertex": "",
            "_tick_error": f"Tick index {tick_index} out of range (have {len(ticks_newest)} ticks)",
        }

    tick = ticks_newest[tick_index]

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
    boundary = tick.payload.get("_boundary", {}) if isinstance(tick.payload, dict) else {}

    return {
        "facts": facts,
        "fold_meta": _get_fold_meta(vertex_path),
        "vertex": ast.name,
        "_tick": {
            "name": tick.name,
            "ts": tick.ts.isoformat(),
            "since": tick.since.isoformat() if tick.since else None,
            "boundary": boundary,
            "index": tick_index,
            "total": len(ticks_newest),
        },
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


def _tick_metadata(tick, *, index: int, total: int) -> dict:
    """Build tick metadata dict for a single tick."""
    boundary = tick.payload.get("_boundary", {}) if isinstance(tick.payload, dict) else {}
    return {
        "name": tick.name,
        "ts": tick.ts.isoformat(),
        "since": tick.since.isoformat() if tick.since else None,
        "boundary": boundary,
        "index": index,
        "total": total,
    }


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

    ticks_newest = _load_ticks_newest(vertex_path, since)

    if tick_index < 0 or tick_index >= len(ticks_newest):
        return {
            "fold_state": None,
            "_tick_error": f"Tick index {tick_index} out of range (have {len(ticks_newest)} ticks)",
        }

    tick = ticks_newest[tick_index]
    fold_state = vertex_tick_fold(vertex_path, tick)

    return {
        "fold_state": fold_state,
        "_tick": _tick_metadata(tick, index=tick_index, total=len(ticks_newest)),
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
    since: str = "30d",
) -> "tuple[TickWindow, ...]":
    """Build ``TickWindow`` objects for a vertex's recent ticks.

    When *name* is None or empty, resolves to the vertex name — the tick
    series produced by the vertex-level boundary. Otherwise filters to
    the named loop's tick series.

    Returns newest-first. ``delta_*`` on index *i* compares against index
    *i + 1* (the next-older tick). The oldest tick in the returned slice
    has zero deltas by construction.
    """
    from atoms import TickWindow
    from engine import vertex_ticks
    from lang import parse_vertex_file

    if not name:
        ast = parse_vertex_file(vertex_path)
        name = ast.name

    since_secs = _parse_duration(since)
    now = datetime.now(timezone.utc)
    since_ts = (now - timedelta(seconds=since_secs)).timestamp()

    ticks = vertex_ticks(vertex_path, since_ts, now.timestamp(), name=name)
    ticks_newest = list(reversed(ticks))  # newest first

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

        if i + 1 < len(payload_stats):
            delta_added, delta_updated, added, updated = _tick_delta(
                stats, payload_stats[i + 1],
            )
        else:
            delta_added, delta_updated, added, updated = 0, 0, {}, {}

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
        ))

    return tuple(windows)
