"""CLI for the loops runtime.

Observer operations (verb-first — resolves vertex from context):
    loops fold                      Show folded state (local vertex)
    loops fold project              Show folded state (named vertex)
    loops stream                    Show event stream
    loops stream project "auth"     Stream named vertex, search query
    loops emit decision topic=x     Emit to local vertex
    loops emit project decision     Emit to named vertex
    loops close thread my-thread    Resolve thread, capture produced artifacts

Observer operations (vertex-first — backward compat):
    loops <vertex>                  Show folded state (default)
    loops <vertex> fold             Show folded state
    loops <vertex> stream           Show event stream
    loops <vertex> stream <query>   Search events (FTS5)
    loops <vertex> emit <kind> ...  Inject a fact

Root commands:
    loops ls                        List vertices
    loops store [file]              Inspect store (name, path, or .db)
    loops start <file>              Run a .vertex file (one round, rendered)
    loops run <file>                Execute a .loop or .vertex file
    loops validate <file>           Validate syntax and flow
    loops compile <file>            Show compiled structure
    loops test <file> --input <f>   Run parse pipeline against sample input
    loops init [name]               Initialize vertex
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


def _err(msg: str, file: TextIO | None = None) -> None:
    """Show an error message through painted."""
    from painted import show, Block
    from painted.palette import current_palette

    show(Block.text(msg, current_palette().error), file=file or sys.stderr)


def _msg(msg: str, file: TextIO | None = None) -> None:
    """Show a success/info message through painted."""
    from painted import show, Block
    from painted.palette import current_palette

    show(Block.text(msg, current_palette().success), file=file or sys.stdout)


def _parse_vars(raw: list[str]) -> dict[str, str]:
    """Parse ['KEY=VALUE', ...] into {key: value}."""
    result: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"Invalid --var format (expected KEY=VALUE): {item!r}")
        key, _, value = item.partition("=")
        result[key] = value
    return result


def loops_home() -> Path:
    """Resolve the loops config directory."""
    if env := os.environ.get("LOOPS_HOME"):
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "loops"


_ROOT_VERTEX = """\
// Root vertex — discovers all .vertex files under this directory
discover "./**/*.vertex"
"""

# App registry — registered apps get `loops <app> <command>` dispatch
_APPS: dict[str, str] = {
    "siftd": "siftd_loops",
}


def _find_local_vertex() -> Path | None:
    """Find a .vertex file in .loops/ or cwd. Returns first match or None."""
    # Prefer .loops/.vertex (workspace root convention)
    loops_dir = Path.cwd() / ".loops"
    dotvertex = loops_dir / ".vertex"
    if dotvertex.exists():
        return dotvertex
    # Fall back to .loops/*.vertex (named vertex)
    if loops_dir.is_dir():
        matches = sorted(loops_dir.glob("*.vertex"))
        if matches:
            return matches[0]
    # Fall back to cwd (existing projects)
    matches = sorted(Path.cwd().glob("*.vertex"))
    return matches[0] if matches else None


_AGGREGATION_VERTEX = """\
// {name} — aggregation vertex, discovers local instances
name "{name}"

discover "./instances/**/*.vertex"

loops {{
  decision {{ fold {{ items "by" "topic" }} }}
  thread   {{ fold {{ items "by" "name" }} }}
  change   {{ fold {{ items "collect" 20 }} }}
  task     {{ fold {{ items "by" "name" }} }}
}}
"""


def _extract_loops_text(content: str) -> str | None:
    """Extract the ``loops { ... }`` block from raw vertex file text.

    Uses brace-matching so nested ``{ }`` inside loop definitions are handled.
    Returns the raw text including the ``loops`` keyword, or ``None``.
    """
    idx = content.find("\nloops {")
    if idx == -1:
        if content.startswith("loops {"):
            idx = 0
        else:
            return None
    else:
        idx += 1  # skip the leading newline
    depth = 0
    start = idx
    i = content.index("{", idx)
    for i in range(i, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return content[start : i + 1]
    return None


def _find_source_vertex(name: str) -> str | None:
    """Find an existing instance vertex to use as source for init.

    Priority:
    1. If the aggregation vertex itself declares a loops block, build a
       synthetic instance from it (name + store + loops).
    2. Fall back to first sibling instance under instances/.
    3. Direct config-level instance (has store, not aggregation).
    """
    home = loops_home()
    config_dir = home / name
    if not config_dir.exists():
        return None
    leaf = Path(name).name
    # Try aggregation vertex's own loops block first
    vertex_file = config_dir / f"{leaf}.vertex"
    if vertex_file.exists():
        agg_content = vertex_file.read_text()
        loops_text = _extract_loops_text(agg_content)
        if loops_text is not None:
            return f'name "{leaf}"\nstore "./data/{leaf}.db"\n\n{loops_text}\n'
    # Aggregation pattern: look in instances/
    instances_dir = config_dir / "instances"
    if instances_dir.is_dir():
        matches = sorted(instances_dir.glob("**/*.vertex"))
        if matches:
            return matches[0].read_text()
    # Direct instance at config level
    if vertex_file.exists():
        content = vertex_file.read_text()
        if "store" in content:
            return content
    return None


def _init_local_vertex(name: str, source_name: str | None = None) -> Path | None:
    """Create a vertex + data dir in .loops/ from an existing instance. Returns vertex path."""
    import re

    source = _find_source_vertex(source_name or name)
    if source is None:
        return None
    # Stamp a local copy with the target name and store path
    content = re.sub(
        r'^name ".*"', f'name "{name}"', source, count=1, flags=re.MULTILINE
    )
    content = re.sub(
        r'^store "./data/.*\.db"',
        f'store "./data/{name}.db"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    loops_dir = Path.cwd() / ".loops"
    loops_dir.mkdir(exist_ok=True)
    vertex_path = loops_dir / f"{name}.vertex"
    if not vertex_path.exists():
        vertex_path.write_text(content)
    data_dir = loops_dir / "data"
    data_dir.mkdir(exist_ok=True)
    return vertex_path


def _init_config_vertex(name: str) -> Path:
    """Create an aggregation vertex + instances dir in LOOPS_HOME. Returns vertex path."""
    home = loops_home()
    leaf = Path(name).name
    config_dir = home / name
    config_dir.mkdir(parents=True, exist_ok=True)
    vertex_path = config_dir / f"{leaf}.vertex"
    if not vertex_path.exists():
        vertex_path.write_text(_AGGREGATION_VERTEX.format(name=leaf))
    (config_dir / "instances").mkdir(exist_ok=True)
    return vertex_path


def _register_with_config(name: str, project_dir: Path) -> Path | None:
    """Register a project directory with the config-level vertex.

    Creates a symlink at LOOPS_HOME/{name}/instances/{slug} -> project_dir.
    Returns the symlink path, or None if no config-level vertex exists.
    """
    home = loops_home()
    config_dir = home / name
    if not config_dir.exists():
        return None
    instances_dir = config_dir / "instances"
    instances_dir.mkdir(exist_ok=True)
    slug = project_dir.name
    link = instances_dir / slug
    if link.exists():
        if link.resolve() == project_dir.resolve():
            return link  # already registered
        _err(f"Instance '{slug}' already registered to {link.resolve()}")
        return None
    link.symlink_to(project_dir)
    return link


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a loops config directory, config vertex, or local vertex."""
    name = getattr(args, "name", None)
    template = getattr(args, "template", None)

    # Slashed name → config-level aggregation vertex
    if name and "/" in name:
        vertex_path = _init_config_vertex(name)
        _msg(f"Created {vertex_path}")
        return 0

    # Bare name → local instance from existing config vertex + register
    if name:
        vertex_path = _init_local_vertex(name, source_name=template)
        if vertex_path is None:
            _err(f"No existing vertex found for '{template or name}'")
            return 1
        _msg(f"Created {vertex_path}")
        link = _register_with_config(name, Path.cwd())
        if link is not None:
            _msg(f"Registered {Path.cwd()} → {link}")
        return 0

    # No name + template → local instance in cwd
    if template:
        vertex_path = _init_local_vertex(template)
        if vertex_path is None:
            _err(f"No existing vertex found for '{template}'")
            return 1
        _msg(f"Created {vertex_path}")
        return 0

    # No name + no template → .vertex in LOOPS_HOME
    home = loops_home()
    root = home / ".vertex"
    # Backwards compat: accept existing root.vertex
    legacy_root = home / "root.vertex"
    if root.exists() or legacy_root.exists():
        existing = root if root.exists() else legacy_root
        from painted import show, Block
        from painted.palette import current_palette

        show(
            Block.text(f"Already initialized: {existing}", current_palette().muted),
            file=sys.stdout,
        )
        return 0
    home.mkdir(parents=True, exist_ok=True)
    root.write_text(_ROOT_VERTEX)
    _msg(f"Created {root}")
    return 0


