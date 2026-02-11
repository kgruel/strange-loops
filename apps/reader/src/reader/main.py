"""reader — personal reading intelligence."""

import argparse
import json
from pathlib import Path

from engine import load_vertex_program

from .config import resolve_vars

LOOPS_DIR = Path(__file__).resolve().parent.parent.parent / "loops"


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reader")
    sub = parser.add_subparsers(dest="command")

    rx = sub.add_parser("reactions", help="Gather reaction traces")
    rx.add_argument("--rounds", type=int, default=1)
    rx.add_argument("--json", action="store_true")

    fd = sub.add_parser("feeds", help="Gather subscribed feeds")
    fd.add_argument("--rounds", type=int, default=1)
    fd.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "reactions":
        return cmd_reactions(args)
    if args.command == "feeds":
        return cmd_feeds(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
