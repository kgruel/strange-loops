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

    # Placeholder — commands will be added as they're built
    subparsers.add_parser("version", help="Show version")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print("strange-loops 0.1.0")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
