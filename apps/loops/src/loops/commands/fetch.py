"""Data retrieval — fold (collapsed state) and stream (event history)."""

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


def fetch_fold(vertex_path: Path, kind: str | None = None, observer: str | None = None) -> FoldState:
    """Fetch fold state driven entirely by vertex declaration.

    No per-kind extractors. The fold declaration's key_field IS the
    display key. fold_type (by/collect) IS the rendering strategy.

    Returns a typed ``FoldState`` — the contract between engine computation
    and lens rendering.
    """
    from atoms import FoldItem, FoldSection, FoldState

    from engine import vertex_read
    from lang import parse_vertex_file
    from lang.ast import FoldBy, FoldCollect

    ast = parse_vertex_file(vertex_path)
    fold_state = vertex_read(vertex_path, observer=observer)

    # Declaration order from AST, not alphabetical.
    # Include kinds that have fold state OR are declared (declared-but-empty still show).
    if kind:
        ordered_kinds = [kind]
    else:
        declared = list(ast.loops.keys())
        undeclared = [k for k in fold_state if k not in ast.loops]
        ordered_kinds = declared + undeclared

    sections: list[FoldSection] = []
    for kind_name in ordered_kinds:
        state = fold_state.get(kind_name, {})
        items_raw = state.get("items", state)

        # Extract fold metadata from declaration
        # FoldDecl wraps the FoldOp — access .op for the type check
        loop_def = ast.loops.get(kind_name)
        key_field = None
        fold_type = "collect"
        if loop_def and loop_def.folds:
            fold_decl = loop_def.folds[0]
            fold_op = fold_decl.op
            if isinstance(fold_op, FoldBy):
                fold_type = "by"
                key_field = fold_op.key_field
            elif isinstance(fold_op, FoldCollect):
                fold_type = "collect"

        # Normalize items to list[dict] regardless of fold type,
        # then convert to typed FoldItems
        if fold_type == "by" and isinstance(items_raw, dict):
            raw_items = [dict(v) for v in items_raw.values()]
        elif isinstance(items_raw, list):
            raw_items = [dict(v) for v in items_raw]
        else:
            raw_items = [dict(items_raw)] if items_raw else []

        items = tuple(
            _dict_to_fold_item(d) for d in raw_items
        )

        sections.append(FoldSection(
            kind=kind_name,
            items=items,
            fold_type=fold_type,
            key_field=key_field,
        ))

    return FoldState(sections=tuple(sections), vertex=ast.name)


def _dict_to_fold_item(d: dict) -> FoldItem:
    """Convert a raw fold output dict to a typed FoldItem.

    Separates metadata (_ts, _observer, _origin) from payload.
    """
    from atoms import FoldItem

    ts = d.pop("_ts", None)
    observer = d.pop("_observer", "")
    origin = d.pop("_origin", "")
    return FoldItem(payload=d, ts=ts, observer=observer, origin=origin)


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

    Returns ``{"facts": list[dict], "fold_meta": dict, "vertex": str}``.
    """
    from engine import vertex_facts, vertex_search
    from lang import parse_vertex_file
    from lang.ast import FoldBy

    since_secs = _parse_duration(since or "7d")
    now = datetime.now(timezone.utc)
    since_ts = (now - timedelta(seconds=since_secs)).timestamp()

    if query:
        facts = vertex_search(
            vertex_path, query, kind=kind, since=since_ts, limit=100,
            observer=observer,
        )
    else:
        facts = vertex_facts(
            vertex_path, since_ts, now.timestamp(), kind=kind,
            observer=observer,
        )

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


# --- Legacy aliases for backwards compatibility ---

def fetch_status(vertex_path: Path, kind: str | None = None) -> FoldState:
    """Legacy alias — delegates to fetch_fold."""
    return fetch_fold(vertex_path, kind=kind)


def fetch_log(vertex_path: Path, since: str, kind: str | None) -> list[dict]:
    """Legacy alias — delegates to fetch_stream, returns facts list."""
    result = fetch_stream(vertex_path, kind=kind, since=since)
    return result["facts"]