def _resolve_vertex_path(file_arg: str | None) -> Path | None:
    """Resolve a vertex file path, defaulting to LOOPS_HOME/.vertex."""
    if file_arg is not None:
        return Path(file_arg)
    home = loops_home()
    root = home / ".vertex"
    if root.exists():
        return root
    # Backwards compat: accept existing root.vertex
    legacy = home / "root.vertex"
    if legacy.exists():
        return legacy
    _err(f"Error: {root} not found. Run 'loops init' first.")
    return None


def _run_validate(argv: list[str]) -> int:
    """Run validate command via painted CLI harness."""
    from painted import run_cli
    from painted.fidelity import HelpArg
    from lang import parse_loop_file, parse_vertex_file, validate
    from .lenses.validate import validate_view

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("files", nargs="*")
    known, rest = pre.parse_known_args(argv)

    # Capture fetch result for exit code check
    fetch_result: list[dict] = []

    def fetch():
        files = known.files
        if not files:
            cwd = Path.cwd()
            files = sorted(
                str(p) for p in cwd.rglob("*") if p.suffix in (".loop", ".vertex")
            )

        results = []
        checked = 0
        errors = 0

        for file in files:
            path = Path(file)
            if path.suffix not in (".loop", ".vertex"):
                continue

            if not path.exists():
                results.append(
                    {
                        "path": str(path),
                        "valid": False,
                        "error": f"{path} does not exist",
                    }
                )
                errors += 1
                continue

            try:
                if path.suffix == ".loop":
                    ast = parse_loop_file(path)
                else:
                    ast = parse_vertex_file(path)
                validate(ast)
                results.append({"path": str(path), "valid": True, "error": None})
                checked += 1
            except Exception as e:
                results.append({"path": str(path), "valid": False, "error": str(e)})
                errors += 1

        data = {"results": results, "checked": checked, "errors": errors}
        fetch_result.append(data)
        return data

    def render(ctx, data):
        return validate_view(data, ctx.zoom, ctx.width)

    rc = run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops validate",
        description="Validate .loop or .vertex files",
        help_args=[
            HelpArg(
                "files", "Files to validate (default: all in cwd)", positional=True
            ),
        ],
    )
    if rc != 0:
        return rc
    # Preserve exit code: 1 if validation errors or no files found
    if fetch_result:
        data = fetch_result[0]
        if data["errors"] > 0 or data["checked"] == 0:
            return 1
    return 0


def _run_test(argv: list[str]) -> int:
    """Run test command via painted CLI harness."""
    from painted import run_cli
    from painted.fidelity import HelpArg
    from atoms import run_parse
    from lang import parse_loop_file, validate_loop
    from engine import compile_loop
    from .lenses.test import test_view

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("file")
    pre.add_argument("--input", "-i", default=None)
    known, rest = pre.parse_known_args(argv)

    path = Path(known.file)
    if not path.exists():
        _err(f"Error: {path} does not exist")
        return 1

    if path.suffix != ".loop":
        _err("Error: test command only works with .loop files")
        return 1

    def fetch():
        ast = parse_loop_file(path)
        validate_loop(ast)
        source = compile_loop(ast)

        if source.parse is None:
            return {"results": [], "skipped": 0, "warning": "no parse pipeline defined"}

        if known.input:
            input_path = Path(known.input)
            if not input_path.exists():
                raise FileNotFoundError(f"{input_path} does not exist")
            lines = input_path.read_text().splitlines()
        else:
            lines = sys.stdin.read().splitlines()

        results = []
        skipped = 0

        for line in lines:
            result = run_parse(line, source.parse)
            if result is None:
                skipped += 1
            else:
                results.append(result)

        return {"results": results, "skipped": skipped}

    def render(ctx, data):
        return test_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops test",
        description="Test parse pipeline against sample input",
        help_args=[
            HelpArg("file", "Loop file to test", positional=True),
            HelpArg("--input", "Input file (default: stdin)"),
        ],
    )


def _run_run(argv: list[str]) -> int:
    """Run command via painted CLI harness — execute a .loop or .vertex file."""
    from painted import run_cli
    from painted.fidelity import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("file", nargs="?", default=None)
    pre.add_argument("--limit", "-n", type=int, default=None)
    pre.add_argument("--rounds", "-r", type=int, default=1)
    pre.add_argument("--daemon", "-d", action="store_true", default=False)
    pre.add_argument("--var", action="append", default=[])
    known, rest = pre.parse_known_args(argv)

    resolved = _resolve_vertex_path(known.file)
    if resolved is None:
        return 1
    path = resolved.resolve()
    if not path.exists():
        _err(f"Error: {path} does not exist")
        return 1

    if path.suffix == ".loop":
        return _run_run_loop(path, known, rest)
    elif path.suffix == ".vertex":
        return _run_run_vertex(path, known, rest)
    else:
        _err(f"Error: run expects a .loop or .vertex file, got {path.suffix}")
        return 1


def _run_run_loop(path: Path, known, rest: list[str]) -> int:
    """Execute a .loop file through run_cli."""
    from painted import run_cli
    from painted.fidelity import HelpArg
    from lang import parse_loop_file, validate_loop
    from engine import compile_loop
    from .lenses.run import run_facts_view

    ast = parse_loop_file(path)
    validate_loop(ast)
    source = compile_loop(ast)
    limit = known.limit

    def fetch():
        collected: list[dict] = []

        async def _collect():
            count = 0
            async for fact in source.stream():
                collected.append(
                    {
                        "kind": fact.kind,
                        "ts": fact.ts,
                        "payload": fact.payload,
                        "observer": fact.observer,
                        "origin": fact.origin,
                    }
                )
                count += 1
                if limit and count >= limit:
                    break

        asyncio.run(_collect())
        return collected

    async def fetch_stream():
        accumulated: list[dict] = []
        count = 0
        async for fact in source.stream():
            accumulated.append(
                {
                    "kind": fact.kind,
                    "ts": fact.ts,
                    "payload": fact.payload,
                    "observer": fact.observer,
                    "origin": fact.origin,
                }
            )
            count += 1
            yield list(accumulated)
            if limit and count >= limit:
                break

    def render(ctx, data):
        return run_facts_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        fetch_stream=fetch_stream,
        render=render,
        prog="loops run",
        description=f"Stream facts from {path.name}",
        help_args=[
            HelpArg("file", "Loop or vertex file", positional=True),
            HelpArg("--limit", "Max facts to collect"),
            HelpArg("--rounds", "Number of rounds", default="1"),
            HelpArg("--daemon", "Run continuously"),
            HelpArg("--var", "Set variable KEY=VALUE"),
        ],
    )


def _run_run_vertex(path: Path, known, rest: list[str]) -> int:
    """Execute a .vertex file through run_cli."""
    from painted import run_cli
    from painted.fidelity import HelpArg
    from engine import load_vertex_program
    from .lenses.run import run_ticks_view

    vars = _parse_vars(known.var)
    program = load_vertex_program(path, vars=vars or None)

    if not program.sources:
        _err("Error: no sources configured")
        return 1

    daemon = known.daemon
    rounds = known.rounds
    if daemon or rounds == 0:
        rounds = None

    def log_error(fact):
        payload = dict(fact.payload) if hasattr(fact.payload, "items") else fact.payload
        _err(f"[ERROR] {fact.observer}: {payload}")

    from painted import show, Block
    from painted.palette import current_palette

    show(
        Block.text(
            f"Started {program.vertex.name}: {len(program.sources)} sources",
            current_palette().muted,
        ),
        file=sys.stderr,
    )

    def fetch():
        collected: list[dict] = []

        async def _collect():
            completed_rounds = 0
            if rounds is not None:
                seen: set[str] = set()
                expected = set(program.expected_ticks)

            async for tick in program.run(on_error=log_error):
                collected.append(
                    {
                        "name": tick.name,
                        "ts": tick.ts,
                        "payload": tick.payload,
                        "origin": getattr(tick, "origin", ""),
                    }
                )
                if rounds is not None:
                    seen.add(tick.name)
                    if seen >= expected:
                        completed_rounds += 1
                        if completed_rounds >= rounds:
                            break
                        seen = set()

        asyncio.run(_collect())
        return collected

    async def fetch_stream():
        accumulated: list[dict] = []
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        completed_rounds = 0
        if rounds is not None:
            seen: set[str] = set()
            expected = set(program.expected_ticks)

        async for tick in program.run(on_error=log_error):
            if stop.is_set():
                break
            accumulated.append(
                {
                    "name": tick.name,
                    "ts": tick.ts,
                    "payload": tick.payload,
                    "origin": getattr(tick, "origin", ""),
                }
            )
            yield list(accumulated)
            if rounds is not None:
                seen.add(tick.name)
                if seen >= expected:
                    completed_rounds += 1
                    if completed_rounds >= rounds:
                        break
                    seen = set()

    def render(ctx, data):
        return run_ticks_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        fetch_stream=fetch_stream,
        render=render,
        prog="loops run",
        description=f"Run vertex {program.vertex.name}",
        help_args=[
            HelpArg("file", "Loop or vertex file", positional=True),
            HelpArg("--limit", "Max facts to collect"),
            HelpArg("--rounds", "Number of rounds", default="1"),
            HelpArg("--daemon", "Run continuously"),
            HelpArg("--var", "Set variable KEY=VALUE"),
        ],
    )


