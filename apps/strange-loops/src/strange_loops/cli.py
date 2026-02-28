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

    status_p = session_sub.add_parser("status", help="Show session status")
    status_p.add_argument("--json", action="store_true", help="JSON output")

    log_p = session_sub.add_parser("log", help="Show session log")
    log_p.add_argument("--since", default="7d", help="Time range (e.g. 7d, 24h)")
    log_p.add_argument("--kind", help="Filter by fact kind")
    log_p.add_argument("--json", action="store_true", help="JSONL output")

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

    tstatus_p = task_sub.add_parser("status", help="Show task status")
    tstatus_p.add_argument("name", nargs="?", help="Task name (omit for all)")
    tstatus_p.add_argument("--json", action="store_true", help="JSON output")

    tlist_p = task_sub.add_parser("list", help="List all tasks")
    tlist_p.add_argument("--json", action="store_true", help="JSON output")

    diff_p = task_sub.add_parser("diff", help="Show task worktree diff")
    diff_p.add_argument("name", help="Task name")

    merge_p = task_sub.add_parser("merge", help="Squash merge task branch")
    merge_p.add_argument("name", help="Task name")
    merge_p.add_argument("--force", action="store_true", help="Merge even with uncommitted changes")
    merge_p.add_argument("--observer", help="Observer identity")

    close_p = task_sub.add_parser("close", help="Close a task (remove worktree)")
    close_p.add_argument("name", help="Task name")
    close_p.add_argument("--observer", help="Observer identity")

    return parser


def main(argv: list[str] | None = None) -> int:
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

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
