"""Local store commands — status and log."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
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


def fetch_status(store_path: Path) -> dict:
    """Fetch status data from store. Returns dict suitable for JSON serialization."""
    from engine import StoreReader

    if not store_path.exists():
        return {"decisions": [], "threads": [], "tasks": [], "changes": []}

    with StoreReader(store_path) as reader:
        decisions_raw = _latest_by_group(reader, "decision", "topic")
        threads_raw = _latest_by_group(reader, "thread", "name")
        threads_raw = [
            t for t in threads_raw if t["payload"].get("status") != "resolved"
        ]
        tasks_raw = _latest_by_group(reader, "task", "name")
        changes_raw = reader.recent_facts("change", 10)

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


def render_status(ctx, data: dict):
    """Render status data as a Block.

    Zoom levels:
    - MINIMAL: one-liner counts
    - SUMMARY: topic/name lists with dates, no message bodies
    - DETAILED: topics with message bodies
    - FULL: everything, full messages with all metadata
    """
    from painted import Block, Style, Zoom, join_vertical

    decisions = data["decisions"]
    threads = data["threads"]
    tasks = data["tasks"]
    changes = data["changes"]

    if not any([decisions, threads, tasks, changes]):
        return Block.text("No session data yet.", Style())

    zoom = ctx.zoom

    # MINIMAL: one-liner
    if zoom == Zoom.MINIMAL:
        parts = []
        if decisions:
            parts.append(f"{len(decisions)} decisions")
        if threads:
            parts.append(f"{len(threads)} threads")
        if tasks:
            parts.append(f"{len(tasks)} tasks")
        if changes:
            parts.append(f"{len(changes)} changes")
        return Block.text(", ".join(parts), Style())

    rows = []
    header_style = Style(bold=True)
    dim_style = Style(dim=True)

    if decisions:
        rows.append(Block.text(f"Decisions ({len(decisions)}):", header_style))
        for d in decisions:
            date = _format_date(d["ts"])
            if zoom >= Zoom.DETAILED:
                # Topic on its own line, message indented below
                rows.append(Block.text(f"  {d['topic']} ({date})", Style()))
                if d["message"]:
                    rows.append(Block.text(f"    {d['message']}", dim_style))
            else:
                # SUMMARY: topic + date only
                rows.append(Block.text(f"  {d['topic']} ({date})", Style()))

    if threads:
        if rows:
            rows.append(Block.text("", Style()))
        rows.append(Block.text(f"Open Threads ({len(threads)}):", header_style))
        for t in threads:
            date = _format_date(t["ts"])
            status = t.get("status", "")
            line = f"  {t['name']}: {status} ({date})" if status else f"  {t['name']} ({date})"
            rows.append(Block.text(line, Style()))

    if tasks:
        if rows:
            rows.append(Block.text("", Style()))
        rows.append(Block.text(f"Active Tasks ({len(tasks)}):", header_style))
        for t in tasks:
            date = _format_date(t["ts"])
            if zoom >= Zoom.DETAILED and t.get("summary"):
                rows.append(Block.text(f"  {t['name']}: {t['status']} ({date})", Style()))
                rows.append(Block.text(f"    {t['summary']}", dim_style))
            else:
                rows.append(Block.text(f"  {t['name']}: {t['status']} ({date})", Style()))

    if changes:
        if rows:
            rows.append(Block.text("", Style()))
        rows.append(Block.text(f"Recent Changes ({len(changes)}):", header_style))
        for c in changes:
            date = _format_date(c["ts"])
            rows.append(Block.text(f"  {c['summary']} ({date})", Style()))
            if zoom >= Zoom.DETAILED and c.get("files"):
                rows.append(Block.text(f"    files: {c['files']}", dim_style))

    return join_vertical(*rows)


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


def _log_summary(kind: str, payload: dict) -> str:
    """Kind-aware one-line summary for a log fact.

    Instead of dumping all key=value pairs, format based on the kind
    so the output reads naturally.
    """
    topic = payload.get("topic", "")
    name = payload.get("name", "")
    summary = payload.get("summary", "")
    message = payload.get("message", "")
    status = payload.get("status", "")

    if kind == "decision":
        return f"{topic}: {message}" if message else topic or str(payload)
    if kind == "thread":
        return f"{name} [{status}]" if status else name or str(payload)
    if kind == "task":
        parts = [name]
        if status:
            parts.append(f"[{status}]")
        if summary:
            parts.append(summary)
        return " ".join(parts) if parts else str(payload)
    if kind == "change":
        return summary or str(payload)
    if kind == "notes":
        return message or str(payload)

    # Fallback: first meaningful field
    for key in ("topic", "name", "summary", "message"):
        if key in payload and payload[key]:
            return payload[key]
    return str(payload)


def render_log(ctx, facts: list[dict]):
    """Render log facts as a Block.

    Zoom levels:
    - MINIMAL: counts by kind
    - SUMMARY: time + kind + kind-aware summary (no key= prefixes)
    - DETAILED: summary + secondary fields on next line
    - FULL: all payload fields
    """
    from painted import Block, Style, Zoom, join_vertical

    if not facts:
        return Block.text("No facts in the given time range.", Style())

    zoom = ctx.zoom

    # MINIMAL: just counts
    if zoom == Zoom.MINIMAL:
        counts: dict[str, int] = {}
        for f in facts:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        parts = [f"{count} {kind}" for kind, count in counts.items()]
        return Block.text(", ".join(parts), Style())

    rows = []
    dim_style = Style(dim=True)
    current_date = None

    for f in facts:
        ts = f["ts"]
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts)
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        date_str = dt.strftime("%Y-%m-%d")
        if date_str != current_date:
            if current_date is not None:
                rows.append(Block.text("", Style()))
            rows.append(Block.text(f"{date_str}:", Style(bold=True)))
            current_date = date_str

        time_str = dt.strftime("%H:%M")
        kind_str = f["kind"]
        payload = f["payload"]

        summary = _log_summary(kind_str, payload)
        rows.append(Block.text(f"  {time_str} [{kind_str}] {summary}", Style()))

        # DETAILED+: show secondary fields on next line
        if zoom >= Zoom.DETAILED:
            extras = []
            if kind_str == "change" and payload.get("files"):
                extras.append(f"files: {payload['files']}")
            if kind_str == "task" and payload.get("summary"):
                extras.append(payload["summary"])
            if extras:
                for extra in extras:
                    rows.append(Block.text(f"           {extra}", dim_style))

        # FULL: dump all payload fields
        if zoom >= Zoom.FULL:
            for key, val in payload.items():
                if val:
                    rows.append(Block.text(f"           {key}: {val}", dim_style))

    return join_vertical(*rows)