def _run_compile(argv: list[str]) -> int:
    """Run compile command via painted CLI harness."""
    from painted import run_cli
    from painted.fidelity import HelpArg
    from lang import parse_loop_file, parse_vertex_file, validate
    from engine import compile_loop, compile_vertex
    from .lenses.compile import compile_view

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("file")
    known, rest = pre.parse_known_args(argv)

    path = Path(known.file)
    if not path.exists():
        _err(f"Error: {path} does not exist")
        return 1

    def fetch():
        abs_path = str(path.resolve())
        if path.suffix == ".loop":
            ast = parse_loop_file(path)
            validate(ast)
            source = compile_loop(ast)
            data: dict = {
                "type": "loop",
                "name": path.name,
                "source_path": abs_path,
                "command": source.command,
                "kind": source.kind,
                "observer": source.observer,
                "every": source.every,
                "format": source.format,
                "parse": [],
            }
            if source.parse:
                data["parse"] = [f"{type(op).__name__}: {op}" for op in source.parse]
            return data

        elif path.suffix == ".vertex":
            ast = parse_vertex_file(path)
            validate(ast)
            specs = compile_vertex(ast)
            data = {
                "type": "vertex",
                "name": ast.name,
                "source_path": abs_path,
                "store": ast.store,
                "discover": ast.discover,
                "emit": ast.emit,
                "specs": {},
                "routes": dict(ast.routes) if ast.routes else {},
            }
            for name, spec in specs.items():
                data["specs"][name] = {
                    "state_fields": [f.name for f in spec.state_fields],
                    "folds": [f"{type(fold).__name__}: {fold}" for fold in spec.folds],
                    "boundary": spec.boundary.kind if spec.boundary else None,
                }
            return data

        else:
            raise ValueError(f"Unknown file type: {path.suffix}")

    def render(ctx, data):
        return compile_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops compile",
        description="Show compiled structure",
        help_args=[
            HelpArg("file", "Loop or vertex file to compile", positional=True),
        ],
    )


def _run_start(argv: list[str]) -> int:
    """Run start command via painted CLI harness."""
    from painted import run_cli
    from painted.fidelity import HelpArg
    from engine import load_vertex_program
    from .lenses.start import start_view

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("file", nargs="?", default=None)
    pre.add_argument("--var", action="append", default=[], metavar="KEY=VALUE")
    known, rest = pre.parse_known_args(argv)

    resolved = _resolve_vertex_path(known.file)
    if resolved is None:
        return 1
    path = resolved
    if not path.exists():
        _err(f"Error: {path} does not exist")
        return 1
    if path.suffix != ".vertex":
        _err("Error: start command only works with .vertex files")
        return 1

    vars = _parse_vars(known.var)
    program = load_vertex_program(path, vars=vars or None)

    if not program.sources:
        from painted import show, Block
        from painted.palette import current_palette

        show(
            Block.text(
                "Warning: no sources discovered or configured",
                current_palette().warning,
            ),
            file=sys.stderr,
        )
        return 0

    from painted import show, Block
    from painted.palette import current_palette

    show(
        Block.text(
            f"Starting {program.vertex.name} with {len(program.sources)} source(s)...",
            current_palette().muted,
        ),
        file=sys.stderr,
    )

    def fetch():
        return program.collect(rounds=1)

    def render(ctx, data):
        return start_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops start",
        description="Run a .vertex file (one round)",
        help_args=[
            HelpArg("file", "Vertex file to start", positional=True),
            HelpArg("--var", "Set variable KEY=VALUE"),
        ],
    )


def _parse_emit_parts(parts: list[str]) -> dict[str, str]:
    """Parse emit args into a payload dict.

    Any KEY=VALUE tokens become payload entries. Any trailing non-key=value
    tokens are joined with spaces into payload["message"].
    """
    payload: dict[str, str] = {}
    message_parts: list[str] = []

    for item in parts:
        if "=" in item:
            key, _, value = item.partition("=")
            if key.isidentifier():
                payload[key] = value
                continue
        message_parts.append(item)

    if message_parts:
        payload["message"] = " ".join(message_parts)

    return payload


def _resolve_writable_vertex(vertex_path: Path) -> Path | None:
    """Resolve to the vertex that owns the writable store.

    For vertices with a store, returns the path as-is.
    For combine vertices, follows the chain to find the first constituent
    with a store.  Returns None if no writable vertex is found.
    """
    from lang import parse_vertex_file
    from lang.population import resolve_vertex

    ast = parse_vertex_file(vertex_path)

    if ast.store is not None:
        return vertex_path

    # Follow combine → first entry's vertex
    if ast.combine:
        ref_path = resolve_vertex(ast.combine[0].name, loops_home())
        if not ref_path.is_absolute():
            ref_path = (vertex_path.parent / ref_path).resolve()
        if ref_path.exists():
            return _resolve_writable_vertex(ref_path)

    return None


def _resolve_vertex_store_path(vertex_path: Path) -> Path | None:
    """Resolve store path from a vertex file. Returns None if no store configured.

    For combinatorial vertices (combine block, no store), follows the first
    combine entry to find the writable store.
    """
    from lang import parse_vertex_file
    from lang.population import resolve_vertex

    ast = parse_vertex_file(vertex_path)

    if ast.store is not None:
        store_path = Path(ast.store)
        if not store_path.is_absolute():
            store_path = (vertex_path.parent / store_path).resolve()
        return store_path

    # Follow combine → first entry's store
    if ast.combine:
        ref_path = resolve_vertex(ast.combine[0].name, loops_home())
        if not ref_path.is_absolute():
            ref_path = (vertex_path.parent / ref_path).resolve()
        if ref_path.exists():
            return _resolve_vertex_store_path(ref_path)

    return None


def _resolve_named_store(name: str) -> Path:
    """Resolve a vertex name to its store path via resolve_vertex + store extraction."""
    from lang.population import resolve_vertex

    vertex_path = resolve_vertex(name, loops_home()).resolve()
    if not vertex_path.exists():
        raise FileNotFoundError(f"Vertex not found: {vertex_path}")
    store_path = _resolve_vertex_store_path(vertex_path)
    if store_path is None:
        raise FileNotFoundError(f"Vertex '{name}' has no store configured")
    return store_path


def _resolve_named_vertex(name: str) -> Path:
    """Resolve a vertex name to its .vertex file path."""
    from lang.population import resolve_vertex

    vertex_path = resolve_vertex(name, loops_home()).resolve()
    if not vertex_path.exists():
        raise FileNotFoundError(f"Vertex not found: {vertex_path}")
    return vertex_path


def _resolve_vertex_for_dispatch(name: str) -> Path | None:
    """Try to resolve a name as a vertex for CLI dispatch. Returns None to fall through.

    Resolution chain (local instance wins over config template):
    1. Skip path-like strings — those are file args for root commands
    2. Local: .loops/name.vertex
    3. Local: cwd/name.vertex
    4. Config-level: LOOPS_HOME/name/name.vertex
    """
    if name.endswith(".vertex") or name.startswith("./") or name.startswith("/"):
        return None

    # Local .loops/
    local = Path.cwd() / ".loops" / f"{name}.vertex"
    if local.exists():
        return local.resolve()

    # Local cwd
    local = Path.cwd() / f"{name}.vertex"
    if local.exists():
        return local.resolve()

    # Config-level resolution
    from lang.population import resolve_vertex

    candidate = resolve_vertex(name, loops_home())
    if candidate.exists():
        return candidate.resolve()

    return None


