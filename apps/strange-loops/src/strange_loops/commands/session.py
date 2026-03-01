"""Session commands — orchestration lifecycle for strange-loops."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from pathlib import Path

from strange_loops.store import (
    emit_fact,
    observer,
    parse_duration,
    require_store,
    store_path,
    tick_to_dict,
)


# -- Fetch --


def fetch_session_status(sp: Path) -> dict:
    """Fetch session status data — summary from store reader."""
    require_store(sp)

    from engine import StoreReader

    with StoreReader(sp) as reader:
        return reader.summary()


def fetch_session_log(sp: Path, duration_secs: float, kind: str | None = None) -> dict:
    """Fetch session log — facts and ticks in a time range."""
    require_store(sp)

    from engine import StoreReader

    now = datetime.now(timezone.utc)
    since_ts = now.timestamp() - duration_secs

    with StoreReader(sp) as reader:
        facts = reader.facts_between(since_ts, now.timestamp(), kind=kind)
        ticks = reader.ticks_between(since_ts, now.timestamp())

    facts.sort(key=lambda f: f["ts"])
    tick_dicts = [tick_to_dict(t) for t in ticks]

    return {"facts": facts, "ticks": tick_dicts}


# -- Rendering (painted) --


def _render_status(sp: Path) -> None:
    """Render session status via painted blocks — used by session start."""
    import shutil

    from painted import Zoom, show

    from strange_loops.lenses.session import session_status_view

    data = fetch_session_status(sp)
    width = shutil.get_terminal_size().columns
    show(session_status_view(data, Zoom.SUMMARY, width), file=sys.stdout)


# -- Commands --


def cmd_session_start(args: argparse.Namespace) -> int:
    """Start a session: emit start fact, show status."""
    sp = store_path()
    obs = observer(args)
    emit_fact(sp, "session.start", obs, {})
    _render_status(sp)
    return 0


def cmd_session_end(args: argparse.Namespace) -> int:
    """End a session: require store, emit end fact."""
    sp = store_path()
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    obs = observer(args)
    emit_fact(sp, "session.end", obs, {})
    return 0


def cmd_session_status(args: argparse.Namespace) -> int:
    """Show session status."""
    sp = store_path()
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    use_json = getattr(args, "json", False)
    if use_json:
        data = fetch_session_status(sp)
        print(json.dumps(data, indent=2, default=str))
        return 0

    _render_status(sp)
    return 0


def cmd_session_log(args: argparse.Namespace) -> int:
    """Show session log — time-range query with optional kind filter."""
    sp = store_path()
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        duration_secs = parse_duration(getattr(args, "since", "7d"))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    kind = getattr(args, "kind", None)
    use_json = getattr(args, "json", False)

    data = fetch_session_log(sp, duration_secs, kind)

    if use_json:
        # JSONL — one JSON object per entry, interleaved chronologically
        entries: list[tuple[float, str, dict]] = []
        for f in data["facts"]:
            ts = f["ts"]
            ts_val = ts.timestamp() if isinstance(ts, datetime) else ts
            entries.append((ts_val, "fact", f))
        for t in data["ticks"]:
            ts = t["ts"]
            ts_val = ts.timestamp() if isinstance(ts, datetime) else ts
            entries.append((ts_val, "tick", t))
        entries.sort(key=lambda e: e[0])

        for _, entry_type, item in entries:
            f_out = dict(item)
            if isinstance(f_out.get("ts"), datetime):
                f_out["ts"] = f_out["ts"].isoformat()
            print(json.dumps(f_out, default=str))
        return 0

    from painted import show

    from strange_loops.store import log_block

    show(log_block(data["facts"], data["ticks"]), file=sys.stdout)
    return 0


def cmd_session(args: argparse.Namespace) -> int:
    """Dispatch session subcommands."""
    dispatch = {
        "start": cmd_session_start,
        "end": cmd_session_end,
        "status": cmd_session_status,
        "log": cmd_session_log,
    }
    cmd = getattr(args, "session_command", None)
    handler = dispatch.get(cmd)
    if handler:
        return handler(args)
    print("Usage: strange-loops session {start|end|status|log}", file=sys.stderr)
    return 1
