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


def _resolve_local_store() -> Path:
    """Find store via local vertex or LOOPS_HOME fallback.

    Resolution order:
    1. Local vertex in cwd (*.vertex)
    2. LOOPS_HOME/session/session.vertex

    Raises FileNotFoundError if neither found.
    """
    from loops.main import _find_local_vertex, _resolve_vertex_store_path, loops_home

    # 1. Local vertex in cwd
    local = _find_local_vertex()
    if local is not None:
        store_path = _resolve_vertex_store_path(local)
        if store_path is not None:
            return store_path

    # 2. LOOPS_HOME session fallback
    session_vertex = loops_home() / "session" / "session.vertex"
    if session_vertex.exists():
        store_path = _resolve_vertex_store_path(session_vertex)
        if store_path is not None:
            return store_path

    raise FileNotFoundError(
        "No vertex found. Run 'loops init --template session' or 'loops emit <kind> ...' first."
    )


def _latest_by_group(reader, kind: str, group_field: str) -> list[dict]:
    """Query-time fold: get recent facts, group by field, keep newest per group."""
    facts = reader.recent_facts(kind, 500)
    groups: dict[str, dict] = {}
    for fact in facts:
        key = fact["payload"].get(group_field, "")
        if key not in groups:
            groups[key] = fact
    return list(groups.values())


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


def fetch_status(store_path: Path, kind: str | None = None) -> dict:
    """Fetch status data from store. Returns dict suitable for JSON serialization.

    When *kind* is given, only that section is populated (e.g. kind="task"
    returns tasks only, other sections empty).
    """
    from engine import StoreReader

    if not store_path.exists():
        return {"decisions": [], "threads": [], "tasks": [], "changes": []}

    active = {kind} if kind else {"decision", "thread", "task", "change"}

    with StoreReader(store_path) as reader:
        decisions_raw = _latest_by_group(reader, "decision", "topic") if "decision" in active else []
        threads_raw = _latest_by_group(reader, "thread", "name") if "thread" in active else []
        threads_raw = [
            t for t in threads_raw if t["payload"].get("status") != "resolved"
        ]
        tasks_raw = _latest_by_group(reader, "task", "name") if "task" in active else []
        changes_raw = reader.recent_facts("change", 10) if "change" in active else []

    def _ts(ts):
        return ts.isoformat() if isinstance(ts, datetime) else ts

    return {
        "decisions": [
            {
                "topic": d["payload"].get("topic", ""),
                "message": d["payload"].get("message", ""),
                "ts": _ts(d["ts"]),
            }
            for d in decisions_raw
        ],
        "threads": [
            {
                "name": t["payload"].get("name", ""),
                "status": t["payload"].get("status", ""),
                "ts": _ts(t["ts"]),
            }
            for t in threads_raw
        ],
        "tasks": [
            {
                "name": t["payload"].get("name", ""),
                "status": t["payload"].get("status", ""),
                "summary": t["payload"].get("summary", ""),
                "ts": _ts(t["ts"]),
            }
            for t in tasks_raw
        ],
        "changes": [
            {
                "summary": c["payload"].get("summary", ""),
                "files": c["payload"].get("files", ""),
                "ts": _ts(c["ts"]),
            }
            for c in changes_raw
        ],
    }


def fetch_log(store_path: Path, since: str, kind: str | None) -> list[dict]:
    """Fetch log facts from store."""
    from engine import StoreReader

    if not store_path.exists():
        return []

    duration_secs = _parse_duration(since)
    now = datetime.now(timezone.utc)
    since_ts = now.timestamp() - duration_secs

    with StoreReader(store_path) as reader:
        facts = reader.facts_between(since_ts, now.timestamp(), kind=kind)

    facts.sort(key=lambda f: f["ts"], reverse=True)

    # Normalize timestamps for JSON serialization
    for f in facts:
        if isinstance(f["ts"], datetime):
            f["ts"] = f["ts"].isoformat()

    return facts


