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
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{dt.strftime('%b')} {dt.day}"


def _print_status(store_path: Path, *, use_json: bool) -> int:
    """Print session status from store."""
    from engine import StoreReader

    if not store_path.exists():
        if use_json:
            print(
                json.dumps(
                    {"decisions": [], "threads": [], "tasks": [], "changes": []}
                )
            )
        else:
            print("No session data yet.")
        return 0

    with StoreReader(store_path) as reader:
        decisions = _latest_by_group(reader, "decision", "topic")
        threads_all = _latest_by_group(reader, "thread", "name")
        threads = [
            t for t in threads_all if t["payload"].get("status") != "resolved"
        ]
        tasks = _latest_by_group(reader, "task", "name")
        changes = reader.recent_facts("change", 10)

    if use_json:
        def _ts(ts):
            return ts.isoformat() if isinstance(ts, datetime) else ts

        print(
            json.dumps(
                {
                    "decisions": [
                        {
                            "topic": d["payload"].get("topic", ""),
                            "message": d["payload"].get("message", ""),
                            "ts": _ts(d["ts"]),
                        }
                        for d in decisions
                    ],
                    "threads": [
                        {
                            "name": t["payload"].get("name", ""),
                            "status": t["payload"].get("status", ""),
                            "ts": _ts(t["ts"]),
                        }
                        for t in threads
                    ],
                    "tasks": [
                        {
                            "name": t["payload"].get("name", ""),
                            "status": t["payload"].get("status", ""),
                            "summary": t["payload"].get("summary", ""),
                            "ts": _ts(t["ts"]),
                        }
                        for t in tasks
                    ],
                    "changes": [
                        {
                            "summary": c["payload"].get("summary", ""),
                            "files": c["payload"].get("files", ""),
                            "ts": _ts(c["ts"]),
                        }
                        for c in changes
                    ],
                },
                indent=2,
                default=str,
            )
        )
        return 0

    has_output = False

    if decisions:
        print(f"Decisions ({len(decisions)}):")
        for d in decisions:
            topic = d["payload"].get("topic", "?")
            msg = d["payload"].get("message", "")
            date = _format_date(d["ts"])
            print(f"  {topic}: {msg} ({date})")
        has_output = True

    if threads:
        if has_output:
            print()
        print(f"Open Threads ({len(threads)}):")
        for t in threads:
            name = t["payload"].get("name", "?")
            msg = t["payload"].get("message", "")
            date = _format_date(t["ts"])
            line = f"  {name}: {msg} ({date})" if msg else f"  {name} ({date})"
            print(line)
        has_output = True

    if tasks:
        if has_output:
            print()
        print(f"Active Tasks ({len(tasks)}):")
        for t in tasks:
            name = t["payload"].get("name", "?")
            status = t["payload"].get("status", "")
            date = _format_date(t["ts"])
            print(f"  {name}: {status} ({date})")
        has_output = True

    if changes:
        if has_output:
            print()
        print(f"Recent Changes ({len(changes)}):")
        for c in changes:
            summary = c["payload"].get("summary", "")
            date = _format_date(c["ts"])
            print(f"  {summary} ({date})")
        has_output = True

    if not has_output:
        print("No session data yet.")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show local store status."""
    try:
        store_path = _resolve_local_store()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return _print_status(store_path, use_json=getattr(args, "json", False))


def cmd_log(args: argparse.Namespace) -> int:
    """Show recent facts from local store."""
    from engine import StoreReader

    try:
        store_path = _resolve_local_store()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not store_path.exists():
        print("No facts yet.")
        return 0

    try:
        duration_secs = _parse_duration(getattr(args, "since", "7d"))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    since_ts = now.timestamp() - duration_secs
    kind = getattr(args, "kind", None)
    use_json = getattr(args, "json", False)

    with StoreReader(store_path) as reader:
        facts = reader.facts_between(since_ts, now.timestamp(), kind=kind)

    # Reverse chronological
    facts.sort(key=lambda f: f["ts"], reverse=True)

    if use_json:
        for f in facts:
            f_out = dict(f)
            if isinstance(f_out["ts"], datetime):
                f_out["ts"] = f_out["ts"].isoformat()
            print(json.dumps(f_out, default=str))
        return 0

    # Group by date
    current_date = None
    for f in facts:
        ts = f["ts"]
        if isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        date_str = dt.strftime("%Y-%m-%d")
        if date_str != current_date:
            if current_date is not None:
                print()
            print(f"{date_str}:")
            current_date = date_str

        time_str = dt.strftime("%H:%M")
        kind_str = f["kind"]
        payload = f["payload"]

        # Format payload summary
        parts = []
        for key in ("topic", "name", "summary", "message", "status", "files"):
            if key in payload and payload[key]:
                parts.append(f"{key}={payload[key]}")
        summary = " ".join(parts) if parts else str(payload)

        print(f"  {time_str} [{kind_str}] {summary}")

    if not facts:
        print("No facts in the given time range.")

    return 0
