"""CLI entry point for strange-loops."""

from __future__ import annotations

import argparse
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strange-loops",
        description="Task orchestration built on loops",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="Show version")

    # session
    session_parser = subparsers.add_parser("session", help="Session lifecycle")
    session_sub = session_parser.add_subparsers(dest="session_command", required=True)

    start_p = session_sub.add_parser("start", help="Start a session")
    start_p.add_argument("--observer", help="Observer identity")

    end_p = session_sub.add_parser("end", help="End a session")
    end_p.add_argument("--observer", help="Observer identity")

    # status and log defined for argparse help; actual dispatch is pre-routed
    session_sub.add_parser("status", help="Show session status")
    session_sub.add_parser("log", help="Show session log")

    # task
    task_parser = subparsers.add_parser("task", help="Task lifecycle")
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)

    create_p = task_sub.add_parser("create", help="Create a task")
    create_p.add_argument("name", help="Task name (used as branch name)")
    create_p.add_argument("--title", help="Human-readable title")
    create_p.add_argument("--base", help="Base branch (default: current branch)")
    create_p.add_argument("--description", help="Task description")
    create_p.add_argument("--observer", help="Observer identity")

    assign_p = task_sub.add_parser("assign", help="Assign a task (creates worktree)")
    assign_p.add_argument("name", help="Task name")
    assign_p.add_argument("--harness", default="shell", help="Harness type (default: shell)")
    assign_p.add_argument("--observer", help="Observer identity")

    send_p = task_sub.add_parser("send", help="Send work to a task")
    send_p.add_argument("name", help="Task name")
    send_p.add_argument("shell_command", help="Shell command to run in worktree")
    send_p.add_argument("--observer", help="Observer identity")

    run_p = task_sub.add_parser("run", help="Create, assign, and send in one step")
    run_p.add_argument("name", help="Task name (branch, worktree, fact key)")
    run_p.add_argument(
        "--description", required=True, help="Work specification / prompt for harness"
    )
    run_p.add_argument("--harness", default="shell", help="Harness .loop file (default: shell)")
    run_p.add_argument("--title", help="Human-readable title (default: name)")
    run_p.add_argument("--base", help="Base branch (default: current branch)")
    run_p.add_argument("--observer", help="Observer identity")

    # status, list, log defined for argparse help; actual dispatch is pre-routed
    task_sub.add_parser("status", help="Show task status")
    task_sub.add_parser("list", help="List all tasks")
    task_sub.add_parser("log", help="Show task log")

    diff_p = task_sub.add_parser("diff", help="Show task worktree diff")
    diff_p.add_argument("name", help="Task name")

    merge_p = task_sub.add_parser("merge", help="Squash merge task branch")
    merge_p.add_argument("name", help="Task name")
    merge_p.add_argument("--force", action="store_true", help="Merge even with uncommitted changes")
    merge_p.add_argument("--observer", help="Observer identity")

    close_p = task_sub.add_parser("close", help="Close a task (remove worktree)")
    close_p.add_argument("name", help="Task name")
    close_p.add_argument("--observer", help="Observer identity")

    stop_p = task_sub.add_parser("stop", help="Stop a running task worker")
    stop_p.add_argument("name", help="Task name")
    stop_p.add_argument("--observer", help="Observer identity")

    # note
    note_p = subparsers.add_parser("note", help="Emit a session note")
    note_p.add_argument("message", nargs="+", help="Note text")
    note_p.add_argument("--observer", help="Observer identity")

    # dashboard — arg parsing delegated to painted run_cli
    subparsers.add_parser("dashboard", help="Task dashboard")

    # project
    project_parser = subparsers.add_parser("project", help="Project coordination surface")
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)

    emit_p = project_sub.add_parser("emit", help="Emit a project fact")
    emit_p.add_argument("kind", help="Fact kind (decision, thread, plan)")
    emit_p.add_argument("parts", nargs="*", help="KEY=VALUE pairs and/or message")
    emit_p.add_argument("--observer", help="Observer identity")

    # status, log defined for argparse help; actual dispatch is pre-routed
    project_sub.add_parser("status", help="Show project status")
    project_sub.add_parser("log", help="Show project log")

    bridge_p = project_sub.add_parser("bridge", help="Bridge task ticks to project completions")
    bridge_p.add_argument("--observer", help="Observer identity")

    return parser


# -- Display command wrappers (run_cli) --


def _run_session_status(argv: list[str]) -> int:
    from painted import run_cli

    from strange_loops.commands.session import fetch_session_status
    from strange_loops.lenses.session import session_status_view
    from strange_loops.store import require_store, store_path

    def fetch():
        sp = store_path()
        require_store(sp)
        return fetch_session_status(sp)

    def render(ctx, data):
        return session_status_view(data, ctx.zoom, ctx.width)

    return run_cli(
        argv,
        fetch=fetch,
        render=render,
        prog="strange-loops session status",
        description="Show session status",
    )


