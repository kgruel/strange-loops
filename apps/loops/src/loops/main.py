"""CLI for the loops runtime.

Commands:
    loops validate <file>           Validate syntax and flow
    loops test <file> --input <f>   Run parse pipeline against sample input
    loops run <file>                Execute a .loop or .vertex file
    loops compile <file>            Show compiled structure
    loops start <file>              Run a .vertex file (one round, rendered)
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
name "root"

discover "./**/*.vertex"
"""

_SESSION_VERTEX = """\
name "session"
store "./data/session.db"

loops {
  decision { fold { items "by" "topic" } }
  thread   { fold { items "by" "name" } }
  change   { fold { items "collect" 20 } }
  task     { fold { items "by" "name" } }
}
"""

_TASKS_VERTEX = """\
name "tasks"
store "./data/tasks.db"

loops {
  task     { fold { items "by" "name" } }
  thread   { fold { items "by" "name" } }
  change   { fold { items "collect" 20 } }
}
"""

_PROJECT_VERTEX = """\
name "project"
store "./data/project.db"

loops {
  decision { fold { items "by" "topic" } }
  thread   { fold { items "by" "name" } }
  change   { fold { items "collect" 20 } }
  task     { fold { items "by" "name" } }
}
"""

_SIFTD_VERTEX = """\
name "siftd"
store "./data/siftd.db"

loops {
  exchange {
    fold {
      items "by" "conversation_id"
    }
    search "prompt" "response"
  }
  tag {
    fold {
      items "by" "name"
    }
  }
}
"""

_TEMPLATES: dict[str, str] = {
    "session": _SESSION_VERTEX,
    "tasks": _TASKS_VERTEX,
    "project": _PROJECT_VERTEX,
    "siftd": _SIFTD_VERTEX,
}

# App registry — registered apps get `loops <app> <command>` dispatch
_APPS: dict[str, str] = {
    "siftd": "siftd_loops",
}


def _find_local_vertex() -> Path | None:
    """Find a .vertex file in cwd. Returns first match or None."""
    matches = sorted(Path.cwd().glob("*.vertex"))
    return matches[0] if matches else None


_AGGREGATION_VERTEX = """\
// {name} — aggregation vertex, discovers local instances
name "{name}"

discover "./instances/**/*.vertex"
"""


def _template_content(template: str, name: str) -> str:
    """Get template content with the vertex name overridden."""
    import re

    content = _TEMPLATES[template]
    # Replace name "template" with name "actual_name"
    content = re.sub(r'^name ".*"', f'name "{name}"', content, count=1, flags=re.MULTILINE)
    # Replace store path to match the name
    content = re.sub(
        r'^store "./data/.*\.db"',
        f'store "./data/{name}.db"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    return content


def _init_local_vertex(template: str, name: str | None = None) -> Path:
    """Create a vertex + data dir in cwd from a template. Returns vertex path."""
    leaf = name or template
    content = _template_content(template, leaf)
    vertex_path = Path.cwd() / f"{leaf}.vertex"
    if not vertex_path.exists():
        vertex_path.write_text(content)
    data_dir = Path.cwd() / "data"
    data_dir.mkdir(exist_ok=True)
    return vertex_path


def _init_config_vertex(name: str, template: str) -> Path:
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
        leaf = Path(name).name
        tpl = template or (leaf if leaf in _TEMPLATES else None)
        if tpl is None:
            _err(f"No template specified and '{leaf}' is not a known template")
            return 1
        vertex_path = _init_config_vertex(name, tpl)
        _msg(f"Created {vertex_path}")
        return 0

    # Bare name → local instance + register
    if name:
        tpl = template or (name if name in _TEMPLATES else None)
        if tpl is None:
            _err(f"No template specified and '{name}' is not a known template")
            return 1
        vertex_path = _init_local_vertex(tpl, name)
        _msg(f"Created {vertex_path}")
        link = _register_with_config(name, Path.cwd())
        if link is not None:
            _msg(f"Registered {Path.cwd()} → {link}")
        return 0

    # No name + template → local instance in cwd (existing behavior)
    if template:
        vertex_path = _init_local_vertex(template)
        _msg(f"Created {vertex_path}")
        return 0

    # No name + no template → root.vertex in LOOPS_HOME (existing behavior)
    home = loops_home()
    root = home / "root.vertex"
    if root.exists():
        from painted import show, Block
        from painted.palette import current_palette
        show(Block.text(f"Already initialized: {root}", current_palette().muted), file=sys.stdout)
        return 0
    home.mkdir(parents=True, exist_ok=True)
    root.write_text(_ROOT_VERTEX)
    _msg(f"Created {root}")
    return 0


def _resolve_vertex_path(file_arg: str | None) -> Path | None:
    """Resolve a vertex file path, defaulting to LOOPS_HOME/root.vertex."""
    if file_arg is not None:
        return Path(file_arg)
    root = loops_home() / "root.vertex"
    if not root.exists():
        _err(f"Error: {root} not found. Run 'loops init' first.")
        return None
    return root


def _run_validate(argv: list[str]) -> int:
    """Run validate command via painted CLI harness."""
    from painted import run_cli
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
                results.append({"path": str(path), "valid": False, "error": f"{path} does not exist"})
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
    )


