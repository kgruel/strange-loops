"""Local store commands — status and log."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
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


def fetch_status(vertex_path: Path, kind: str | None = None) -> dict:
    """Fetch status data by replaying facts through vertex-declared folds.

    The vertex declaration drives the read: each declared kind's fold is
    compiled and replayed over stored facts.  The set of kinds comes from
    the vertex declaration (via vertex_read), not a hardcoded list.

    When *kind* is given, only that section is populated.

    Returns ``{"sections": [...]}`` where each section is::

        {"kind": str, "items": list[dict], "fold_type": "by"|"collect"}

    Known kinds (decision, thread, task, change) get field-specific
    extraction for richer rendering.  All other kinds get generic
    extraction (full payload passed through).
    """
    from engine import vertex_read

    fold_state = vertex_read(vertex_path)

    active = {kind} if kind else set(fold_state.keys())

    # --- known-kind extractors (preserve existing rendering) -----------

    def _extract_decision(items_dict: dict) -> list[dict]:
        return [
            {"topic": v.get("topic", ""), "message": v.get("message", ""), "ts": v.get("_ts", "")}
            for v in items_dict.values()
        ]

    def _extract_thread(items_dict: dict) -> list[dict]:
        return [
            {"name": v.get("name", ""), "status": v.get("status", ""), "ts": v.get("_ts", "")}
            for v in items_dict.values()
            if v.get("status") != "resolved"
        ]

    def _extract_task(items_dict: dict) -> list[dict]:
        return [
            {"name": v.get("name", ""), "status": v.get("status", ""), "summary": v.get("summary", ""), "ts": v.get("_ts", "")}
            for v in items_dict.values()
        ]

    def _extract_change(items: list | dict) -> list[dict]:
        vals = items if isinstance(items, list) else items.values()
        return list(reversed([
            {"summary": v.get("summary", ""), "files": v.get("files", ""), "ts": v.get("_ts", "")}
            for v in vals
        ]))

    _known_extractors: dict[str, tuple[str, object]] = {
        "decision": ("by", _extract_decision),
        "thread": ("by", _extract_thread),
        "task": ("by", _extract_task),
        "change": ("collect", _extract_change),
    }

    def _extract_generic(items: list | dict) -> list[dict]:
        """Pass through full payload for unknown kinds."""
        if isinstance(items, dict):
            return [dict(v) for v in items.values()]
        return [dict(v) for v in items]

    # --- build sections ------------------------------------------------

    sections: list[dict] = []
    for kind_name in sorted(active):
        state = fold_state.get(kind_name, {})
        items_raw = state.get("items", state)

        if kind_name in _known_extractors:
            fold_type, extractor = _known_extractors[kind_name]
            extracted = extractor(items_raw)
        else:
            fold_type = "by" if isinstance(items_raw, dict) else "collect"
            extracted = _extract_generic(items_raw)

        if kind_name not in active:
            continue

        sections.append({
            "kind": kind_name,
            "items": extracted,
            "fold_type": fold_type,
        })

    # --- backwards compat: also return legacy keys ---------------------

    legacy: dict = {
        "decisions": [], "threads": [], "tasks": [], "changes": [],
        "sections": sections,
    }
    for sec in sections:
        k = sec["kind"]
        if k == "decision":
            legacy["decisions"] = sec["items"]
        elif k == "thread":
            legacy["threads"] = sec["items"]
        elif k == "task":
            legacy["tasks"] = sec["items"]
        elif k == "change":
            legacy["changes"] = sec["items"]
    return legacy


def fetch_log(vertex_path: Path, since: str, kind: str | None) -> list[dict]:
    """Fetch log facts from a vertex's store within a time range."""
    from engine import vertex_facts

    duration_secs = _parse_duration(since)
    now = datetime.now(timezone.utc)
    since_ts = now.timestamp() - duration_secs

    facts = vertex_facts(vertex_path, since_ts, now.timestamp(), kind=kind)
    facts.sort(key=lambda f: f["ts"], reverse=True)

    # Normalize timestamps for JSON serialization
    for f in facts:
        if isinstance(f["ts"], datetime):
            f["ts"] = f["ts"].isoformat()

    return facts