def cmd_emit(args: argparse.Namespace, *, vertex_path: Path | None = None) -> int:
    """Inject a fact directly into a vertex store (or print in --dry-run)."""
    from atoms import Fact
    from lang import parse_vertex_file
    from lang.population import (
        list_file_header,
        list_file_read,
        resolve_template,
        resolve_vertex,
    )
    from loops.commands.identity import resolve_observer, validate_emit
    from loops.pop_store import (
        POP_ADD_KIND,
        POP_RM_KIND,
        pop_materialize_list,
        pop_store_has_facts,
    )
    from painted import show, Block
    from painted.palette import current_palette

    p = current_palette()

    # Resolve observer from flag → env → .vertex declaration
    observer = resolve_observer(args.observer)

    kind = args.kind
    parts = list(args.parts or [])
    template_qualifier = None

    if vertex_path is not None:
        # Vertex-first dispatch: vertex already resolved, no ambiguity
        pass
    else:
        # Legacy path: resolve vertex from args
        vertex_ref = args.vertex

        def _is_path_like(s: str) -> bool:
            return s.endswith(".vertex") or s.startswith("./") or s.startswith("/")

        if vertex_ref is not None:
            if "/" in vertex_ref and not _is_path_like(vertex_ref):
                vertex_ref, template_qualifier = vertex_ref.split("/", 1)

            # Try resolving as vertex
            candidate = resolve_vertex(vertex_ref, loops_home()).resolve()
            if candidate.exists():
                vertex_path = candidate
            elif _is_path_like(vertex_ref):
                # Explicit path that doesn't exist — error
                show(Block.text(f"Error: {candidate} not found", p.error), file=sys.stderr)
                return 1
            else:
                # vertex_ref doesn't resolve — reinterpret as kind, shift args
                parts = [kind] + parts
                kind = vertex_ref
                vertex_ref = None

        if vertex_ref is None:
            # No vertex: try local
            local = _find_local_vertex()
            if local is not None:
                vertex_path = local.resolve()
            else:
                show(
                    Block.text(
                        "No vertex found. Run 'loops init' first.", p.error
                    ),
                    file=sys.stderr,
                )
                return 1

    payload = _parse_emit_parts(parts)

    # Thread auto-tagging: inherit LOOPS_THREAD as default thread association.
    # Priority: explicit thread= in payload > LOOPS_THREAD env > none.
    if "thread" not in payload:
        thread_hint = os.environ.get("LOOPS_THREAD", "")
        if thread_hint:
            payload["thread"] = thread_hint

    # Validate observer + kind against declaration chain
    if vertex_path is not None:
        err = validate_emit(vertex_path, observer, kind)
        if err is not None:
            show(Block.text(f"Error: {err}", p.error), file=sys.stderr)
            return 1

    ts = datetime.now(timezone.utc).timestamp()
    fact = Fact(
        kind=kind,
        ts=ts,
        payload=payload,
        observer=observer,
        origin="",
    )

    if args.dry_run:
        show(
            Block.text(
                json.dumps(fact.to_dict(), sort_keys=True, default=str), p.muted
            ),
            file=sys.stdout,
        )
        return 0

    try:
        # Resolve to the vertex that owns the writable store (follow combine)
        writable_path = _resolve_writable_vertex(vertex_path)
        if writable_path is None:
            show(
                Block.text("Error: vertex has no store configured", p.error),
                file=sys.stderr,
            )
            return 1

        store_path = _resolve_vertex_store_path(writable_path)
        if store_path is None:
            show(
                Block.text("Error: vertex has no store configured", p.error),
                file=sys.stderr,
            )
            return 1

    except Exception as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1

    try:
        from engine import load_vertex_program

        # Special-case: pop facts also materialize the configured .list file.
        is_pop = kind in (POP_ADD_KIND, POP_RM_KIND)
        list_path = None
        header = None
        template_name = None
        include_unscoped = True
        template = None

        if is_pop:
            ast = parse_vertex_file(vertex_path)

            # Resolve template target:
            # - prefer explicit vertex/template qualifier
            # - else payload["template"] if provided
            # - else allow implicit if only one template exists
            payload_template = payload.get("template")
            qualifier = template_qualifier or payload_template

            templates = [
                s
                for s in (ast.sources or ())
                if getattr(s, "template", None) is not None
            ]
            is_multi = len(templates) > 1
            include_unscoped = not is_multi

            if is_multi and not qualifier:
                show(
                    Block.text(
                        "Error: multiple templates in vertex; specify one as "
                        "'vertex/template' or include template=... in payload",
                        p.error,
                    ),
                    file=sys.stderr,
                )
                return 1

            template = resolve_template(ast, qualifier)
            template_name = template.template.stem if is_multi else None

            if template.from_ is None or not hasattr(template.from_, "path"):
                show(
                    Block.text(
                        "Error: template has no 'from file' population configured",
                        p.error,
                    ),
                    file=sys.stderr,
                )
                return 1

            list_path = template.from_.path
            if not Path(list_path).is_absolute():
                list_path = (vertex_path.parent / list_path).resolve()
            else:
                list_path = Path(list_path)

            header = list_file_header(list_path)
            if not header:
                show(
                    Block.text(
                        f"Error: no .list header found at {list_path}",
                        p.error,
                    ),
                    file=sys.stderr,
                )
                return 1

            if kind == POP_ADD_KIND:
                if "key" not in payload:
                    show(
                        Block.text("Error: pop.add requires key=...", p.error),
                        file=sys.stderr,
                    )
                    return 1
                missing = [h for h in header[1:] if h not in payload]
                if missing:
                    show(
                        Block.text(
                            "Error: pop.add requires all non-key columns: "
                            + ", ".join(missing),
                            p.error,
                        ),
                        file=sys.stderr,
                    )
                    return 1
            if kind == POP_RM_KIND and "key" not in payload:
                show(
                    Block.text("Error: pop.rm requires key=...", p.error),
                    file=sys.stderr,
                )
                return 1

            if template_name is not None:
                if "template" in payload and payload.get("template") != template_name:
                    show(
                        Block.text(
                            f"Error: payload template={payload.get('template')!r} does not match "
                            f"resolved template {template_name!r}",
                            p.error,
                        ),
                        file=sys.stderr,
                    )
                    return 1
                payload["template"] = template_name

        # Load the vertex runtime — facts route through loops, boundaries fire
        store_path.parent.mkdir(parents=True, exist_ok=True)
        program = load_vertex_program(writable_path, validate_ast=False)

        try:
            if is_pop and list_path is not None and header is not None:
                # If this is the first pop mutation for this template, seed the store
                # from the existing .list to avoid clobbering on first materialization.
                if not pop_store_has_facts(
                    store_path,
                    template=template_name,
                    include_unscoped=include_unscoped,
                ):
                    if list_path.exists():
                        hdr, rows = list_file_read(list_path)
                        if hdr:
                            for row in rows:
                                seed_payload: dict[str, str] = {"key": row.key}
                                if template_name is not None:
                                    seed_payload["template"] = template_name
                                for field in hdr[1:]:
                                    seed_payload[field] = row.values.get(field, "")
                                seed_fact = Fact(
                                    kind=POP_ADD_KIND,
                                    ts=datetime.now(timezone.utc).timestamp(),
                                    payload=seed_payload,
                                    observer=args.observer or "",
                                    origin="",
                                )
                                program.vertex.receive(seed_fact)

            # Route fact through the vertex runtime — fold, boundary check, store
            tick = program.vertex.receive(fact)
            if tick is not None:
                # Boundary fired — a tick was produced
                show(
                    Block.text(
                        f"tick: {tick.name} ({len(tick.payload)} fields)",
                        p.muted,
                    ),
                )
        finally:
            # Clean up the store connection
            if hasattr(program.vertex, '_store') and program.vertex._store is not None:
                program.vertex._store.close()

        if is_pop and list_path is not None and header is not None:
            pop_materialize_list(
                store_path=store_path,
                list_path=list_path,
                header=header,
                template=template_name,
                include_unscoped=include_unscoped,
            )
        return 0
    except Exception as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1