def _run_run(argv: list[str]) -> int:
    """Run command via painted CLI harness — execute a .loop or .vertex file."""
    from painted import run_cli

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
                collected.append({
                    "kind": fact.kind,
                    "ts": fact.ts,
                    "payload": fact.payload,
                    "observer": fact.observer,
                    "origin": fact.origin,
                })
                count += 1
                if limit and count >= limit:
                    break

        asyncio.run(_collect())
        return collected

    async def fetch_stream():
        accumulated: list[dict] = []
        count = 0
        async for fact in source.stream():
            accumulated.append({
                "kind": fact.kind,
                "ts": fact.ts,
                "payload": fact.payload,
                "observer": fact.observer,
                "origin": fact.origin,
            })
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
    )


def _run_run_vertex(path: Path, known, rest: list[str]) -> int:
    """Execute a .vertex file through run_cli."""
    from painted import run_cli
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
        payload = dict(fact.payload) if hasattr(fact.payload, 'items') else fact.payload
        _err(f"[ERROR] {fact.observer}: {payload}")

    from painted import show, Block
    from painted.palette import current_palette
    show(Block.text(
        f"Started {program.vertex.name}: {len(program.sources)} sources",
        current_palette().muted,
    ), file=sys.stderr)

    def fetch():
        collected: list[dict] = []

        async def _collect():
            completed_rounds = 0
            if rounds is not None:
                seen: set[str] = set()
                expected = set(program.expected_ticks)

            async for tick in program.run(on_error=log_error):
                collected.append({
                    "name": tick.name,
                    "ts": tick.ts,
                    "payload": tick.payload,
                    "origin": getattr(tick, "origin", ""),
                })
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
            accumulated.append({
                "name": tick.name,
                "ts": tick.ts,
                "payload": tick.payload,
                "origin": getattr(tick, "origin", ""),
            })
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
    )


def _run_compile(argv: list[str]) -> int:
    """Run compile command via painted CLI harness."""
    from painted import run_cli
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
                data["parse"] = [
                    f"{type(op).__name__}: {op}" for op in source.parse
                ]
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
                    "folds": [
                        f"{type(fold).__name__}: {fold}" for fold in spec.folds
                    ],
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
    )


def _run_start(argv: list[str]) -> int:
    """Run start command via painted CLI harness."""
    from painted import run_cli
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
        show(Block.text("Warning: no sources discovered or configured", current_palette().warning), file=sys.stderr)
        return 0

    from painted import show, Block
    from painted.palette import current_palette
    show(Block.text(
        f"Starting {program.vertex.name} with {len(program.sources)} source(s)...",
        current_palette().muted,
    ), file=sys.stderr)

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


def _resolve_vertex_store_path(vertex_path: Path) -> Path | None:
    """Resolve store path from a vertex file. Returns None if no store configured."""
    from lang import parse_vertex_file

    ast = parse_vertex_file(vertex_path)
    if ast.store is None:
        return None

    store_path = Path(ast.store)
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()
    return store_path


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


