"""reader — personal reading intelligence."""

import argparse
import json
from pathlib import Path

from engine import load_vertex_program

from .config import resolve_vars

LOOPS_DIR = Path(__file__).resolve().parent.parent.parent / "loops"
FEEDS_LIST = LOOPS_DIR / "feeds.list"


def cmd_reactions(args: argparse.Namespace) -> int:
    program = load_vertex_program(
        LOOPS_DIR / "reactions.vertex",
        vars=resolve_vars(),
    )
    rounds = getattr(args, "rounds", 1)
    results = program.collect(rounds=rounds)
    if getattr(args, "json", False):
        print(json.dumps(results, default=str))
    else:
        for name, payload in results.items():
            count = payload.get("count", 0)
            items = payload.get("items", {})
            print(f"[{name}] {len(items)} items (count={count})")
    return 0


def cmd_feeds(args: argparse.Namespace) -> int:
    program = load_vertex_program(
        LOOPS_DIR / "feeds.vertex",
        vars=resolve_vars(),
    )
    rounds = getattr(args, "rounds", 1)
    results = program.collect(rounds=rounds)
    if getattr(args, "json", False):
        print(json.dumps(results, default=str))
    else:
        for name, payload in results.items():
            count = payload.get("count", 0)
            items = payload.get("items", {})
            print(f"[{name}] {len(items)} items (count={count})")
    return 0


def cmd_feeds_add(args: argparse.Namespace) -> int:
    """Append a feed to feeds.list."""
    kind = args.kind
    url = args.url

    # Read existing to check for duplicates
    if FEEDS_LIST.exists():
        lines = FEEDS_LIST.read_text().splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split(None, 1)
            if parts and parts[0] == kind:
                print(f"Feed '{kind}' already exists")
                return 1

    # Append
    with open(FEEDS_LIST, "a") as f:
        f.write(f"{kind} {url}\n")
    print(f"Added {kind}: {url}")
    return 0


def cmd_feeds_rm(args: argparse.Namespace) -> int:
    """Remove a feed from feeds.list by kind."""
    kind = args.kind

    if not FEEDS_LIST.exists():
        print(f"No feeds.list found")
        return 1

    lines = FEEDS_LIST.read_text().splitlines()
    kept: list[str] = []
    removed = False

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            parts = stripped.split(None, 1)
            if parts and parts[0] == kind:
                removed = True
                continue
        kept.append(line)

    if not removed:
        print(f"Feed '{kind}' not found")
        return 1

    FEEDS_LIST.write_text("\n".join(kept) + "\n")
    print(f"Removed {kind}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reader")
    sub = parser.add_subparsers(dest="command")

    rx = sub.add_parser("reactions", help="Gather reaction traces")
    rx.add_argument("--rounds", type=int, default=1)
    rx.add_argument("--json", action="store_true")

    fd = sub.add_parser("feeds", help="Gather subscribed feeds")
    fd_sub = fd.add_subparsers(dest="feeds_action")

    fd.add_argument("--rounds", type=int, default=1)
    fd.add_argument("--json", action="store_true")

    fd_add = fd_sub.add_parser("add", help="Add a feed")
    fd_add.add_argument("kind", help="Feed kind name")
    fd_add.add_argument("url", help="Feed URL")

    fd_rm = fd_sub.add_parser("rm", help="Remove a feed")
    fd_rm.add_argument("kind", help="Feed kind to remove")

    args = parser.parse_args(argv)
    if args.command == "reactions":
        return cmd_reactions(args)
    if args.command == "feeds":
        action = getattr(args, "feeds_action", None)
        if action == "add":
            return cmd_feeds_add(args)
        if action == "rm":
            return cmd_feeds_rm(args)
        return cmd_feeds(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