def _resolve_render_fn(
    lens_flag: str | None,
    vertex_path: Path | None,
    mod,
    view_name: str,
):
    """Resolve render function via 4-tier chain.

    Resolution order:
    1. --lens CLI flag (resolved via lens_resolver)
    2. Vertex lens{} declaration (resolved via lens_resolver)
    3. App module override (_resolve_app_view)
    4. Built-in default
    """
    from .lens_resolver import resolve_lens

    # Determine vertex directory for lens search path
    vertex_dir = vertex_path.parent if vertex_path is not None else None

    # Tier 1: --lens flag
    if lens_flag is not None:
        fn = resolve_lens(lens_flag, view_name, vertex_dir=vertex_dir)
        if fn is not None:
            return fn

    # Tier 2: vertex lens{} declaration
    if vertex_path is not None:
        vertex_lens = _get_vertex_lens_decl(vertex_path)
        if vertex_lens is not None:
            # Pick the right lens name for this view
            if view_name == "fold_view" and vertex_lens.fold:
                fn = resolve_lens(vertex_lens.fold, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn
            elif view_name in ("stream_view", "log_view") and vertex_lens.stream:
                fn = resolve_lens(vertex_lens.stream, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn

    # Tier 3: app module override
    if mod is not None:
        fn = _resolve_app_view(mod, view_name)
        if fn is not None:
            return fn

    # Tier 4: built-in defaults
    if view_name == "fold_view":
        from .lenses.fold import fold_view
        return fold_view
    elif view_name in ("stream_view", "log_view"):
        from .lenses.stream import stream_view
        return stream_view

    # Shouldn't reach here, but be safe
    from .lenses.fold import fold_view
    return fold_view


def _get_vertex_lens_decl(vertex_path: Path):
    """Extract LensDecl from a vertex file, if present."""
    try:
        from lang import parse_vertex_file
        vf = parse_vertex_file(vertex_path)
        return vf.lens
    except Exception:
        return None


def _resolve_app_view(mod, view_name: str):
    """Resolve a view function from an app module.

    Lookup order:
    1. mod.<view_name> — app provides a specific view function
    2. Fallback names: fold_view → status_view, stream_view → log_view
    3. PAYLOAD_LENS — app provides a lens, generic view wraps it
    4. None — caller falls back to shared loops lenses
    """
    specific = getattr(mod, view_name, None)
    if specific is not None:
        return specific

    # Fallback aliases for transition period
    _fallbacks = {
        "fold_view": "status_view",
        "stream_view": "log_view",
    }
    if view_name in _fallbacks:
        fallback = getattr(mod, _fallbacks[view_name], None)
        if fallback is not None:
            return fallback

    payload_lens = getattr(mod, "PAYLOAD_LENS", None)
    if payload_lens is not None and view_name in ("log_view", "search_view", "stream_view"):
        # Build a generic log/search view that delegates payload rendering to the lens
        return _make_lens_log_view(payload_lens)

    return None


def _make_lens_log_view(payload_lens):
    """Build a log_view that uses a PayloadLens for payload summaries.

    This is the generic fallback: an app that only exports PAYLOAD_LENS
    gets a log view where kind summaries come from the lens, not the
    hardcoded _log_summary in the shared log lens.
    """
    from datetime import datetime, timezone

    from painted import Block, Style, Zoom, join_vertical
    from painted.compose import join_horizontal

    def log_view(facts, zoom, width):
        if not facts:
            return Block.text(
                "No facts in the given time range.", Style(dim=True), width=width
            )

        if zoom == Zoom.MINIMAL:
            counts: dict[str, int] = {}
            for f in facts:
                counts[f["kind"]] = counts.get(f["kind"], 0) + 1
            parts = [f"{count} {kind}" for kind, count in counts.items()]
            return Block.text(", ".join(parts), Style(), width=width)

        rows: list[Block] = []
        dim = Style(dim=True)
        current_date = None

        for f in facts:
            ts = f["ts"]
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(ts, datetime):
                dt = ts
            elif isinstance(ts, str):
                dt = datetime.fromisoformat(ts)
            else:
                continue

            date_str = dt.strftime("%Y-%m-%d")
            if date_str != current_date:
                if current_date is not None:
                    rows.append(Block.text("", Style(), width=width))
                rows.append(Block.text(f"{date_str}:", Style(bold=True), width=width))
                current_date = date_str

            time_str = dt.strftime("%H:%M")
            kind = f["kind"]
            payload = f.get("payload", {})
            summary = payload_lens(kind, payload, zoom)

            if isinstance(summary, Block):
                label = Block.text(f"  {time_str} [{kind}] ", Style(), width=0)
                rows.append(join_horizontal(label, summary))
            else:
                line = f"  {time_str} [{kind}] {summary}"
                if len(line) > width:
                    line = line[: width - 1] + "…"
                rows.append(Block.text(line, Style(), width=width))

            if zoom >= Zoom.FULL:
                for key, val in payload.items():
                    if val:
                        rows.append(
                            Block.text(f"           {key}: {val}", dim, width=width)
                        )

        return join_vertical(*rows)

    return log_view


def _generic_fold_summary(fold_state: dict) -> dict:
    """Build a generic summary from raw fold state when no app-specific fetch exists."""
    sections = {}
    for kind, state in fold_state.items():
        items = state.get("items", {})
        if isinstance(items, dict):
            sections[kind] = {"count": len(items), "items": items}
        elif isinstance(items, list):
            sections[kind] = {"count": len(items), "items": items}
        else:
            sections[kind] = {"count": 0, "items": {}}
    return sections


def _run_stream(argv: list[str], *, vertex_path: Path | None = None, mod=None, observer: str = "") -> int:
    """Run stream command — unified event history with optional search.

    Dissolves the old log + search into one temporal mode.
    When vertex_path is None (verb-first), the first positional is tried as
    a vertex name before falling back to search query.
    """
    from painted import run_cli
    from painted.fidelity import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex_or_query", nargs="?", default=None)
        pre.add_argument("query", nargs="?", default=None)
    else:
        pre.add_argument("query", nargs="?", default=None)
    pre.add_argument("--kind", default=None)
    pre.add_argument("--since", default=None)
    pre.add_argument("--lens", default=None)
    known, rest = pre.parse_known_args(argv)

    # Render function resolved lazily — vertex_path may not be known until fetch()
    resolved_render_fn = None

    def fetch():
        nonlocal vertex_path
        query = known.query

        if vertex_path is None:
            from .commands.identity import resolve_local_vertex as _resolve_local_vertex

            first = getattr(known, "vertex_or_query", None)
            if first is not None:
                # Try as vertex name first; if it fails, treat as query
                resolved = _resolve_vertex_for_dispatch(first)
                if resolved is not None:
                    vertex_path = resolved
                else:
                    # Not a vertex — it's the query; shift known.query to unused
                    query = first
                    if known.query is not None:
                        query = f"{first} {known.query}"
            if vertex_path is None:
                vertex_path = _resolve_local_vertex()

        from .commands.fetch import fetch_stream
        return fetch_stream(
            vertex_path,
            query=query,
            kind=known.kind,
            since=known.since,
            observer=observer or None,
        )

    def render(ctx, data):
        nonlocal resolved_render_fn
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, mod, "stream_view",
            )
        return resolved_render_fn(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops stream",
        description="Show event stream",
        help_args=[
            HelpArg("query", "Search text (FTS5)", positional=True),
            HelpArg("--kind", "Filter by fact kind"),
            HelpArg("--observer", "Filter by observer (default: you)"),
            HelpArg("--since", "Time window (7d, 24h, 1h)", default="7d"),
            HelpArg("--lens", "Render lens (prompt)"),
        ],
    )


def _run_fold(argv: list[str], *, vertex_path: Path | None = None, mod=None, observer: str = "") -> int:
    """Run fold command — show collapsed vertex state."""
    from painted import run_cli
    from painted.fidelity import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex", nargs="?", default=None)
    pre.add_argument("--kind", default=None)
    pre.add_argument("--lens", default=None)
    known, rest = pre.parse_known_args(argv)

    # Render function resolved lazily — vertex_path may not be known until fetch()
    resolved_render_fn = None

    def fetch():
        nonlocal vertex_path
        if vertex_path is None:
            from .commands.identity import resolve_local_vertex as _resolve_local_vertex
            vname = getattr(known, "vertex", None)
            if vname is not None:
                vertex_path = _resolve_named_vertex(vname)
            else:
                vertex_path = _resolve_local_vertex()
        if mod is not None:
            from engine import vertex_read
            fold_state = vertex_read(vertex_path, observer=observer or None)
            fetch_fn = getattr(mod, "fetch_status", None)
            if fetch_fn is not None:
                return fetch_fn(fold_state)
            return _generic_fold_summary(fold_state)
        from .commands.fetch import fetch_fold
        return fetch_fold(vertex_path, kind=known.kind, observer=observer or None)

    def render(ctx, data):
        nonlocal resolved_render_fn
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, mod, "fold_view",
            )
        # When piped (not TTY), pass width=None so text flows without
        # truncation or padding. The fold output IS the data — useful
        # directly as a system prompt or piped to other tools.
        w = ctx.width if ctx.is_tty else None
        return resolved_render_fn(data, ctx.zoom, w)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops fold",
        description="Show folded state",
        help_args=[
            HelpArg("--kind", "Filter by fact kind"),
            HelpArg("--observer", "Filter by observer (default: you)"),
            HelpArg("--lens", "Render lens (prompt)"),
        ],
    )


def _run_log_legacy(argv: list[str], *, vertex_path: Path | None = None, mod=None, observer: str = "") -> int:
    """Legacy log alias — delegates to _run_stream with --since default."""
    # If vertex_path not provided, we need to resolve it first for the legacy path
    if vertex_path is None:
        pre = argparse.ArgumentParser(add_help=False)
        pre.add_argument("vertex", nargs="?", default=None)
        known, rest = pre.parse_known_args(argv)
        vname = getattr(known, "vertex", None)
        if vname is not None:
            vertex_path = _resolve_named_vertex(vname)
        else:
            from .commands.identity import resolve_local_vertex as _resolve_local_vertex
            vertex_path = _resolve_local_vertex()
        argv = rest
    return _run_stream(argv, vertex_path=vertex_path, mod=mod, observer=observer)