def _run_session_log(argv: list[str]) -> int:
    from painted import run_cli

    from strange_loops.commands.session import fetch_session_log
    from strange_loops.lenses.session import session_log_view
    from strange_loops.store import parse_duration, require_store, store_path

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--since", default="7d")
    pre.add_argument("--kind", default=None)
    known, rest = pre.parse_known_args(argv)

    try:
        duration_secs = parse_duration(known.since)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    def fetch():
        sp = store_path()
        require_store(sp)
        return fetch_session_log(sp, duration_secs, known.kind)

    def render(ctx, data):
        return session_log_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="strange-loops session log",
        description="Show session log",
    )


def _run_task_status(argv: list[str]) -> int:
    from painted import run_cli

    from strange_loops.commands.task import fetch_task_status
    from strange_loops.lenses.task import task_status_view
    from strange_loops.store import store_path

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("name", nargs="?", default=None)
    known, rest = pre.parse_known_args(argv)

    def fetch():
        sp = store_path()
        return fetch_task_status(sp, known.name)

    def render(ctx, data):
        return task_status_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="strange-loops task status",
        description="Show task status",
    )


def _run_task_list(argv: list[str]) -> int:
    return _run_task_status(argv)


def _run_task_log(argv: list[str]) -> int:
    from strange_loops.store import parse_duration, require_store, store_path

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("name")
    pre.add_argument("--since", default="7d")
    pre.add_argument("--kind", default=None)
    pre.add_argument("--follow", action="store_true")
    known, rest = pre.parse_known_args(argv)

    try:
        duration_secs = parse_duration(known.since)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if known.follow:
        # Follow bypasses run_cli — uses direct polling + printing
        sp = store_path()
        try:
            require_store(sp)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        from engine import StoreReader

        from strange_loops.lifecycle import fold_task_state

        with StoreReader(sp) as reader:
            if fold_task_state(reader, known.name) is None:
                print(f"Error: Task '{known.name}' not found.", file=sys.stderr)
                return 1

        use_json = "--json" in rest
        from strange_loops.commands.task import follow_task_log

        return follow_task_log(sp, known.name, known.kind, use_json)

    from painted import run_cli

    from strange_loops.commands.task import fetch_task_log
    from strange_loops.lenses.task import task_log_view

    def fetch():
        sp = store_path()
        return fetch_task_log(sp, known.name, duration_secs, known.kind)

    def render(ctx, data):
        return task_log_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="strange-loops task log",
        description=f"Show log for task '{known.name}'",
    )


def _run_project_status(argv: list[str]) -> int:
    from painted import run_cli

    from strange_loops.commands.project import fetch_project_status, _project_store
    from strange_loops.lenses.project import project_status_view

    def fetch():
        sp = _project_store()
        return fetch_project_status(sp)

    def render(ctx, data):
        return project_status_view(data, ctx.zoom, ctx.width)

    return run_cli(
        argv,
        fetch=fetch,
        render=render,
        prog="strange-loops project status",
        description="Show project status",
    )


def _run_project_log(argv: list[str]) -> int:
    from strange_loops.store import parse_duration

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--since", default="7d")
    pre.add_argument("--kind", default=None)
    known, rest = pre.parse_known_args(argv)

    try:
        duration_secs = parse_duration(known.since)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from painted import run_cli

    from strange_loops.commands.project import fetch_project_log, _project_store
    from strange_loops.lenses.project import project_log_view

    def fetch():
        sp = _project_store()
        return fetch_project_log(sp, duration_secs, known.kind)

    def render(ctx, data):
        return project_log_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="strange-loops project log",
        description="Show project log",
    )


# -- Pre-dispatch table for display subcommands --

_DISPLAY_SUB = {
    ("session", "status"): _run_session_status,
    ("session", "log"): _run_session_log,
    ("task", "status"): _run_task_status,
    ("task", "list"): _run_task_list,
    ("task", "log"): _run_task_log,
    ("project", "status"): _run_project_status,
    ("project", "log"): _run_project_log,
}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Dashboard delegates to painted's run_cli for arg parsing + mode handling
    if argv and argv[0] == "dashboard":
        from strange_loops.commands.dashboard import run_dashboard

        return run_dashboard(argv[1:])

    # Display subcommands → run_cli
    if len(argv) >= 2 and (argv[0], argv[1]) in _DISPLAY_SUB:
        return _DISPLAY_SUB[(argv[0], argv[1])](argv[2:])

    # Action commands → argparse as before
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print("strange-loops 0.1.0")
        return 0

    if args.command == "session":
        from strange_loops.commands.session import cmd_session

        return cmd_session(args)

    if args.command == "task":
        from strange_loops.commands.task import cmd_task

        return cmd_task(args)

    if args.command == "note":
        from strange_loops.store import emit_fact, observer, store_path

        sp = store_path()
        obs = observer(args)
        message = " ".join(args.message)
        emit_fact(sp, "session.note", obs, {"message": message})

        from painted import show
        from painted.block import Block
        from painted.palette import current_palette

        p = current_palette()
        show(Block.text(f"[note] {message}", p.muted), file=sys.stdout)
        return 0

    if args.command == "project":
        from strange_loops.commands.project import cmd_project

        return cmd_project(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
