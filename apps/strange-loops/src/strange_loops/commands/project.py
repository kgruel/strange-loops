"""Project commands — coordination surface for strange-loops."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from strange_loops.lifecycle import project_vertex_path, tasks_vertex_path
from strange_loops.store import (
    emit_fact,
    observer,
    parse_duration,
    store_path_for,
)


def _project_store() -> Path:
    """Resolve the project store path for write operations."""
    return store_path_for("project")


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


def _items_to_facts(kind_state: dict) -> dict[str, dict]:
    """Convert vertex_read items to fact-like dicts for lens compatibility.

    vertex_read returns {kind: {"items": {key: enriched_payload}}} where
    enriched_payload has _ts/_observer injected. Transform to the shape
    the project lens expects: {key: {"ts": ..., "observer": ..., "payload": {...}}}.
    """
    result = {}
    for key, payload in kind_state.get("items", {}).items():
        p = {k: v for k, v in payload.items() if not k.startswith("_")}
        result[key] = {
            "ts": payload.get("_ts", 0),
            "observer": payload.get("_observer", ""),
            "payload": p,
        }
    return result


# -- Fetch --


def fetch_project_status(vp: Path) -> dict:
    """Fetch project status — vertex_read fold over decisions, threads, plans."""
    from engine import vertex_read, vertex_summary

    states = vertex_read(vp)
    summary = vertex_summary(vp)
    total = summary["facts"]["total"]

    decisions = _items_to_facts(states.get("decision", {}))
    threads = _items_to_facts(states.get("thread", {}))
    plans = _items_to_facts(states.get("plan", {}))
    completions = _items_to_facts(states.get("completion", {}))

    # Filter threads: hide resolved
    open_threads = {k: v for k, v in threads.items() if v["payload"].get("status") != "resolved"}

    return {
        "total": total,
        "decisions": decisions,
        "threads": open_threads,
        "plans": plans,
        "completions": completions,
    }


def fetch_project_log(vp: Path, duration_secs: float, kind: str | None = None) -> dict:
    """Fetch project log — facts in a time range."""
    from engine import vertex_facts

    now = datetime.now(timezone.utc)
    since_ts = now.timestamp() - duration_secs

    facts = vertex_facts(vp, since_ts, now.timestamp(), kind=kind)
    facts.sort(key=lambda f: f["ts"])

    return {"facts": facts}


# -- Commands --


def cmd_project_emit(args: argparse.Namespace) -> int:
    """Emit a project fact: project emit KIND [KEY=VALUE...] [message]."""
    sp = _project_store()
    kind = args.kind
    parts = args.parts or []
    payload = _parse_emit_parts(parts)
    obs = observer(args)
    emit_fact(sp, kind, obs, payload)

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    summary = " ".join(f"{k}={v}" for k, v in payload.items())
    p = current_palette()
    show(Block.text(f"[{kind}] {summary}", p.success), file=sys.stdout)
    return 0


def cmd_project_status(args: argparse.Namespace) -> int:
    """Show project status — latest-per-group fold over decisions, threads, plans."""
    import shutil

    use_json = getattr(args, "json", False)
    vp = project_vertex_path()
    data = fetch_project_status(vp)

    if use_json:
        json_data = {
            "total": data["total"],
            "decisions": {k: v["payload"] for k, v in sorted(data["decisions"].items())},
            "threads": {k: v["payload"] for k, v in sorted(data["threads"].items())},
            "plans": {k: v["payload"] for k, v in sorted(data["plans"].items())},
            "completions": {k: v["payload"] for k, v in sorted(data["completions"].items())},
        }
        print(json.dumps(json_data, indent=2, default=str))
        return 0

    from painted import Zoom, show

    from strange_loops.lenses.project import project_status_view

    width = shutil.get_terminal_size().columns
    show(project_status_view(data, Zoom.SUMMARY, width), file=sys.stdout)
    return 0


def cmd_project_log(args: argparse.Namespace) -> int:
    """Show project log — time-windowed query with optional kind filter."""
    try:
        duration_secs = parse_duration(getattr(args, "since", "7d"))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    kind = getattr(args, "kind", None)
    use_json = getattr(args, "json", False)

    data = fetch_project_log(project_vertex_path(), duration_secs, kind)

    if use_json:
        for f in data["facts"]:
            f_out = dict(f)
            if isinstance(f_out["ts"], datetime):
                f_out["ts"] = f_out["ts"].isoformat()
            print(json.dumps(f_out, default=str))
        return 0

    from painted import show

    from strange_loops.store import log_block

    show(log_block(data["facts"]), file=sys.stdout)
    return 0


def cmd_project_bridge(args: argparse.Namespace) -> int:
    """Bridge task.tick ticks from tasks.db → completion facts in project.db."""
    project_sp = _project_store()

    from engine import vertex_facts, vertex_ticks

    tasks_vp = tasks_vertex_path()
    project_vp = project_vertex_path()

    # 1. Read all task.tick ticks from tasks vertex
    ticks = vertex_ticks(tasks_vp, 0, float("inf"), name="task.tick")

    if not ticks:
        from painted import show
        from painted.block import Block
        from painted.palette import current_palette

        p = current_palette()
        show(Block.text("No task.tick ticks to bridge.", p.muted), file=sys.stdout)
        return 0

    # 2. Read existing completion facts from project vertex (if any)
    already_bridged: set[str] = set()
    all_facts = vertex_facts(project_vp, 0, float("inf"))
    for f in all_facts:
        if f["kind"] == "completion":
            task_name = f["payload"].get("task", "")
            if task_name:
                already_bridged.add(task_name)

    # 3. Latest tick per task
    latest_per_task: dict[str, object] = {}
    for t in ticks:
        payload = t.payload if isinstance(t.payload, dict) else {}
        task_name = payload.get("task", "")
        if not task_name:
            continue
        existing = latest_per_task.get(task_name)
        if existing is None:
            latest_per_task[task_name] = t
        else:
            existing_ts = (
                existing.ts.timestamp() if isinstance(existing.ts, datetime) else existing.ts
            )
            tick_ts = t.ts.timestamp() if isinstance(t.ts, datetime) else t.ts
            if tick_ts > existing_ts:
                latest_per_task[task_name] = t

    # 4. Bridge new ones
    obs = observer(args)
    bridged = []
    for task_name, tick in sorted(latest_per_task.items()):
        if task_name in already_bridged:
            continue
        payload = tick.payload if isinstance(tick.payload, dict) else {}
        emit_fact(project_sp, "completion", obs, dict(payload))
        bridged.append(task_name)

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    if bridged:
        show(
            Block.text(
                f"Bridged {len(bridged)} tick(s) → completions: {', '.join(bridged)}", p.success
            ),
            file=sys.stdout,
        )
    else:
        show(Block.text("All ticks already bridged.", p.muted), file=sys.stdout)
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    """Dispatch project subcommands."""
    dispatch = {
        "emit": cmd_project_emit,
        "status": cmd_project_status,
        "log": cmd_project_log,
        "bridge": cmd_project_bridge,
    }
    cmd = getattr(args, "project_command", None)
    handler = dispatch.get(cmd)
    if handler:
        return handler(args)
    print("Usage: strange-loops project {emit|status|log|bridge}", file=sys.stderr)
    return 1