def _run_store(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Run store command via painted CLI harness."""
    from painted import run_cli, OutputMode
    from painted.fidelity import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
    known, rest = pre.parse_known_args(argv)
    file_arg = getattr(known, "file", None)

    def _resolve_store_target() -> Path:
        """Resolve file arg: vertex name, path, or LOOPS_HOME/root.vertex fallback."""
        if vertex_path is not None:
            return vertex_path
        if file_arg is not None:
            p = Path(file_arg)
            # If it looks like a path (has extension or path separators), use directly
            if p.suffix or file_arg.startswith("./") or file_arg.startswith("/"):
                return p
            # Otherwise treat as vertex name
            from lang.population import resolve_vertex

            return resolve_vertex(file_arg, loops_home())
        home = loops_home()
        root = home / ".vertex"
        if root.exists():
            return root
        legacy = home / "root.vertex"
        if legacy.exists():
            return legacy
        raise FileNotFoundError(f"{root} not found. Run 'loops init' first.")

    def fetch():
        from .commands.store import make_fetcher

        path = _resolve_store_target().resolve()
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist")
        return make_fetcher(path, zoom=3)()

    def render(ctx, data):
        from .lenses.store import store_view

        return store_view(data, ctx.zoom, ctx.width)

    async def fetch_stream():
        import asyncio

        while True:
            try:
                yield fetch()
            except FileNotFoundError:
                pass
            await asyncio.sleep(2.0)

    def handle_interactive(ctx):
        from .tui import StoreExplorerApp

        path = _resolve_store_target().resolve()
        app = StoreExplorerApp(path)
        asyncio.run(app.run())
        return 0

    return run_cli(
        rest,
        fetch=fetch,
        fetch_stream=fetch_stream,
        render=render,
        handlers={OutputMode.INTERACTIVE: handle_interactive},
        default_mode=OutputMode.STATIC,
        prog="loops store",
        description="Inspect store contents",
        help_args=[
            HelpArg("file", "Store file, vertex name, or path", positional=True),
        ],
    )


def _run_check(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Run health checks, emit result facts, render with gutter."""
    from painted import run_cli
    from painted.fidelity import HelpArg
    from lang import parse_vertex_file
    from engine.compiler import compile_sources_block

    from .health import DEFAULT_STEPS, health_view, run_checks, run_sequential_checks

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex", nargs="?", default=None)
    pre.add_argument("--observer", default="dev-check")
    known, rest = pre.parse_known_args(argv)

    # Resolve vertex and store
    if vertex_path is None:
        vname = getattr(known, "vertex", None)
        if vname is not None:
            vertex_path = _resolve_named_vertex(vname)
        else:
            local = _find_local_vertex()
            if local is not None:
                vertex_path = local
            else:
                _err("No vertex found. Run 'loops init' first.")
                return 1

    store_path = _resolve_vertex_store_path(vertex_path)
    if store_path is None:
        _err("Vertex has no store configured")
        return 1

    # Parse vertex AST to check for sources sequential blocks
    vertex_ast = parse_vertex_file(vertex_path)
    seq_block = None
    if vertex_ast.sources_blocks:
        for block in vertex_ast.sources_blocks:
            if block.mode == "sequential":
                seq_block = block
                break

    project_root = vertex_path.parent
    results_ref: list[dict] = []

    def fetch():
        if seq_block is not None:
            # Vertex declares sources sequential — compile and run it
            seq_source = compile_sources_block(seq_block, vertex_ast.name)
            results = run_sequential_checks(
                seq_source,
                store_path,
                observer=known.observer,
            )
        else:
            # No sources block — fall back to DEFAULT_STEPS
            results = run_checks(
                store_path,
                DEFAULT_STEPS,
                observer=known.observer,
                cwd=project_root,
            )
        results_ref.extend(results)
        return results

    def render(ctx, data):
        return health_view(data, ctx.zoom, ctx.width)

    rc = run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops check",
        description="Run project health checks",
        help_args=[
            HelpArg("vertex", "Vertex name (default: local)", positional=True),
            HelpArg("--observer", "Observer name", default="dev-check"),
        ],
    )

    # Return failure if any check failed
    if results_ref:
        last = results_ref[-1]
        if last.get("payload", {}).get("status") == "failed":
            return 1

    return rc


def _run_ls(argv: list[str]) -> int:
    """Run ls command via painted CLI harness."""
    from painted import run_cli
    from painted.fidelity import HelpArg
    from .commands.pop import fetch_ls
    from .lenses.pop import pop_view

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("target")
    known, rest = pre.parse_known_args(argv)

    def fetch():
        return fetch_ls(known.target)

    def render(ctx, data):
        return pop_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops ls",
        description="List template populations",
        help_args=[
            HelpArg("target", "Population target name", positional=True),
        ],
    )


def _run_ls_root(argv: list[str]) -> int:
    """Run root-level ls: list all discovered vertices."""
    from painted import run_cli
    from .commands.vertices import fetch_vertices
    from .lenses.vertices import vertices_view

    home = loops_home()

    def fetch():
        return fetch_vertices(home)

    def render(ctx, data):
        return vertices_view(data, ctx.zoom, ctx.width)

    return run_cli(
        argv,
        fetch=fetch,
        render=render,
        prog="loops ls",
        description="List vertices",
    )


def _run_init(argv: list[str]) -> int:
    """Thin wrapper: parse argv for init, delegate to cmd_init."""
    parser = argparse.ArgumentParser(prog="loops init", add_help=False)
    parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Vertex name (e.g., 'project' or 'dev/project')",
    )
    parser.add_argument(
        "--template",
        "-t",
        help="Source vertex name to use as template (defaults to init name)",
    )
    args = parser.parse_args(argv)
    return cmd_init(args)


def _run_emit(argv: list[str], *, vertex_path: Path | None = None, observer: str = "") -> int:
    """Thin wrapper: parse argv for emit, delegate to cmd_emit."""
    parser = argparse.ArgumentParser(prog="loops emit", add_help=False)
    if vertex_path is None:
        parser.add_argument(
            "vertex",
            nargs="?",
            default=None,
            help="Vertex name or .vertex path (optional; auto-resolves local vertex)",
        )
    parser.add_argument("kind", help="Fact kind")
    parser.add_argument(
        "parts", nargs="*", help="KEY=VALUE pairs and optional trailing message text"
    )
    parser.add_argument(
        "--observer",
        default=None,
        help="Observer string (default: from .vertex declaration or $LOOPS_OBSERVER)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the fact JSON without storing"
    )
    args = parser.parse_args(argv)
    if vertex_path is not None:
        args.vertex = None
    # Use dispatch-level observer if emit didn't override
    if args.observer is None:
        args.observer = observer or None
    return cmd_emit(args, vertex_path=vertex_path)


def _run_close(argv: list[str], *, vertex_path: Path | None = None, observer: str = "") -> int:
    """Close a thread — resolve it and capture what it produced.

    Volitional boundary: the observer decides when a thread is done.
    Collects associated artifacts (decisions, tasks, threads) by:
    1. Temporal proximity — facts emitted since the thread opened
    2. Explicit tagging — facts with thread=<name> in payload

    Emits the resolution fact with a ``produced`` field listing what
    the thread generated.
    """
    from datetime import datetime, timezone

    from atoms import Fact
    from engine import vertex_facts, vertex_fold
    from painted import show, Block, Style
    from painted.palette import current_palette
    from .commands.identity import resolve_local_vertex, resolve_observer, validate_emit

    p = current_palette()

    parser = argparse.ArgumentParser(prog="loops close", add_help=False)
    if vertex_path is None:
        parser.add_argument("vertex", nargs="?", default=None)
    parser.add_argument("kind", help="Fact kind to close (e.g. thread, task)")
    parser.add_argument("name", help="Name/key of the item to close")
    parser.add_argument("message", nargs="?", default=None, help="Resolution summary")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args(argv)

    # Resolve vertex
    if vertex_path is None:
        vname = getattr(args, "vertex", None)
        if vname is not None:
            resolved = _resolve_vertex_for_dispatch(vname)
            if resolved is not None:
                vertex_path = resolved
            else:
                # Not a vertex — shift: it's the kind, kind is name, name is message
                if args.message is None:
                    args.message = args.name
                args.name = args.kind
                args.kind = vname
                vertex_path = resolve_local_vertex()
        else:
            vertex_path = resolve_local_vertex()

    # Resolve observer
    obs = resolve_observer(observer or None)

    # Find the item in fold state to get its open timestamp
    fold_state = vertex_fold(vertex_path, observer=None, kind=args.kind)
    target_item = None
    for section in fold_state.sections:
        if section.kind == args.kind:
            for item in section.items:
                # Match by key field value (name, topic, etc.)
                key_field = section.key_field
                if key_field and item.payload.get(key_field) == args.name:
                    target_item = item
                    break
                # Fallback: check common key fields
                for kf in ("name", "topic", "title"):
                    if item.payload.get(kf) == args.name:
                        target_item = item
                        break
                if target_item:
                    break

    if target_item is None:
        _err(f"No {args.kind} named '{args.name}' found in fold state.")
        return 1

    # Collect produced artifacts via two strategies:
    # 1. Tagged — facts with thread=<name> in payload (precise)
    # 2. Temporal — artifact kinds emitted since thread opened (approximate)
    # Tagged wins when any tagged facts exist; temporal is the fallback.
    tagged = []
    temporal = []
    now = datetime.now(timezone.utc).timestamp()
    if target_item.ts:
        all_facts = vertex_facts(vertex_path, target_item.ts, now)
        for f in all_facts:
            payload = f.get("payload", {})

            # Skip the thread's own facts
            if f["kind"] == args.kind:
                is_self = False
                for kf in ("name", "topic", "title"):
                    if payload.get(kf) == args.name:
                        is_self = True
                        break
                if is_self:
                    continue

            # Check explicit thread tag
            if payload.get("thread") == args.name:
                _add_produced(tagged, f)
                continue

            # Temporal: artifact kinds emitted during thread lifetime
            if f["kind"] in ("decision", "task", "thread", "change"):
                _add_produced(temporal, f)

    # Tagged wins when available; temporal is fallback
    if tagged:
        produced = tagged
        produced_mode = "tagged"
    else:
        produced = temporal
        produced_mode = "temporal"

    # Deduplicate produced artifacts (same kind:key = same artifact)
    seen = set()
    deduped = []
    for pr in produced:
        ref = f"{pr['kind']}:{pr['key']}"
        if ref not in seen:
            seen.add(ref)
            deduped.append(pr)
    produced = deduped

    # Build resolution payload
    key_field = "name"
    for section in fold_state.sections:
        if section.kind == args.kind and section.key_field:
            key_field = section.key_field
            break

    resolution_payload = {
        key_field: args.name,
        "status": "resolved",
    }
    if args.message:
        resolution_payload["message"] = args.message
    if produced:
        resolution_payload["produced"] = [
            f"{p['kind']}:{p['key']}" for p in produced
        ]

    # Show what we found
    show(Block.text(f"Closing {args.kind}: {args.name}", Style(bold=True)))
    if target_item.ts:
        opened = datetime.fromtimestamp(target_item.ts, tz=timezone.utc)
        show(Block.text(f"  opened: {opened.strftime('%Y-%m-%d %H:%M')}", Style(dim=True)))

    if produced:
        show(Block.text(f"  produced ({len(produced)}, {produced_mode}):", Style()))
        for pr in produced:
            show(Block.text(f"    {pr['kind']}: {pr['key']}", Style(dim=True)))
    else:
        show(Block.text("  no associated artifacts found", Style(dim=True)))

    if args.dry_run:
        import json as _json
        show(Block.text(f"\n  dry-run payload: {_json.dumps(resolution_payload)}", Style(dim=True)))
        return 0

    # Emit the resolution fact
    fact = Fact.of(args.kind, obs, **resolution_payload)

    # Validate and emit through runtime
    err = validate_emit(vertex_path, obs, args.kind)
    if err is not None:
        _err(f"Error: {err}")
        return 1

    from engine import load_vertex_program

    vp = _resolve_writable_vertex(vertex_path)
    program = load_vertex_program(vp)
    program.vertex.receive(fact)

    show(Block.text(f"  ✓ {args.kind} '{args.name}' resolved", p.success))
    return 0