def cmd_emit(args: argparse.Namespace) -> int:
    """Inject a fact directly into a vertex store (or print in --dry-run)."""
    from atoms import Fact
    from lang import parse_vertex_file
    from lang.population import (
        list_file_header,
        list_file_read,
        resolve_template,
        resolve_vertex,
    )
    from loops.pop_store import (
        POP_ADD_KIND,
        POP_RM_KIND,
        pop_materialize_list,
        pop_store_has_facts,
    )
    from painted import show, Block
    from painted.palette import current_palette
    p = current_palette()

    # Resolve vertex: explicit arg → LOOPS_HOME → local cwd → auto-init
    #
    # Argparse ambiguity: with vertex as nargs="?", `emit decision topic=x`
    # gives vertex="decision", kind="topic=x". We detect this by checking
    # whether the vertex arg actually resolves. If not, reinterpret it as
    # the kind and shift args.
    vertex_ref = args.vertex
    kind = args.kind
    parts = list(args.parts or [])
    template_qualifier = None

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
        # No vertex: try local, then auto-init
        local = _find_local_vertex()
        if local is not None:
            vertex_path = local.resolve()
        else:
            vertex_path = _init_local_vertex("session").resolve()
            show(Block.text(f"Auto-initialized: {vertex_path}", p.muted), file=sys.stderr)

    payload = _parse_emit_parts(parts)
    ts = datetime.now(timezone.utc).timestamp()
    fact = Fact(
        kind=kind,
        ts=ts,
        payload=payload,
        observer=args.observer or "",
        origin="",
    )

    if args.dry_run:
        show(Block.text(json.dumps(fact.to_dict(), sort_keys=True, default=str), p.muted), file=sys.stdout)
        return 0

    try:
        store_path = _resolve_vertex_store_path(vertex_path)
    except Exception as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1

    if store_path is None:
        show(Block.text("Error: vertex has no store configured", p.error), file=sys.stderr)
        return 1

    try:
        from engine import SqliteStore

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
                show(Block.text(
                    "Error: multiple templates in vertex; specify one as "
                    "'vertex/template' or include template=... in payload",
                    p.error,
                ), file=sys.stderr)
                return 1

            template = resolve_template(ast, qualifier)
            template_name = template.template.stem if is_multi else None

            if template.from_ is None or not hasattr(template.from_, "path"):
                show(Block.text(
                    "Error: template has no 'from file' population configured",
                    p.error,
                ), file=sys.stderr)
                return 1

            list_path = template.from_.path
            if not Path(list_path).is_absolute():
                list_path = (vertex_path.parent / list_path).resolve()
            else:
                list_path = Path(list_path)

            header = list_file_header(list_path)
            if not header:
                show(Block.text(
                    f"Error: no .list header found at {list_path}",
                    p.error,
                ), file=sys.stderr)
                return 1

            if kind == POP_ADD_KIND:
                if "key" not in payload:
                    show(Block.text("Error: pop.add requires key=...", p.error), file=sys.stderr)
                    return 1
                missing = [h for h in header[1:] if h not in payload]
                if missing:
                    show(Block.text(
                        "Error: pop.add requires all non-key columns: "
                        + ", ".join(missing),
                        p.error,
                    ), file=sys.stderr)
                    return 1
            if kind == POP_RM_KIND and "key" not in payload:
                show(Block.text("Error: pop.rm requires key=...", p.error), file=sys.stderr)
                return 1

            if template_name is not None:
                if "template" in payload and payload.get("template") != template_name:
                    show(Block.text(
                        f"Error: payload template={payload.get('template')!r} does not match "
                        f"resolved template {template_name!r}",
                        p.error,
                    ), file=sys.stderr)
                    return 1
                payload["template"] = template_name

        store_path.parent.mkdir(parents=True, exist_ok=True)
        with SqliteStore(
            path=store_path,
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        ) as store:
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
                                store.append(seed_fact)
            store.append(fact)

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


