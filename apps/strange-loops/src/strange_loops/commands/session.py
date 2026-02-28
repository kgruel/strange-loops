"""Session commands — orchestration lifecycle for strange-loops."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from pathlib import Path

from strange_loops.store import emit_fact, observer, parse_duration, require_store, store_path


def _format_ts(dt: datetime) -> str:
    """Format datetime as 'HH:MM' for log display."""
    return dt.strftime("%H:%M")


def _format_date(dt: datetime) -> str:
    """Format datetime as 'YYYY-MM-DD' for log grouping."""
    return dt.strftime("%Y-%m-%d")


# -- Rendering (painted) --


def _render_status(sp: Path) -> None:
    """Render session status via painted blocks."""
    from engine import StoreReader
    from painted import show
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    if not Path(sp).exists():
        p = current_palette()
        show(Block.text("No session data yet.", p.muted), file=sys.stdout)
        return

    with StoreReader(sp) as reader:
        stats = reader.fact_kind_stats()
        total = reader.fact_total

    p = current_palette()
    header = Block.text(f"Session — {total} facts", p.accent)

    if not stats:
        show(join_vertical(header, Block.text("  (empty)", p.muted)), file=sys.stdout)
        return

    lines = [header]
    for kind, info in sorted(stats.items()):
        count = info["count"]
        latest = info["latest"]
        age = f"latest {latest.strftime('%b %d %H:%M')}" if latest else ""
        lines.append(Block.text(f"  {kind}: {count}  {age}", p.muted))

    show(join_vertical(*lines), file=sys.stdout)


def _render_log_entry(fact: dict) -> None:
    """Render a single fact as a styled line via painted."""
    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    ts = fact["ts"]
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    time_str = _format_ts(dt)
    kind = fact["kind"]
    obs = fact.get("observer", "")
    payload = fact["payload"]

    parts = [f"{k}={v}" for k, v in payload.items() if v is not None and v != ""]
    summary = " ".join(parts)

    who = f" ({obs})" if obs else ""
    text = f"  {time_str} [{kind}]{who} {summary}" if summary else f"  {time_str} [{kind}]{who}"
    show(Block.text(text, p.muted), file=sys.stdout)


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
        from engine import StoreReader

        with StoreReader(sp) as reader:
            data = reader.summary()
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

    now = datetime.now(timezone.utc)
    since_ts = now.timestamp() - duration_secs
    kind = getattr(args, "kind", None)
    use_json = getattr(args, "json", False)

    from engine import StoreReader

    with StoreReader(sp) as reader:
        facts = reader.facts_between(since_ts, now.timestamp(), kind=kind)

    facts.sort(key=lambda f: f["ts"])

    if use_json:
        for f in facts:
            f_out = dict(f)
            if isinstance(f_out["ts"], datetime):
                f_out["ts"] = f_out["ts"].isoformat()
            print(json.dumps(f_out, default=str))
        return 0

    if not facts:
        from painted import show
        from painted.block import Block
        from painted.palette import current_palette

        p = current_palette()
        show(Block.text("No facts in the given time range.", p.muted), file=sys.stdout)
        return 0

    # Group by date
    current_date = None
    for f in facts:
        ts = f["ts"]
        dt = ts if isinstance(ts, datetime) else datetime.fromtimestamp(ts, tz=timezone.utc)
        date_str = _format_date(dt)
        if date_str != current_date:
            if current_date is not None:
                print()
            from painted import show
            from painted.block import Block
            from painted.palette import current_palette

            p = current_palette()
            show(Block.text(f"{date_str}:", p.accent), file=sys.stdout)
            current_date = date_str

        _render_log_entry(f)

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