def _add_produced(produced: list[dict], fact: dict) -> None:
    """Extract a reference from a fact for the produced list."""
    payload = fact.get("payload", {})
    # Find the best key for this fact
    for kf in ("name", "topic", "title"):
        if payload.get(kf):
            produced.append({"kind": fact["kind"], "key": payload[kf]})
            return
    # Fallback: first non-empty string field
    for k, v in payload.items():
        if isinstance(v, str) and v and not k.startswith("_"):
            produced.append({"kind": fact["kind"], "key": v[:60]})
            return


def _run_add(argv: list[str]) -> int:
    """Thin wrapper: parse argv for add, delegate to cmd_add."""
    from .commands.pop import cmd_add

    parser = argparse.ArgumentParser(prog="loops add", add_help=False)
    parser.add_argument("target", help="Vertex name or vertex/template")
    parser.add_argument("values", nargs="+", help="Column values in header order")
    args = parser.parse_args(argv)
    return cmd_add(args)


def _run_rm(argv: list[str]) -> int:
    """Thin wrapper: parse argv for rm, delegate to cmd_rm."""
    from .commands.pop import cmd_rm

    parser = argparse.ArgumentParser(prog="loops rm", add_help=False)
    parser.add_argument("target", help="Vertex name or vertex/template")
    parser.add_argument("key", help="Key (first column) to remove")
    args = parser.parse_args(argv)
    return cmd_rm(args)


def _run_export(argv: list[str]) -> int:
    """Thin wrapper: parse argv for export, delegate to cmd_export."""
    from .commands.pop import cmd_export

    parser = argparse.ArgumentParser(prog="loops export", add_help=False)
    parser.add_argument("target", help="Vertex name or vertex/template")
    parser.add_argument(
        "--output",
        "-o",
        help="(deprecated) ignored; export materializes configured .list",
    )
    args = parser.parse_args(argv)
    return cmd_export(args)


def _run_whoami(argv: list[str]) -> int:
    """Show resolved observer identity.

    Resolution chain:
    1. LOOPS_OBSERVER env var / .vertex single-observer (via resolve_observer)
    2. Identity store self/name fact (for multi-observer .vertex files)
    """
    from painted import show, Block, Style
    from .commands.identity import resolve_observer, resolve_local_vertex

    observer = resolve_observer()
    if not observer:
        # Fall back to identity store — handles multi-observer .vertex
        observer = _whoami_from_identity_store()
    if not observer:
        show(Block.text("No observer identity resolved.", Style(dim=True)))
        return 1
    show(Block.text(observer, Style()))
    return 0


def _whoami_from_identity_store() -> str:
    """Try to read observer name from the local identity vertex store.

    Uses dispatch resolution (local .loops/ first) so it finds the
    workspace identity, not the config-level template.
    """
    try:
        from .commands.fetch import fetch_fold
        identity_path = _resolve_vertex_for_dispatch("identity")
        if identity_path is None:
            return ""
        fold_state = fetch_fold(identity_path, kind="self")
        for section in fold_state.sections:
            if section.kind == "self":
                for item in section.items:
                    if item.payload.get("name") == "name":
                        msg = item.payload.get("message", "")
                        # "meta-claude. Some description..." → "meta-claude"
                        return msg.split(".")[0].strip() if msg else ""
        return ""
    except Exception:
        return ""


_ROOT_COMMANDS = {"run", "start", "compile", "validate", "test", "init", "ls", "store", "whoami"}

# Verbs that support verb-first dispatch: `loops fold` instead of `loops project fold`.
# These resolve the vertex from context (local .vertex or LOOPS_HOME fallback).
_OBSERVER_VERBS = frozenset({"fold", "stream", "emit", "close"})

_VERTEX_OPS = frozenset({
    "fold", "stream", "emit", "close", "store",
    "check", "ls", "add", "rm", "export",
    # Legacy aliases
    "status", "log", "search",
})


def _render_main_help(argv: list[str]) -> int:
    """Render two-group help: vertex operations + root commands."""
    import shutil
    from painted.fidelity import (
        Format,
        HelpData,
        HelpFlag,
        HelpGroup,
        Zoom,
        render_help,
        scan_help_args,
    )
    from painted.writer import print_block

    zoom, fmt = scan_help_args(argv)

    observer_group = HelpGroup(
        name="Observer",
        hint="loops <verb> [vertex] [args]",
        flags=(
            HelpFlag(None, "fold", "Show folded state (default)", detail="[vertex] [--kind KIND] [--observer OBS]"),
            HelpFlag(None, "stream", "Show event stream", detail="[vertex] [query] [--since SINCE] [--kind KIND]"),
            HelpFlag(None, "emit", "Inject a fact", detail="[vertex] <kind> [KEY=VALUE ...] [--dry-run]"),
            HelpFlag(None, "close", "Resolve and capture artifacts", detail="[vertex] <kind> <name> [message] [--dry-run]"),
        ),
    )

    vertex_group = HelpGroup(
        name="Vertex operations",
        hint="loops <vertex> [op]",
        flags=(
            HelpFlag(None, "store", "Inspect store contents"),
            HelpFlag(None, "check", "Run health checks", detail="[--observer OBS]"),
            HelpFlag(None, "ls", "List vertex contents", detail="[template]"),
            HelpFlag(None, "add", "Add to template population", detail="<values...>"),
            HelpFlag(None, "rm", "Remove from template population", detail="<key>"),
            HelpFlag(None, "export", "Materialize .list from store"),
        ),
    )

    commands_group = HelpGroup(
        name="Commands",
        flags=(
            HelpFlag(None, "ls", "List vertices"),
            HelpFlag(None, "store", "Inspect store contents", detail="[file]"),
            HelpFlag(None, "start", "Run a vertex (one round, rendered)", detail="[file] [--var KEY=VALUE]"),
            HelpFlag(None, "run", "Execute a .loop or .vertex file", detail="[file] [--rounds N]"),
            HelpFlag(None, "compile", "Show compiled structure", detail="<file>"),
            HelpFlag(None, "validate", "Validate syntax and flow", detail="[files...]"),
            HelpFlag(None, "test", "Run parse pipeline", detail="<file> [--input FILE]"),
            HelpFlag(None, "init", "Initialize vertex", detail="[name] [--template NAME]"),
            HelpFlag(None, "whoami", "Show resolved observer identity"),
        ),
    )

    zoom_group = HelpGroup(
        name="Zoom",
        hint="(what to show)",
        detail="Controls how much detail is rendered.",
        flags=(
            HelpFlag("-q", "--quiet", "Minimal output"),
            HelpFlag("-v", "--verbose", "Detailed (-v) or full (-vv)"),
        ),
        min_zoom=Zoom.SUMMARY,
    )

    format_group = HelpGroup(
        name="Format",
        hint="(serialization)",
        flags=(
            HelpFlag(None, "--json", "JSON output"),
            HelpFlag(None, "--plain", "Plain text, no ANSI codes"),
        ),
        min_zoom=Zoom.SUMMARY,
    )

    help_group = HelpGroup(
        name="Help",
        flags=(HelpFlag("-h", "--help", "Show this help", detail="Add -v for more detail."),),
        min_zoom=Zoom.SUMMARY,
    )

    help_data = HelpData(
        prog="loops",
        description="Runtime for .loop and .vertex files",
        groups=(observer_group, vertex_group, commands_group, zoom_group, format_group, help_group),
    )

    if fmt == Format.JSON:
        from dataclasses import asdict
        print(json.dumps(asdict(help_data), default=str))
        return 0

    use_ansi = fmt != Format.PLAIN
    if fmt == Format.AUTO:
        use_ansi = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    width = shutil.get_terminal_size().columns
    block = render_help(help_data, zoom, width, use_ansi)
    print_block(block, use_ansi=use_ansi)
    return 0


