"""Demo discovery and listing for the painted CLI."""

from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

from painted import Block, CliContext, Style, Zoom, join_vertical, print_block, run_cli, truncate

# ---------------------------------------------------------------------------
# DemoEntry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DemoEntry:
    name: str  # "fidelity"
    group: str  # "patterns"
    path: Path  # absolute path to .py file
    description: str  # first line of docstring
    invocations: tuple[str, ...] = ()  # "uv run ..." lines from docstring
    has_main: bool = True  # False for primitives/apps


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_CACHE: list[DemoEntry] | None = None

_GROUPS = ("primitives", "patterns", "apps", "examples")


def _find_demos_root() -> Path | None:
    """Walk up from package source to find demos/ directory."""
    # src/painted/_demo_cli.py -> src/painted -> src -> project root
    candidate = Path(__file__).resolve().parent.parent.parent / "demos"
    if candidate.is_dir():
        return candidate
    # Fallback: cwd
    candidate = Path.cwd() / "demos"
    if candidate.is_dir():
        return candidate
    return None


def _parse_demo(path: Path, group: str) -> DemoEntry | None:
    """Extract demo metadata via ast without executing the file."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, OSError):
        return None

    docstring = ast.get_docstring(tree) or ""
    first_line = docstring.split("\n")[0].strip() if docstring else path.stem

    # Extract invocation lines: lines starting with whitespace + "uv run"
    invocations: list[str] = []
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped.startswith("uv run"):
            invocations.append(stripped)

    # has_main: check for top-level def main or async def main
    has_main = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
        for node in ast.iter_child_nodes(tree)
    )

    return DemoEntry(
        name=path.stem,
        group=group,
        path=path.resolve(),
        description=first_line,
        invocations=tuple(invocations),
        has_main=has_main,
    )


def discover_demos() -> list[DemoEntry]:
    """Find all demos, sorted by group then name. Cached."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    root = _find_demos_root()
    if root is None:
        _CACHE = []
        return _CACHE

    entries: list[DemoEntry] = []
    for group in _GROUPS:
        group_dir = root / group
        if not group_dir.is_dir():
            continue
        for path in sorted(group_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            entry = _parse_demo(path, group)
            if entry is not None:
                entries.append(entry)

    # Also discover tour.py at demos root
    tour_path = root / "tour.py"
    if tour_path.exists():
        entry = _parse_demo(tour_path, "")
        if entry is not None:
            entries.append(entry)

    _CACHE = entries
    return _CACHE


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_PLAIN = Style()
_DIM = Style(dim=True)
_BOLD = Style(bold=True)


def render_demo_list(ctx: CliContext, entries: list[DemoEntry]) -> Block:
    """Render demo list at the requested zoom level."""
    # Filter out tour — it has its own command
    demos = [e for e in entries if e.group]

    if ctx.zoom == Zoom.MINIMAL:
        # One name per line, for scripting
        names = "\n".join(e.name for e in demos if e.has_main)
        return Block.text(names, _PLAIN) if names else Block.empty(0, 0)

    # Group demos
    groups: dict[str, list[DemoEntry]] = {}
    for e in demos:
        groups.setdefault(e.group, []).append(e)

    # Find max name width for alignment
    max_name = max((len(e.name) for e in demos), default=10)

    blocks: list[Block] = []
    for group in _GROUPS:
        group_entries = groups.get(group, [])
        if not group_entries:
            continue

        if blocks:
            blocks.append(Block.text(" ", _PLAIN))  # spacer between groups

        blocks.append(Block.text(group, _BOLD))
        for e in group_entries:
            suffix = "" if e.has_main else "  (run directly)"
            line = f"  {e.name:<{max_name}}  {e.description}{suffix}"
            blocks.append(Block.text(line, _PLAIN))

            # DETAILED+: show invocation examples
            if ctx.zoom >= Zoom.DETAILED and e.invocations:
                for inv in e.invocations:
                    blocks.append(Block.text(f"    {inv}", _DIM))

    result = join_vertical(*blocks) if blocks else Block.empty(0, 0)
    return truncate(result, ctx.width)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def list_demos(args: list[str]) -> int:
    """List available demos via run_cli."""
    return run_cli(
        args,
        render=render_demo_list,
        fetch=discover_demos,
        description="List available painted demos",
        prog="painted demos",
    )


def run_demo(name: str, args: list[str]) -> int:
    """Run a demo by name, forwarding remaining args."""
    entries = discover_demos()
    match = next((e for e in entries if e.name == name), None)

    if match is None:
        # Suggest similar names
        all_names = [e.name for e in entries if e.has_main]
        suggestions = [n for n in all_names if name in n or n in name]
        msg = f"Unknown demo: {name}"
        if suggestions:
            msg += f"\n\nDid you mean: {', '.join(suggestions)}?"
        else:
            msg += f"\n\nAvailable: {', '.join(all_names)}"
        print_block(Block.text(msg, Style(fg="red")))
        return 1

    if not match.has_main:
        print_block(
            Block.text(f"Run directly: uv run {match.path}", _DIM),
        )
        return 1

    # Import and run
    spec = importlib.util.spec_from_file_location(f"demo_{match.name}", match.path)
    if spec is None or spec.loader is None:
        print_block(Block.text(f"Cannot load: {match.path}", Style(fg="red")))
        return 1

    mod_name = f"demo_{match.name}"
    module = importlib.util.module_from_spec(spec)
    saved_argv = sys.argv[:]
    saved_mod = sys.modules.get(mod_name)
    try:
        sys.argv = [str(match.path)] + args
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        main_fn = getattr(module, "main", None)
        if main_fn is None:
            print_block(Block.text(f"No main() in {match.path}", Style(fg="red")))
            return 1
        import asyncio
        import inspect

        if inspect.iscoroutinefunction(main_fn):
            result = asyncio.run(main_fn())
        else:
            result = main_fn()
        return result if isinstance(result, int) else 0
    finally:
        sys.argv = saved_argv
        if saved_mod is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = saved_mod