def _run_app(app_name: str, argv: list[str]) -> int:
    """Dispatch to a registered app — resolves vertex, loads module, routes subcommand."""
    import importlib

    mod = importlib.import_module(_APPS[app_name])

    # Resolve the app's vertex: local cwd first, then named resolution via LOOPS_HOME
    vertex_path = None
    local = Path.cwd() / f"{app_name}.vertex"
    if local.exists():
        vertex_path = local
    else:
        try:
            vertex_path = _resolve_named_vertex(app_name)
        except FileNotFoundError:
            vertex_path = None
        except ValueError:
            vertex_path = None

    # Build available subcommands from module exports
    subs: list[str] = []
    # status/log always available (generic fallback exists)
    subs.append("status")
    subs.append("log")
    # search available if vertex has search-declared kinds (always offer it)
    subs.append("search")
    # feedback handlers
    feedback = getattr(mod, "FEEDBACK", {})
    subs.extend(feedback.keys())

    if not argv:
        _err(f"Usage: loops {app_name} <{'|'.join(subs)}>")
        return 1

    sub = argv[0]
    rest = argv[1:]

    def _require_vertex() -> Path | None:
        if vertex_path is not None:
            return vertex_path
        _err(f"No {app_name} vertex found. Run 'loops init {app_name}' first.")
        return None

    if sub == "status":
        vp = _require_vertex()
        return 1 if vp is None else _run_app_status(vp, mod, rest)

    if sub == "log":
        vp = _require_vertex()
        return 1 if vp is None else _run_app_log(vp, mod, rest)

    if sub == "search":
        vp = _require_vertex()
        return 1 if vp is None else _run_app_search(vp, mod, rest)

    if sub in feedback:
        vp = _require_vertex()
        if vp is None:
            return 1
        handler_ref = feedback[sub]
        handler_mod, handler_fn = handler_ref.rsplit(":", 1)
        handler = getattr(importlib.import_module(handler_mod), handler_fn)
        parser = argparse.ArgumentParser(prog=f"loops {app_name} {sub}")
        parser.add_argument("name", help=f"{sub.capitalize()} name")
        parser.add_argument("--conversation", required=True, help="Conversation ID")
        parser.add_argument("--note", default="", help="Optional note")
        parser.add_argument("--observer", default=os.environ.get("LOOPS_OBSERVER", "user"))
        args = parser.parse_args(rest)
        return handler(vp, args)

    _err(f"Unknown {app_name} command: {sub}")
    return 1


def _resolve_app_view(mod, view_name: str):
    """Resolve a view function from an app module.

    Lookup order:
    1. mod.<view_name> — app provides a specific view function
    2. PAYLOAD_LENS — app provides a lens, generic view wraps it
    3. None — caller falls back to shared loops lenses
    """
    specific = getattr(mod, view_name, None)
    if specific is not None:
        return specific

    payload_lens = getattr(mod, "PAYLOAD_LENS", None)
    if payload_lens is not None and view_name in ("log_view", "search_view"):
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
            return Block.text("No facts in the given time range.", Style(dim=True), width=width)

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
                        rows.append(Block.text(f"           {key}: {val}", dim, width=width))

        return join_vertical(*rows)

    return log_view


def _run_app_status(vertex_path: Path, mod, argv: list[str]) -> int:
    """Run app status via run_cli."""
    from painted import run_cli
    from engine import vertex_read

    pre = argparse.ArgumentParser(add_help=False)
    known, rest = pre.parse_known_args(argv)

    render_fn = _resolve_app_view(mod, "status_view")
    if render_fn is None:
        from .lenses.status import status_view as render_fn

    def fetch():
        fold_state = vertex_read(vertex_path)
        fetch_fn = getattr(mod, "fetch_status", None)
        if fetch_fn is not None:
            return fetch_fn(fold_state)
        return _generic_fold_summary(fold_state)

    def render(ctx, data):
        return render_fn(data, ctx.zoom, ctx.width)

    return run_cli(
        rest, fetch=fetch, render=render,
        prog=f"loops {getattr(mod, 'APP_NAME', '?')} status",
        description="Show store status",
    )


