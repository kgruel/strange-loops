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
    """Fetch fold state — thin wrapper around engine's vertex_fold.

    The typed FoldState contract (declaration order, fold metadata,
    FoldItem with separated payload/metadata) is computed entirely
    by the engine. This function exists as the CLI's fetch entry point.
    """
    from engine import vertex_fold

    return vertex_fold(vertex_path, observer=observer, kind=kind)


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
