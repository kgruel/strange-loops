"""Task commands — create, assign, send, monitor, merge, close, log, stop."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from painted.block import Block

from strange_loops import harness, worktree
from strange_loops.lifecycle import fold_all_tasks, fold_task_state, tasks_vertex_path
from strange_loops.store import (
    emit_fact,
    filter_task_facts as _filter_task_facts,
    filter_task_ticks as _filter_task_ticks,
    observer,
    parse_duration,
    print_fact_line,
    print_tick_line,
    store_path,
    tick_to_dict,
)


def render_task(state: dict, zoom=None) -> "Block":
    """Render a single task as a painted block — zoom-aware.

    MINIMAL: `name [status]`
    SUMMARY: name+status+title header, harness, worktree, worker, base
    DETAILED: + description, + pid on worker line
    FULL: + raw state dict dump below separator
    """
    from painted import Zoom
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    if zoom is None:
        zoom = Zoom.SUMMARY

    p = current_palette()
    name = state["name"]
    status = state.get("status", "unknown")
    title = state.get("title", "")

    if zoom == Zoom.MINIMAL:
        text = f"  {name} [{status}]"
        return Block.text(text, p.accent)

    header_text = f"  {name}  [{status}]"
    if title:
        header_text += f"  {title}"

    lines = [Block.text(header_text, p.accent)]

    if state.get("harness"):
        lines.append(Block.text(f"    harness: {state['harness']}", p.muted))
    if state.get("worktree"):
        lines.append(Block.text(f"    worktree: {state['worktree']}", p.muted))
    if state.get("worker"):
        worker_info = f"    worker: {state['worker']}"
        if state.get("exit_code") is not None:
            worker_info += f" exit={state['exit_code']}"
        if zoom >= Zoom.DETAILED and state.get("pid") is not None:
            worker_info += f" pid={state['pid']}"
        lines.append(Block.text(worker_info, p.muted))
    if state.get("base_branch"):
        lines.append(Block.text(f"    base: {state['base_branch']}", p.muted))

    if zoom >= Zoom.DETAILED and state.get("description"):
        lines.append(Block.text(f"    description: {state['description']}", p.muted))

    if zoom >= Zoom.FULL:
        lines.append(Block.text("    ---", p.muted))
        for k, v in sorted(state.items()):
            lines.append(Block.text(f"    {k}: {v}", p.muted))

    return join_vertical(*lines)


def render_task_list(tasks: list[dict], zoom=None) -> "Block":
    """Render all tasks as a painted block — zoom-aware.

    MINIMAL: `N tasks, M working, K closed`
    SUMMARY/DETAILED/FULL: header + each task at corresponding zoom.
    """
    from painted import Zoom
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    if zoom is None:
        zoom = Zoom.SUMMARY

    p = current_palette()
    if not tasks:
        return Block.text("No tasks.", p.muted)

    if zoom == Zoom.MINIMAL:
        counts: dict[str, int] = {}
        for t in tasks:
            s = t.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
        parts = [f"{len(tasks)} tasks"]
        for status, n in sorted(counts.items()):
            parts.append(f"{n} {status}")
        return Block.text(", ".join(parts), p.muted)

    header = Block.text(f"Tasks — {len(tasks)} total", p.accent)
    blocks = [header]
    for t in tasks:
        blocks.append(render_task(t, zoom))

    return join_vertical(*blocks, gap=1)


def _require_task(vp: Path, name: str) -> dict:
    """Require that a task exists, return its state."""
    state = fold_task_state(vp, name)
    if state is None:
        raise ValueError(f"Task '{name}' not found. Create it first with 'task create'.")
    return state


# -- Fetch --


def fetch_task_status(vp: Path, name: str | None = None) -> dict | list[dict]:
    """Fetch task status — single task dict or list of all tasks."""
    if name:
        state = fold_task_state(vp, name)
        if state is None:
            raise ValueError(f"Task '{name}' not found.")
        return state
    return fold_all_tasks(vp)


def fetch_task_log(vp: Path, name: str, duration_secs: float, kind: str | None = None) -> dict:
    """Fetch task log — filtered facts and ticks for a specific task."""
    from engine import vertex_facts, vertex_ticks

    _require_task(vp, name)
    now = datetime.now(timezone.utc)
    since_ts = now.timestamp() - duration_secs

    facts = vertex_facts(vp, since_ts, now.timestamp(), kind=kind)
    ticks = vertex_ticks(vp, since_ts, now.timestamp())

    facts = _filter_task_facts(facts, name)
    tick_dicts = [tick_to_dict(t) for t in ticks]
    tick_dicts = _filter_task_ticks(tick_dicts, name)
    facts.sort(key=lambda f: f["ts"])

    return {"facts": facts, "ticks": tick_dicts}


# -- Commands --


def cmd_task_create(args: argparse.Namespace) -> int:
    """Create a task: emit task.created fact."""
    sp = store_path()
    obs = observer(args)

    name = args.name
    title = getattr(args, "title", None) or name
    base = getattr(args, "base", None)
    description = getattr(args, "description", None) or ""

    if not base:
        try:
            base = worktree.current_branch(Path.cwd())
        except subprocess.CalledProcessError:
            base = "main"

    emit_fact(
        sp,
        "task.created",
        obs,
        {
            "name": name,
            "title": title,
            "base_branch": base,
            "description": description,
        },
    )

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    show(Block.text(f"Task '{name}' created (base: {base})", p.success), file=sys.stdout)
    return 0


def cmd_task_assign(args: argparse.Namespace) -> int:
    """Assign a task: create worktree, emit task.assigned fact."""
    sp = store_path()
    name = args.name
    harness_type = getattr(args, "harness", "shell")

    try:
        state = _require_task(tasks_vertex_path(), name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    base = state.get("base_branch", "main")
    repo_root = Path.cwd()

    try:
        wt_path = worktree.create(repo_root, name, base)
    except subprocess.CalledProcessError as e:
        print(f"Error creating worktree: {e.stderr or e}", file=sys.stderr)
        return 1

    obs = observer(args)
    emit_fact(
        sp,
        "task.assigned",
        obs,
        {
            "name": name,
            "harness": harness_type,
            "worktree": str(wt_path),
        },
    )

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    show(Block.text(f"Task '{name}' assigned → {wt_path}", p.success), file=sys.stdout)
    return 0


def cmd_task_send(args: argparse.Namespace) -> int:
    """Send work to a task: spawn harness (resolved from task state)."""
    sp = store_path()
    name = args.name
    command = args.shell_command

    try:
        state = _require_task(tasks_vertex_path(), name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if "worktree" not in state:
        print(f"Error: Task '{name}' not assigned. Run 'task assign' first.", file=sys.stderr)
        return 1

    wt_path = Path(state["worktree"])
    harness_name = state.get("harness", "shell")
    obs = observer(args)

    pid = harness.spawn(sp, name, wt_path, command, harness_name, obs)
    emit_fact(sp, "task.stage", obs, {"name": name, "status": "working"})

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    show(Block.text(f"Worker spawned for '{name}' (pid {pid})", p.success), file=sys.stdout)
    return 0


def cmd_task_status(args: argparse.Namespace) -> int:
    """Show task status — single task detail or all tasks summary."""
    use_json = getattr(args, "json", False)
    name = getattr(args, "name", None)
    vp = tasks_vertex_path()

    try:
        data = fetch_task_status(vp, name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if use_json:
        print(json.dumps(data, indent=2, default=str))
    else:
        from painted import show

        if isinstance(data, list):
            show(render_task_list(data), file=sys.stdout)
        else:
            show(render_task(data), file=sys.stdout)

    return 0


def cmd_task_list(args: argparse.Namespace) -> int:
    """List all tasks — alias for status with no name."""
    args.name = None
    return cmd_task_status(args)


def cmd_task_diff(args: argparse.Namespace) -> int:
    """Show diff for a task's worktree."""
    name = args.name

    try:
        state = _require_task(tasks_vertex_path(), name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if "worktree" not in state:
        print(f"Error: Task '{name}' has no worktree.", file=sys.stderr)
        return 1

    wt_path = Path(state["worktree"])
    try:
        diff_output = worktree.diff_full(wt_path)
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr or e}", file=sys.stderr)
        return 1

    if diff_output:
        print(diff_output)
    else:
        print("No changes in worktree.")
    return 0