def _run_app_log(vertex_path: Path, mod, argv: list[str]) -> int:
    """Run app log via run_cli."""
    from painted import run_cli
    from engine import vertex_facts

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--since", default="7d")
    pre.add_argument("--kind", default=None)
    known, rest = pre.parse_known_args(argv)

    render_fn = _resolve_app_view(mod, "log_view")
    if render_fn is None:
        from .lenses.log import log_view as render_fn

    def fetch():
        import re
        m = re.match(r"^(\d+)([dhms])$", known.since)
        if not m:
            return []
        value = int(m.group(1))
        unit = m.group(2)
        multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
        duration = value * multipliers[unit]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        since_ts = now.timestamp() - duration
        facts = vertex_facts(vertex_path, since_ts, now.timestamp(), kind=known.kind)
        facts.sort(key=lambda f: f["ts"], reverse=True)
        return facts

    def render(ctx, data):
        return render_fn(data, ctx.zoom, ctx.width)

    return run_cli(
        rest, fetch=fetch, render=render,
        prog=f"loops {getattr(mod, 'APP_NAME', '?')} log",
        description="Show recent facts",
    )


def _run_app_search(vertex_path: Path, mod, argv: list[str]) -> int:
    """Run app search via run_cli."""
    from painted import run_cli

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("query", nargs="*")
    pre.add_argument("--kind", default=None)
    pre.add_argument("--since", default=None)
    pre.add_argument("--limit", type=int, default=100)
    known, rest = pre.parse_known_args(argv)

    query_str = " ".join(known.query) if known.query else ""

    render_fn = _resolve_app_view(mod, "search_view")
    if render_fn is None:
        render_fn = _resolve_app_view(mod, "log_view")
    if render_fn is None:
        from .lenses.log import log_view as render_fn

    def fetch():
        if not query_str:
            return []
        from engine import vertex_search
        since_ts = None
        if known.since:
            import re
            m = re.match(r"^(\d+)([dhms])$", known.since)
            if m:
                value = int(m.group(1))
                unit = m.group(2)
                multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                since_ts = now.timestamp() - value * multipliers[unit]
        return vertex_search(
            vertex_path, query_str,
            kind=known.kind, since=since_ts, limit=known.limit,
        )

    def render(ctx, data):
        return render_fn(data, ctx.zoom, ctx.width)

    return run_cli(
        rest, fetch=fetch, render=render,
        prog=f"loops {getattr(mod, 'APP_NAME', '?')} search",
        description="Search facts",
    )


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


def _run_status(argv: list[str]) -> int:
    """Run status command via painted CLI harness."""
    from painted import run_cli
    from .commands.session import _resolve_local_vertex, fetch_status
    from .lenses.status import status_view

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("vertex", nargs="?", default=None)
    pre.add_argument("--kind", default=None)
    known, rest = pre.parse_known_args(argv)

    def fetch():
        if known.vertex is not None:
            vertex_path = _resolve_named_vertex(known.vertex)
        else:
            vertex_path = _resolve_local_vertex()
        return fetch_status(vertex_path, kind=known.kind)

    def render(ctx, data):
        return status_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops status",
        description="Show local store status",
    )


def _run_log(argv: list[str]) -> int:
    """Run log command via painted CLI harness."""
    from painted import run_cli
    from .commands.session import _resolve_local_vertex, fetch_log
    from .lenses.log import log_view

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("vertex", nargs="?", default=None)
    pre.add_argument("--since", default="7d")
    pre.add_argument("--kind", default=None)
    known, rest = pre.parse_known_args(argv)

    def fetch():
        if known.vertex is not None:
            vertex_path = _resolve_named_vertex(known.vertex)
        else:
            vertex_path = _resolve_local_vertex()
        return fetch_log(vertex_path, known.since, known.kind)

    def render(ctx, data):
        return log_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops log",
        description="Show recent facts",
    )


