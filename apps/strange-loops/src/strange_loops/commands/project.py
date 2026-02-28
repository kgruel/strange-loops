"""Project commands — coordination surface for strange-loops."""

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
    render_log,
    require_store,
    store_path_for,
)

_VERTEX_NAME = "project"


def _project_store() -> Path:
    """Resolve the project store path from the vertex file."""
    return store_path_for(_VERTEX_NAME)


def _parse_emit_parts(parts: list[str]) -> dict[str, str]:
    """Parse emit args into a payload dict.

    KEY=VALUE tokens become payload entries. Remaining tokens join as message.
    """
    payload: dict[str, str] = {}
    message_parts: list[str] = []
    for part in parts:
        if "=" in part:
            key, _, value = part.partition("=")
            if key.isidentifier():
                payload[key] = value
                continue
        message_parts.append(part)
    if message_parts:
        payload["message"] = " ".join(message_parts)
    return payload


def _latest_by_group(facts: list[dict], kind: str, group_field: str) -> dict[str, dict]:
    """Query-time fold: filter by kind, group by field, keep newest per group."""
    grouped: dict[str, dict] = {}
    for f in facts:
        if f["kind"] != kind:
            continue
        key = f["payload"].get(group_field, "")
        if not key:
            continue
        existing = grouped.get(key)
        if existing is None or f["ts"] > existing["ts"]:
            grouped[key] = f
    return grouped


# -- Commands --


def cmd_project_emit(args: argparse.Namespace) -> int:
    """Emit a project fact: project emit KIND [KEY=VALUE...] [message]."""
    sp = _project_store()
    kind = args.kind
    parts = args.parts or []
    payload = _parse_emit_parts(parts)
    obs = observer(args)
    emit_fact(sp, kind, obs, payload)

    summary = " ".join(f"{k}={v}" for k, v in payload.items())
    print(f"[{kind}] {summary}")
    return 0


def cmd_project_status(args: argparse.Namespace) -> int:
    """Show project status — latest-per-group fold over decisions, threads, plans."""
    sp = _project_store()
    try:
        require_store(sp, "No project data yet. Run 'strange-loops project emit' first.")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    use_json = getattr(args, "json", False)

    from engine import StoreReader

    with StoreReader(sp) as reader:
        total = reader.fact_total
        all_facts = reader.facts_between(0, float("inf"))

    decisions = _latest_by_group(all_facts, "decision", "topic")
    threads = _latest_by_group(all_facts, "thread", "name")
    plans = _latest_by_group(all_facts, "plan", "name")

    # Filter threads: hide resolved
    open_threads = {k: v for k, v in threads.items() if v["payload"].get("status") != "resolved"}

    if use_json:
        data = {
            "total": total,
            "decisions": {k: v["payload"] for k, v in sorted(decisions.items())},
            "threads": {k: v["payload"] for k, v in sorted(open_threads.items())},
            "plans": {k: v["payload"] for k, v in sorted(plans.items())},
        }
        print(json.dumps(data, indent=2, default=str))
        return 0

    from painted import show
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    lines: list[Block] = [Block.text(f"Project — {total} facts", p.accent)]

    if decisions:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Decisions ({len(decisions)}):", p.accent))
        for topic, f in sorted(decisions.items()):
            dt = (
                f["ts"]
                if isinstance(f["ts"], datetime)
                else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
            )
            msg = f["payload"].get("message", "")
            label = f"  {topic}: {msg}" if msg else f"  {topic}"
            lines.append(Block.text(f"{label} ({dt.strftime('%b %d')})", p.muted))

    if open_threads:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Open Threads ({len(open_threads)}):", p.accent))
        for name, f in sorted(open_threads.items()):
            dt = (
                f["ts"]
                if isinstance(f["ts"], datetime)
                else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
            )
            msg = f["payload"].get("message", "")
            status = f["payload"].get("status", "")
            detail = msg or status
            label = f"  {name}: {detail}" if detail else f"  {name}"
            lines.append(Block.text(f"{label} ({dt.strftime('%b %d')})", p.muted))

    if plans:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Plans ({len(plans)}):", p.accent))
        for name, f in sorted(plans.items()):
            dt = (
                f["ts"]
                if isinstance(f["ts"], datetime)
                else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
            )
            status = f["payload"].get("status", "")
            label = f"  {name}: {status}" if status else f"  {name}"
            lines.append(Block.text(f"{label} ({dt.strftime('%b %d')})", p.muted))

    show(join_vertical(*lines), file=sys.stdout)
    return 0


def cmd_project_log(args: argparse.Namespace) -> int:
    """Show project log — time-windowed query with optional kind filter."""
    sp = _project_store()
    try:
        require_store(sp, "No project data yet. Run 'strange-loops project emit' first.")
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

    render_log(facts)
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    """Dispatch project subcommands."""
    dispatch = {
        "emit": cmd_project_emit,
        "status": cmd_project_status,
        "log": cmd_project_log,
    }
    cmd = getattr(args, "project_command", None)
    handler = dispatch.get(cmd)
    if handler:
        return handler(args)
    print("Usage: strange-loops project {emit|status|log}", file=sys.stderr)
    return 1