def cmd_task_merge(args: argparse.Namespace) -> int:
    """Merge a task's worktree branch back via squash merge."""
    sp = store_path()
    name = args.name
    force = getattr(args, "force", False)

    try:
        state = _require_task(tasks_vertex_path(), name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if "worktree" not in state:
        print(f"Error: Task '{name}' has no worktree.", file=sys.stderr)
        return 1

    base = state.get("base_branch", "main")
    repo_root = Path.cwd()

    # Check for uncommitted changes in the worktree
    wt_path = Path(state["worktree"])
    if not force:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=wt_path,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            print(
                "Error: Worktree has uncommitted changes. Commit first or use --force.",
                file=sys.stderr,
            )
            return 1

    # Squash merge
    try:
        subprocess.run(
            ["git", "checkout", base],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        # Check if branch has changes to merge
        diff_result = subprocess.run(
            ["git", "diff", f"{base}...{name}", "--quiet"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if diff_result.returncode == 0:
            print(f"Nothing to merge — '{name}' has no changes vs {base}.", file=sys.stderr)
            return 1
        subprocess.run(
            ["git", "merge", "--squash", name],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            ["git", "commit", "-m", f"merge: {name}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        # Get the commit hash
        commit_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        commit_hash = commit_result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error during merge: {e.stderr or e}", file=sys.stderr)
        return 1

    obs = observer(args)
    emit_fact(
        sp,
        "task.merged",
        obs,
        {
            "name": name,
            "strategy": "squash",
            "commit": commit_hash,
        },
    )
    emit_fact(
        sp,
        "task.completed",
        obs,
        {
            "name": name,
            "summary": f"Squash merged to {base} ({commit_hash[:8]})",
        },
    )

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    show(
        Block.text(f"Task '{name}' merged to {base} ({commit_hash[:8]})", p.success),
        file=sys.stdout,
    )
    return 0


def cmd_task_run(args: argparse.Namespace) -> int:
    """Run a task: create → assign → send in one invocation."""
    sp = store_path()
    obs = observer(args)

    name = args.name
    title = getattr(args, "title", None) or name
    base = getattr(args, "base", None)
    description = args.description
    harness_type = getattr(args, "harness", "shell")

    if not base:
        try:
            base = worktree.current_branch(Path.cwd())
        except subprocess.CalledProcessError:
            base = "main"

    # 1. task.created
    emit_fact(
        sp,
        "task.created",
        obs,
        {
            "name": name,
            "title": title,
            "base_branch": base,
            "description": description,
        },
    )

    # 2. worktree
    repo_root = Path.cwd()
    try:
        wt_path = worktree.create(repo_root, name, base)
    except subprocess.CalledProcessError as e:
        print(f"Error creating worktree: {e.stderr or e}", file=sys.stderr)
        return 1

    # 3. task.assigned
    emit_fact(
        sp,
        "task.assigned",
        obs,
        {
            "name": name,
            "harness": harness_type,
            "worktree": str(wt_path),
        },
    )

    # 4. task.stage → working
    emit_fact(sp, "task.stage", obs, {"name": name, "status": "working"})

    # 5. spawn harness
    pid = harness.spawn(sp, name, wt_path, description, harness_type, obs)

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    show(Block.text(f"Task '{name}' running (pid {pid})", p.success), file=sys.stdout)
    return 0


def cmd_task_close(args: argparse.Namespace) -> int:
    """Close a task: remove worktree, emit stage fact."""
    sp = store_path()
    name = args.name

    try:
        state = _require_task(tasks_vertex_path(), name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Remove worktree if it exists
    if "worktree" in state:
        repo_root = Path.cwd()
        try:
            worktree.remove(repo_root, name)
        except subprocess.CalledProcessError:
            pass  # Worktree may already be removed

    obs = observer(args)
    emit_fact(sp, "task.stage", obs, {"name": name, "status": "closed"})

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    show(Block.text(f"Task '{name}' closed.", p.success), file=sys.stdout)
    return 0


def cmd_task_log(args: argparse.Namespace) -> int:
    """Show log for a specific task — filtered time-range query."""
    name = args.name
    vp = tasks_vertex_path()

    try:
        _require_task(vp, name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        duration_secs = parse_duration(getattr(args, "since", "7d"))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    kind = getattr(args, "kind", None)
    use_json = getattr(args, "json", False)
    follow = getattr(args, "follow", False)

    if follow:
        return follow_task_log(vp, name, kind, use_json)

    data = fetch_task_log(vp, name, duration_secs, kind)

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
            print(json.dumps(f_out, default=str), flush=True)
        return 0

    from painted import show

    from strange_loops.store import log_block

    show(log_block(data["facts"], data["ticks"]), file=sys.stdout)
    return 0


def follow_task_log(vp: Path, name: str, kind: str | None, use_json: bool) -> int:
    """Follow task log — poll for new facts and ticks, print as they arrive."""
    from engine import vertex_facts, vertex_ticks

    last_ts = 0.0

    try:
        while True:
            facts = vertex_facts(vp, last_ts, float("inf"), kind=kind)
            ticks = vertex_ticks(vp, last_ts, float("inf"))

            facts = _filter_task_facts(facts, name)
            tick_dicts = [tick_to_dict(t) for t in ticks]
            tick_dicts = _filter_task_ticks(tick_dicts, name)

            # Build unified timeline
            entries: list[tuple[float, str, dict]] = []
            for f in facts:
                ts = f["ts"]
                ts_val = ts.timestamp() if isinstance(ts, datetime) else ts
                entries.append((ts_val, "fact", f))
            for t in tick_dicts:
                ts = t["ts"]
                ts_val = ts.timestamp() if isinstance(ts, datetime) else ts
                entries.append((ts_val, "tick", t))
            entries.sort(key=lambda e: e[0])

            for ts_val, entry_type, item in entries:
                if ts_val <= last_ts:
                    continue
                last_ts = ts_val

                if use_json:
                    f_out = dict(item)
                    if isinstance(f_out.get("ts"), datetime):
                        f_out["ts"] = f_out["ts"].isoformat()
                    print(json.dumps(f_out, default=str), flush=True)
                elif entry_type == "fact":
                    print_fact_line(item)
                else:
                    print_tick_line(item)

            time.sleep(2)
    except KeyboardInterrupt:
        return 0


def cmd_task_stop(args: argparse.Namespace) -> int:
    """Stop a running task worker."""
    sp = store_path()
    name = args.name

    try:
        state = _require_task(tasks_vertex_path(), name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    status = state.get("status", "")
    if status not in ("working", "assigned"):
        print(
            f"Error: Task '{name}' is not running (status: {status}).",
            file=sys.stderr,
        )
        return 1

    pid = state.get("pid")
    if pid is None:
        print(f"Error: No worker PID recorded for task '{name}'.", file=sys.stderr)
        return 1

    # Check if process is still alive
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        # Already exited — just emit the stage fact
        obs = observer(args)
        emit_fact(sp, "task.stage", obs, {"name": name, "status": "stopped"})

        from painted import show
        from painted.block import Block
        from painted.palette import current_palette

        p = current_palette()
        show(
            Block.text(f"Worker for '{name}' already exited (pid {pid}).", p.muted),
            file=sys.stdout,
        )
        return 0
    except PermissionError:
        print(f"Error: No permission to signal worker (pid {pid}).", file=sys.stderr)
        return 1

    # Kill the process group (spawn uses start_new_session=True → PID == PGID)
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # Raced with exit

    # Poll for exit (200ms × 10 = 2s)
    alive = True
    for _ in range(10):
        time.sleep(0.2)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            alive = False
            break
        except PermissionError:
            alive = False
            break

    # Escalate to SIGKILL if still alive
    if alive:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    obs = observer(args)
    emit_fact(sp, "task.stage", obs, {"name": name, "status": "stopped"})

    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    show(Block.text(f"Task '{name}' stopped (pid {pid}).", p.success), file=sys.stdout)
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    """Dispatch task subcommands."""
    dispatch = {
        "create": cmd_task_create,
        "assign": cmd_task_assign,
        "send": cmd_task_send,
        "run": cmd_task_run,
        "status": cmd_task_status,
        "list": cmd_task_list,
        "diff": cmd_task_diff,
        "merge": cmd_task_merge,
        "close": cmd_task_close,
        "log": cmd_task_log,
        "stop": cmd_task_stop,
    }
    cmd = getattr(args, "task_command", None)
    handler = dispatch.get(cmd)
    if handler:
        return handler(args)
    print(
        "Usage: strange-loops task {create|assign|send|run|status|list|diff|merge|close|log|stop}",
        file=sys.stderr,
    )
    return 1