def _resolve_observer_flag(raw: str | None) -> str:
    """Resolve --observer flag, handling the special 'all' value.

    Returns "" to mean 'unscoped / all observers' (engine passes None).
    Any other value goes through normal observer resolution.
    """
    if raw is not None and raw.lower() == "all":
        return ""  # unscoped — will pass None to engine
    from .commands.identity import resolve_observer
    return resolve_observer(raw)


def _dispatch_verb_first(verb: str, rest: list[str]) -> int:
    """Dispatch verb-first observer operations: ``loops fold [vertex] [args]``.

    Resolves ``--observer`` the same way as ``_dispatch_observer``, then
    delegates to the same ``_run_*`` functions with ``vertex_path=None``
    so they resolve the vertex from context (optional positional or local).
    """
    # Pre-parse --observer from rest (same pattern as _dispatch_observer)
    obs_parser = argparse.ArgumentParser(add_help=False)
    obs_parser.add_argument("--observer", default=None)
    obs_known, rest = obs_parser.parse_known_args(rest)
    observer = _resolve_observer_flag(obs_known.observer)

    if verb == "fold":
        return _run_fold(rest, vertex_path=None, observer=observer)
    if verb == "stream":
        return _run_stream(rest, vertex_path=None, observer=observer)
    if verb == "emit":
        return _run_emit(rest, vertex_path=None, observer=observer)
    if verb == "close":
        return _run_close(rest, vertex_path=None, observer=observer)

    _err(f"Unknown verb: {verb}")
    return 1


def _dispatch_observer(
    vertex_name: str, vertex_path: Path, rest: list[str]
) -> int:
    """Dispatch observer operations with resolved vertex.

    Resolves ``--observer`` once at dispatch level and threads it to all
    subcommands. Default is the current observer identity (from env /
    .vertex chain) — you're always yourself unless you explicitly look
    through someone else's eyes.

    Default (no subcommand or flags only) → fold mode.
    Temporal modes: fold, stream, emit.
    Legacy aliases: status → fold, log → stream, search → stream.
    """
    import importlib

    # Pre-parse --observer from rest (before subcommand dispatch)
    obs_parser = argparse.ArgumentParser(add_help=False)
    obs_parser.add_argument("--observer", default=None)
    obs_known, rest = obs_parser.parse_known_args(rest)
    observer = _resolve_observer_flag(obs_known.observer)

    # Load app module if registered
    mod = None
    if vertex_name in _APPS:
        mod = importlib.import_module(_APPS[vertex_name])

    # Default: no subcommand or flags only → fold mode
    if not rest or rest[0].startswith("-"):
        return _run_fold(rest, vertex_path=vertex_path, mod=mod, observer=observer)

    op = rest[0]
    args = rest[1:]

    # Temporal modes
    if op == "fold":
        return _run_fold(args, vertex_path=vertex_path, mod=mod, observer=observer)
    if op == "stream":
        return _run_stream(args, vertex_path=vertex_path, mod=mod, observer=observer)
    if op == "emit":
        return _run_emit(args, vertex_path=vertex_path, observer=observer)
    if op == "close":
        return _run_close(args, vertex_path=vertex_path, observer=observer)

    # Legacy aliases
    if op == "status":
        return _run_fold(args, vertex_path=vertex_path, mod=mod, observer=observer)
    if op == "log":
        return _run_log_legacy(args, vertex_path=vertex_path, mod=mod, observer=observer)
    if op == "search":
        return _run_stream([op] + args, vertex_path=vertex_path, mod=mod, observer=observer)

    # Kept as-is (dissolve later)
    if op == "store":
        return _run_store(args, vertex_path=vertex_path)
    if op == "check":
        return _run_check(args, vertex_path=vertex_path)

    # Population operations — reconstruct target argv
    if op == "ls":
        qualifier = None
        flags = []
        for arg in args:
            if qualifier is None and not arg.startswith("-"):
                qualifier = arg
            else:
                flags.append(arg)
        target = f"{vertex_name}/{qualifier}" if qualifier else vertex_name
        return _run_ls([target] + flags)
    if op in ("add", "rm", "export"):
        handler = {"add": _run_add, "rm": _run_rm, "export": _run_export}[op]
        return handler([vertex_name] + args)

    # Feedback handlers from app module
    if mod is not None:
        feedback = getattr(mod, "FEEDBACK", {})
        if op in feedback:
            handler_ref = feedback[op]
            handler_mod, handler_fn = handler_ref.rsplit(":", 1)
            handler = getattr(importlib.import_module(handler_mod), handler_fn)
            parser = argparse.ArgumentParser(prog=f"loops {vertex_name} {op}")
            parser.add_argument("name", help=f"{op.capitalize()} name")
            parser.add_argument("--conversation", required=True, help="Conversation ID")
            parser.add_argument("--note", default="", help="Optional note")
            parsed = parser.parse_args(args)
            parsed.observer = observer  # already resolved at dispatch level
            return handler(vertex_path, parsed)

    _err(f"Unknown operation: {op}")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Main entry point — vertex-first dispatch."""
    if argv is None:
        argv = sys.argv[1:]

    # No args → help
    if not argv:
        return _render_main_help([])

    # Top-level help: -h/--help only when it's the first arg (no command yet)
    if argv[0] in ("-h", "--help"):
        return _render_main_help(argv)

    # Root commands → dispatch directly
    if argv[0] in _ROOT_COMMANDS:
        from painted.app_runner import run_app, AppCommand
        from painted.fidelity import HelpArg

        root_commands = [
            AppCommand("ls", "List vertices", _run_ls_root),
            AppCommand(
                "store",
                "Inspect store contents",
                _run_store,
                detail="[file] — vertex name, path, or .db file",
            ),
            AppCommand(
                "start",
                "Run a vertex (one round, rendered)",
                _run_start,
                detail="[file] [--var KEY=VALUE ...]",
            ),
            AppCommand(
                "run",
                "Execute a .loop or .vertex file",
                _run_run,
                detail="[file] [--rounds N] [--limit N] [--daemon] [--var KEY=VALUE]",
            ),
            AppCommand("compile", "Show compiled structure", _run_compile, detail="<file>"),
            AppCommand(
                "validate",
                "Validate syntax and flow",
                _run_validate,
                detail="[files...] — defaults to *.loop/*.vertex in cwd",
            ),
            AppCommand(
                "test",
                "Run parse pipeline against sample input",
                _run_test,
                detail="<file> [--input FILE]",
            ),
            AppCommand(
                "init",
                "Initialize vertex",
                _run_init,
                detail="[name] [--template NAME]",
                help_args=[
                    HelpArg("name", "Vertex name (e.g., 'project' or 'dev/project')", positional=True),
                    HelpArg("--template", "Source vertex name to use as template"),
                ],
            ),
            AppCommand("whoami", "Show resolved observer identity", _run_whoami),
        ]
        return run_app(
            argv, root_commands, prog="loops", description="Runtime for .loop and .vertex files"
        )

    # Verb-first dispatch: `loops fold`, `loops stream`, `loops emit`
    if argv[0] in _OBSERVER_VERBS:
        return _dispatch_verb_first(argv[0], argv[1:])

    # Vertex-first dispatch
    vertex_name = argv[0]
    vertex_path = _resolve_vertex_for_dispatch(vertex_name)

    if vertex_path is not None:
        return _dispatch_observer(vertex_name, vertex_path, argv[1:])

    # Path-like arg → suggest the right invocation
    if vertex_name.endswith(".vertex") or vertex_name.startswith("./") or vertex_name.startswith("/"):
        _err(f"File arguments go with a command: loops start {vertex_name}")
        return 1

    # Unknown command
    _err(f"Unknown command: {vertex_name}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
