"""Entry point for python -m painted."""

from __future__ import annotations

import sys

from painted import Block, Style, join_vertical, print_block


_PLAIN = Style()
_USAGE = join_vertical(
    Block.text("painted — Terminal UI framework", Style(bold=True)),
    Block.text(" ", _PLAIN),
    Block.text("Commands", Style(bold=True)),
    Block.text("  demos [flags]              List available demos", _PLAIN),
    Block.text("  demos <name> [flags]       Run a demo by name", _PLAIN),
    Block.text(" ", _PLAIN),
    Block.text("  tour [flags]               Interactive tour", _PLAIN),
    Block.text(" ", _PLAIN),
    Block.text("Use painted <command> --help for details.", Style(dim=True)),
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print_block(_USAGE)
        return 0

    command = args[0]

    if command in ("demos", "demo"):
        return _demo_dispatch(args[1:])

    if command == "tour":
        return _tour_dispatch(args[1:])

    print_block(Block.text(f"Unknown command: {command}", Style(fg="red")))
    print_block(_USAGE)
    return 1


def _demo_dispatch(args: list[str]) -> int:
    from painted._demo_cli import list_demos, run_demo

    # No args or flags only → list demos
    if not args or args[0].startswith("-"):
        return list_demos(args)

    sub = args[0]

    # Explicit "list" subcommand
    if sub == "list":
        return list_demos(args[1:])

    # Legacy "run" subcommand
    if sub == "run":
        if len(args) < 2:
            print_block(Block.text("Usage: painted demos <name> [flags]", Style(dim=True)))
            return 1
        return run_demo(args[1], args[2:])

    # Otherwise, first arg is a demo name
    return run_demo(sub, args[1:])


def _tour_dispatch(args: list[str]) -> int:
    import asyncio
    import importlib.util

    from painted._demo_cli import _find_demos_root

    root = _find_demos_root()
    if root is None:
        print_block(Block.text("Cannot find demos/ directory", Style(fg="red")))
        return 1

    tour_path = root / "tour.py"
    if not tour_path.exists():
        print_block(Block.text(f"Tour not found: {tour_path}", Style(fg="red")))
        return 1

    spec = importlib.util.spec_from_file_location("demo_tour", tour_path)
    if spec is None or spec.loader is None:
        print_block(Block.text(f"Cannot load: {tour_path}", Style(fg="red")))
        return 1

    module = importlib.util.module_from_spec(spec)
    saved_argv = sys.argv[:]
    saved_mod = sys.modules.get("demo_tour")
    try:
        sys.argv = [str(tour_path)] + args
        sys.modules["demo_tour"] = module
        spec.loader.exec_module(module)
        asyncio.run(module.main())
        return 0
    finally:
        sys.argv = saved_argv
        if saved_mod is None:
            sys.modules.pop("demo_tour", None)
        else:
            sys.modules["demo_tour"] = saved_mod


if __name__ == "__main__":
    sys.exit(main())
