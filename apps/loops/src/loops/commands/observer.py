"""Observer commands — fold (collapsed state) and stream (event history)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _observer() -> str:
    """Read observer from LOOPS_OBSERVER env var."""
    return os.environ.get("LOOPS_OBSERVER", "")


def _emit_fact(store_path: Path, kind: str, observer: str, payload: dict) -> None:
    """Emit a fact into a store."""
    from atoms import Fact
    from engine import SqliteStore

    ts = datetime.now(timezone.utc).timestamp()
    fact = Fact(kind=kind, ts=ts, payload=payload, observer=observer, origin="")

    store_path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteStore(
        path=store_path, serialize=Fact.to_dict, deserialize=Fact.from_dict
    ) as store:
        store.append(fact)


def _resolve_local_vertex() -> Path:
    """Find a vertex file via local cwd or LOOPS_HOME fallback.

    Resolution order:
    1. Local vertex in cwd (*.vertex)
    2. LOOPS_HOME/session/session.vertex

    Raises FileNotFoundError if neither found.
    """
    from loops.main import _find_local_vertex, loops_home

    # 1. Local vertex in cwd
    local = _find_local_vertex()
    if local is not None:
        return local

    # 2. LOOPS_HOME session fallback
    session_vertex = loops_home() / "session" / "session.vertex"
    if session_vertex.exists():
        return session_vertex

    raise FileNotFoundError(
        "No vertex found. Run 'loops init --template session' or 'loops emit <kind> ...' first."
    )


def _parse_duration(s: str) -> float:
    """Parse duration string like '7d', '24h', '1h' to seconds."""
    m = re.match(r"^(\d+)([dhms])$", s)
    if not m:
        raise ValueError(f"Invalid duration: {s!r} (expected e.g. '7d', '24h', '1h')")
    value = int(m.group(1))
    unit = m.group(2)
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return value * multipliers[unit]


def _format_date(ts) -> str:
    """Format timestamp as short date (e.g. 'Feb 27')."""
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return ts[:10] if len(ts) >= 10 else ts
    elif isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        return "?"
    return f"{dt.strftime('%b')} {dt.day}"


def fetch_fold(vertex_path: Path, kind: str | None = None) -> dict:
    """Fetch fold state driven entirely by vertex declaration.

    No per-kind extractors. The fold declaration's key_field IS the
    display key. fold_type (by/collect) IS the rendering strategy.

    Returns ``{"sections": [...], "vertex": str}`` where each section is::

        {"kind": str, "items": list[dict], "fold_type": "by"|"collect",
         "key_field": str|None, "count": int}
    """
    from engine import vertex_read
    from lang import parse_vertex_file
    from lang.ast import FoldBy, FoldCollect

    ast = parse_vertex_file(vertex_path)
    fold_state = vertex_read(vertex_path)

    active = {kind} if kind else set(fold_state.keys())

    sections: list[dict] = []
    for kind_name in sorted(active):
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

        # Normalize items to list[dict] regardless of fold type
        if fold_type == "by" and isinstance(items_raw, dict):
            items = [dict(v) for v in items_raw.values()]
        elif isinstance(items_raw, list):
            items = [dict(v) for v in items_raw]
        else:
            items = [dict(items_raw)] if items_raw else []

        sections.append({
            "kind": kind_name,
            "items": items,
            "fold_type": fold_type,
            "key_field": key_field,
            "count": len(items),
        })

    return {"sections": sections, "vertex": ast.name}


def fetch_stream(
    vertex_path: Path,
    *,
    query: str | None = None,
    kind: str | None = None,
    since: str | None = None,
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
            vertex_path, query, kind=kind, since=since_ts, limit=100
        )
    else:
        facts = vertex_facts(vertex_path, since_ts, now.timestamp(), kind=kind)

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

def fetch_status(vertex_path: Path, kind: str | None = None) -> dict:
    """Legacy alias — delegates to fetch_fold."""
    return fetch_fold(vertex_path, kind=kind)


def fetch_log(vertex_path: Path, since: str, kind: str | None) -> list[dict]:
    """Legacy alias — delegates to fetch_stream, returns facts list."""
    result = fetch_stream(vertex_path, kind=kind, since=since)
    return result["facts"]