def _run_store(argv: list[str]) -> int:
    """Run store command via painted CLI harness."""
    from painted import run_cli, OutputMode

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("file", nargs="?", default=None)
    known, rest = pre.parse_known_args(argv)
    file_arg = known.file

    def _resolve_store_target() -> Path:
        """Resolve file arg: vertex name, path, or LOOPS_HOME/root.vertex fallback."""
        if file_arg is not None:
            p = Path(file_arg)
            # If it looks like a path (has extension or path separators), use directly
            if p.suffix or file_arg.startswith("./") or file_arg.startswith("/"):
                return p
            # Otherwise treat as vertex name
            from lang.population import resolve_vertex
            return resolve_vertex(file_arg, loops_home())
        root = loops_home() / "root.vertex"
        if not root.exists():
            raise FileNotFoundError(
                f"{root} not found. Run 'loops init' first."
            )
        return root

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
    )


def _run_ls(argv: list[str]) -> int:
    """Run ls command via painted CLI harness."""
    from painted import run_cli
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
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="loops",
        description="Runtime for .loop and .vertex files",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    init_parser = subparsers.add_parser("init", help="Initialize loops config directory")
    init_parser.add_argument(
        "name", nargs="?", default=None,
        help="Vertex name (e.g., 'project' or 'dev/project')",
    )
    init_parser.add_argument(
        "--template", "-t", choices=list(_TEMPLATES),
        help="Template to use",
    )

    # store
    store_parser = subparsers.add_parser(
        "store", help="Inspect store contents"
    )
    store_parser.add_argument("file", nargs="?", default=None, help=".vertex or .db file")

    # emit
    emit_parser = subparsers.add_parser(
        "emit", help="Inject a fact into a vertex store"
    )
    emit_parser.add_argument("vertex", nargs="?", default=None, help="Vertex name or .vertex path (optional; auto-resolves local vertex)")
    emit_parser.add_argument("kind", help="Fact kind")
    emit_parser.add_argument(
        "parts",
        nargs="*",
        help="KEY=VALUE pairs and optional trailing message text",
    )
    emit_parser.add_argument(
        "--observer",
        default="",
        help="Observer string (default: empty)",
    )
    emit_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the fact JSON without storing",
    )

    # Population management
    add_parser = subparsers.add_parser("add", help="Add to template population")
    add_parser.add_argument("target", help="Vertex name or vertex/template")
    add_parser.add_argument("values", nargs="+", help="Column values in header order")

    rm_parser = subparsers.add_parser("rm", help="Remove from template population")
    rm_parser.add_argument("target", help="Vertex name or vertex/template")
    rm_parser.add_argument("key", help="Key (first column) to remove")

    export_parser = subparsers.add_parser("export", help="Inline with -> .list file")
    export_parser.add_argument("target", help="Vertex name or vertex/template")
    export_parser.add_argument(
        "--output",
        "-o",
        help="(deprecated) ignored; export materializes configured .list",
    )

    # status, log, store, start: routed through run_cli in main(), not via argparse.
    # Their parsers live inside _run_status/_run_log/_run_store/_run_start.

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    if argv is None:
        argv = sys.argv[1:]

    # Display commands routed through painted run_cli
    _display = {
        "status": _run_status,
        "log": _run_log,
        "store": _run_store,
        "start": _run_start,
        "compile": _run_compile,
        "validate": _run_validate,
        "test": _run_test,
        "ls": _run_ls,
        "run": _run_run,
    }
    if argv and argv[0] in _display:
        return _display[argv[0]](argv[1:])

    # Registered app dispatch — `loops <app> <command>`
    if argv and argv[0] in _APPS:
        return _run_app(argv[0], argv[1:])

    # All other commands via shared parser
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return cmd_init(args)
    elif args.command == "emit":
        return cmd_emit(args)
    elif args.command == "add":
        from .commands.pop import cmd_add
        return cmd_add(args)
    elif args.command == "rm":
        from .commands.pop import cmd_rm
        return cmd_rm(args)
    elif args.command == "export":
        from .commands.pop import cmd_export
        return cmd_export(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
