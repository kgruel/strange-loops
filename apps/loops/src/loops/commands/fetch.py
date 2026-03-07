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
) -> "FoldState":
    """Fetch fold state, with optional key drill-down.

    Supports ``kind/key`` syntax: ``thread/fold-state-types`` filters
    to the single item whose key field matches. The fold section is
    preserved (one item instead of many) so lenses render normally.
    """
    from atoms import FoldSection, FoldState
    from engine import vertex_fold

    kind_filter, key_filter = _split_kind_key(kind)
    state = vertex_fold(vertex_path, observer=observer, kind=kind_filter)

    if key_filter is None:
        return state

    # Filter sections to items matching the key value
    filtered: list[FoldSection] = []
    for section in state.sections:
        if section.kind != kind_filter:
            continue
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
