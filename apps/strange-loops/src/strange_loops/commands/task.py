"""Task commands — create, assign, send, monitor, merge, close."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from painted.block import Block

from strange_loops import harness, worktree
from strange_loops.lifecycle import fold_all_tasks, fold_task_state
from strange_loops.store import emit_fact, observer, require_store, store_path


def _render_task(state: dict) -> "Block":
    """Render a single task as a painted block."""
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    name = state["name"]
    status = state.get("status", "unknown")
    title = state.get("title", "")

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
        lines.append(Block.text(worker_info, p.muted))
    if state.get("base_branch"):
        lines.append(Block.text(f"    base: {state['base_branch']}", p.muted))

    return join_vertical(*lines)


def _render_task_list(tasks: list[dict]) -> "Block":
    """Render all tasks as a painted block."""
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    if not tasks:
        return Block.text("No tasks.", p.muted)

    header = Block.text(f"Tasks — {len(tasks)} total", p.accent)
    blocks = [header]
    for t in tasks:
        blocks.append(_render_task(t))

    return join_vertical(*blocks, gap=1)


def _require_task(reader, name: str) -> dict:
    """Require that a task exists, return its state."""
    state = fold_task_state(reader, name)
    if state is None:
        raise ValueError(f"Task '{name}' not found. Create it first with 'task create'.")
    return state


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
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from engine import StoreReader

    name = args.name
    harness_type = getattr(args, "harness", "shell")

    with StoreReader(sp) as reader:
        try:
            state = _require_task(reader, name)
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
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from engine import StoreReader

    name = args.name
    command = args.shell_command

    with StoreReader(sp) as reader:
        try:
            state = _require_task(reader, name)
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
    sp = store_path()
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    use_json = getattr(args, "json", False)
    name = getattr(args, "name", None)

    from engine import StoreReader

    with StoreReader(sp) as reader:
        if name:
            state = fold_task_state(reader, name)
            if state is None:
                print(f"Error: Task '{name}' not found.", file=sys.stderr)
                return 1

            if use_json:
                print(json.dumps(state, indent=2, default=str))
            else:
                from painted import show

                show(_render_task(state), file=sys.stdout)
        else:
            tasks = fold_all_tasks(reader)
            if use_json:
                print(json.dumps(tasks, indent=2, default=str))
            else:
                from painted import show

                show(_render_task_list(tasks), file=sys.stdout)

    return 0


def cmd_task_list(args: argparse.Namespace) -> int:
    """List all tasks — alias for status with no name."""
    args.name = None
    return cmd_task_status(args)


def cmd_task_diff(args: argparse.Namespace) -> int:
    """Show diff for a task's worktree."""
    sp = store_path()
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from engine import StoreReader

    name = args.name

    with StoreReader(sp) as reader:
        try:
            state = _require_task(reader, name)
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
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from engine import StoreReader

    name = args.name
    force = getattr(args, "force", False)

    with StoreReader(sp) as reader:
        try:
            state = _require_task(reader, name)
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
    try:
        require_store(sp)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from engine import StoreReader

    name = args.name

    with StoreReader(sp) as reader:
        try:
            state = _require_task(reader, name)
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
    }
    cmd = getattr(args, "task_command", None)
    handler = dispatch.get(cmd)
    if handler:
        return handler(args)
    print(
        "Usage: strange-loops task {create|assign|send|run|status|list|diff|merge|close}",
        file=sys.stderr,
    )
    return 1
