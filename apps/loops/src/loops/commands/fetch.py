"""Data retrieval — fold (collapsed state) and stream (event history).

Supports key drill-down via ``kind/key`` syntax on the ``--kind`` flag:
``--kind thread/fold-state-types`` filters to the single folded item
(fold) or facts matching the key field value (stream).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atoms import FoldItem, FoldState


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
    observer: str | None = None,
    retain_facts: bool = False,
) -> "FoldState":
    """Fetch fold state, with optional key drill-down.

    Supports ``kind/key`` syntax: ``thread/fold-state-types`` filters
    to the single item whose key field matches. The fold section is
    preserved (one item instead of many) so lenses render normally.
    """
    from atoms import FoldSection, FoldState
    from engine import vertex_fold

    kind_filter, key_filter = _split_kind_key(kind)
    state = vertex_fold(
        vertex_path, observer=observer, kind=kind_filter,
        retain_facts=retain_facts,
    )

    if key_filter is None:
        return state

    # Filter sections to items matching the key value
    # (vertex_fold(kind=kind_filter) always returns a single-kind state,
    # so all sections already have kind == kind_filter)
    filtered: list[FoldSection] = []
    for section in state.sections:
        matches = tuple(
            item for item in section.items
            if _item_matches_key(item, section.key_field, key_filter)
        )
        if matches:
            filtered.append(FoldSection(
                kind=section.kind,
                items=matches,
                sections=section.sections,
                fold_type=section.fold_type,
                key_field=section.key_field,
            ))

    return FoldState(sections=tuple(filtered), vertex=state.vertex)


def _item_matches_key(item: "FoldItem", key_field: str | None, key: str) -> bool:
    """Check if a fold item matches a key value.

    Tries key_field first, then common label fields. Case-insensitive.
    """
    candidates = [key_field] if key_field else []
    candidates.extend(["topic", "name", "title", "summary"])

    for field in candidates:
        if field and field in item.payload:
            val = str(item.payload[field])
            if val.lower() == key.lower():
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
    returns only facts whose key field payload matches. When drilling down,
    time window defaults to all history (not 7d).

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
    """Check if a raw fact's payload matches a key value."""
    payload = fact.get("payload", {})
    candidates = [key_field] if key_field else []
    candidates.extend(["topic", "name", "title", "summary"])

    for field in candidates:
        if field and field in payload:
            val = str(payload[field])
            if val.lower() == key.lower():
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
