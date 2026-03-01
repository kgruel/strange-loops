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
    require_store,
    store_path,
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


# -- Fetch --


def fetch_project_status(sp: Path) -> dict:
    """Fetch project status — latest-per-group fold over decisions, threads, plans."""
    require_store(sp, "No project data yet. Run 'strange-loops project emit' first.")

    from engine import StoreReader

    with StoreReader(sp) as reader:
        total = reader.fact_total
        all_facts = reader.facts_between(0, float("inf"))

    decisions = _latest_by_group(all_facts, "decision", "topic")
    threads = _latest_by_group(all_facts, "thread", "name")
    plans = _latest_by_group(all_facts, "plan", "name")
    completions = _latest_by_group(all_facts, "completion", "task")

    # Filter threads: hide resolved
    open_threads = {k: v for k, v in threads.items() if v["payload"].get("status") != "resolved"}

    return {
        "total": total,
        "decisions": decisions,
        "threads": open_threads,
        "plans": plans,
        "completions": completions,
    }


def fetch_project_log(sp: Path, duration_secs: float, kind: str | None = None) -> dict:
    """Fetch project log — facts in a time range."""
    require_store(sp, "No project data yet. Run 'strange-loops project emit' first.")

    from engine import StoreReader

    now = datetime.now(timezone.utc)
    since_ts = now.timestamp() - duration_secs

    with StoreReader(sp) as reader:
        facts = reader.facts_between(since_ts, now.timestamp(), kind=kind)

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
    completions = _latest_by_group(all_facts, "completion", "task")

    # Filter threads: hide resolved
    open_threads = {k: v for k, v in threads.items() if v["payload"].get("status") != "resolved"}

    if use_json:
        data = {
            "total": total,
            "decisions": {k: v["payload"] for k, v in sorted(decisions.items())},
            "threads": {k: v["payload"] for k, v in sorted(open_threads.items())},
            "plans": {k: v["payload"] for k, v in sorted(plans.items())},
            "completions": {k: v["payload"] for k, v in sorted(completions.items())},
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

    if completions:
        lines.append(Block.text("", p.muted))
        lines.append(Block.text(f"Completions ({len(completions)}):", p.accent))
        for task_name, f in sorted(completions.items()):
            dt = (
                f["ts"]
                if isinstance(f["ts"], datetime)
                else datetime.fromtimestamp(f["ts"], tz=timezone.utc)
            )
            status = f["payload"].get("status", "")
            exit_code = f["payload"].get("exit_code", "")
            detail = f"{status} exit={exit_code}" if exit_code != "" else status
            label = f"  {task_name}: {detail}" if detail else f"  {task_name}"
            lines.append(Block.text(f"{label} ({dt.strftime('%b %d')})", p.muted))

    show(join_vertical(*lines), file=sys.stdout)
    return 0


def cmd_project_log(args: argparse.Namespace) -> int:
    """Show project log — time-windowed query with optional kind filter."""
    sp = _project_store()
    try:
        duration_secs = parse_duration(getattr(args, "since", "7d"))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    kind = getattr(args, "kind", None)
    use_json = getattr(args, "json", False)

    try:
        data = fetch_project_log(sp, duration_secs, kind)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

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
    task_sp = store_path()
    project_sp = _project_store()

    try:
        require_store(task_sp, "No task data yet. Run tasks first.")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from engine import StoreReader

    # 1. Read all task.tick ticks from tasks.db
    with StoreReader(task_sp) as reader:
        ticks = reader.ticks_between(0, float("inf"), name="task.tick")

    if not ticks:
        from painted import show
        from painted.block import Block
        from painted.palette import current_palette

        p = current_palette()
        show(Block.text("No task.tick ticks to bridge.", p.muted), file=sys.stdout)
        return 0

    # 2. Read existing completion facts from project.db (if any)
    already_bridged: set[str] = set()
    if project_sp.exists():
        with StoreReader(project_sp) as reader:
            all_facts = reader.facts_between(0, float("inf"))
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
