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

_TEMPLATES: dict[str, str] = {
    "session": _SESSION_VERTEX,
    "tasks": _TASKS_VERTEX,
}


def _find_local_vertex() -> Path | None:
    """Find a .vertex file in cwd. Returns first match or None."""
    matches = sorted(Path.cwd().glob("*.vertex"))
    return matches[0] if matches else None


def _init_local_vertex(template: str) -> Path:
    """Create a vertex + data dir in cwd from a template. Returns vertex path."""
    content = _TEMPLATES[template]
    vertex_path = Path.cwd() / f"{template}.vertex"
    if not vertex_path.exists():
        vertex_path.write_text(content)
    data_dir = Path.cwd() / "data"
    data_dir.mkdir(exist_ok=True)
    return vertex_path


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a loops config directory or local vertex from template."""
    template = getattr(args, "template", None)

    if template:
        vertex_path = _init_local_vertex(template)
        print(f"Created {vertex_path}")
        return 0

    # Default: root vertex in LOOPS_HOME
    home = loops_home()
    root = home / "root.vertex"
    if root.exists():
        print(f"Already initialized: {root}")
        return 0
    home.mkdir(parents=True, exist_ok=True)
    root.write_text(_ROOT_VERTEX)
    print(f"Created {root}")
    return 0


def _resolve_vertex_path(file_arg: str | None) -> Path | None:
    """Resolve a vertex file path, defaulting to LOOPS_HOME/root.vertex."""
    if file_arg is not None:
        return Path(file_arg)
    root = loops_home() / "root.vertex"
    if not root.exists():
        print(
            f"Error: {root} not found. Run 'loops init' first.",
            file=sys.stderr,
        )
        return None
    return root


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate one or more .loop/.vertex files (silently skips other types)."""
    from lang import parse_loop_file, parse_vertex_file, validate

    errors = 0
    checked = 0

    files = args.files
    if not files:
        # No args: discover .loop/.vertex files from cwd downward
        cwd = Path.cwd()
        files = sorted(
            str(p) for p in cwd.rglob("*") if p.suffix in (".loop", ".vertex")
        )

    for file in files:
        path = Path(file)
        if path.suffix not in (".loop", ".vertex"):
            continue  # skip non-DSL files from globs

        if not path.exists():
            print(f"Error: {path} does not exist", file=sys.stderr)
            errors += 1
            continue

        try:
            if path.suffix == ".loop":
                ast = parse_loop_file(path)
            else:
                ast = parse_vertex_file(path)

            validate(ast)
            print(f"\u2713 {path} is valid")
            checked += 1

        except Exception as e:
            print(f"\u2717 {path}: {e}", file=sys.stderr)
            errors += 1

    if errors:
        return 1
    if checked == 0:
        print("No .loop or .vertex files found", file=sys.stderr)
        return 1
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Test a .loop file's parse pipeline against sample input."""
    from atoms import run_parse
    from lang import parse_loop_file, validate_loop
    from engine import compile_loop

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    if path.suffix != ".loop":
        print(f"Error: test command only works with .loop files", file=sys.stderr)
        return 1

    try:
        ast = parse_loop_file(path)
        validate_loop(ast)
        source = compile_loop(ast)

        if source.parse is None:
            print("Warning: no parse pipeline defined", file=sys.stderr)
            return 0

        # Read input
        if args.input:
            input_path = Path(args.input)
            if not input_path.exists():
                print(f"Error: {input_path} does not exist", file=sys.stderr)
                return 1
            lines = input_path.read_text().splitlines()
        else:
            # Read from stdin
            lines = sys.stdin.read().splitlines()

        # Process each line
        results = []
        skipped = 0
        errors = 0

        for line in lines:
            result = run_parse(line, source.parse)
            if result is None:
                skipped += 1
            else:
                results.append(result)

        # Output results
        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            for result in results:
                print(result)

        # Summary
        print(f"\n--- {len(results)} parsed, {skipped} skipped ---", file=sys.stderr)
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Execute a .loop or .vertex file."""
    resolved = _resolve_vertex_path(args.file)
    if resolved is None:
        return 1
    path = resolved.resolve()
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    if path.suffix == ".vertex":
        return _run_vertex(path, args)
    elif path.suffix == ".loop":
        return _run_loop(path, args)
    else:
        print(f"Error: run expects a .loop or .vertex file, got {path.suffix}", file=sys.stderr)
        return 1


def _run_loop(path: Path, args: argparse.Namespace) -> int:
    """Execute a .loop file and print facts."""
    from lang import parse_loop_file, validate_loop
    from engine import compile_loop

    try:
        ast = parse_loop_file(path)
        validate_loop(ast)
        source = compile_loop(ast)

        async def stream_facts():
            count = 0
            async for fact in source.stream():
                if args.json:
                    print(json.dumps(fact.payload, default=str))
                else:
                    print(f"[{fact.kind}] {fact.payload}")
                count += 1
                if args.limit and count >= args.limit:
                    break

        asyncio.run(stream_facts())
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _run_vertex(path: Path, args: argparse.Namespace) -> int:
    """Run a .vertex file. Defaults to 1 round; --daemon for continuous."""
    from engine import load_vertex_program

    try:
        vars = _parse_vars(getattr(args, "var", []))
        program = load_vertex_program(path, vars=vars or None)

        if not program.sources:
            print("Error: no sources configured", file=sys.stderr)
            return 1

        daemon = getattr(args, "daemon", False)
        rounds = getattr(args, "rounds", 1)
        if daemon or rounds == 0:
            rounds = None  # None = run forever
        use_json = getattr(args, "json", False)

        def log_error(fact):
            payload = dict(fact.payload) if hasattr(fact.payload, 'items') else fact.payload
            print(
                f"[ERROR] {fact.observer}: {payload}",
                file=sys.stderr,
                flush=True,
            )

        async def run():
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, stop.set)

            print(
                f"Started {program.vertex.name}: {len(program.sources)} sources",
                file=sys.stderr,
                flush=True,
            )

            completed_rounds = 0
            if rounds is not None:
                seen: set[str] = set()
                expected = set(program.expected_ticks)

            async for tick in program.run(on_error=log_error):
                if stop.is_set():
                    break

                if use_json:
                    print(json.dumps({
                        "name": tick.name,
                        "ts": tick.ts,
                        "payload": tick.payload,
                    }, default=str), flush=True)
                else:
                    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    print(f"[{ts}] tick: {tick.name} ({len(tick.payload)} keys)", flush=True)

                if rounds is not None:
                    seen.add(tick.name)
                    if seen >= expected:
                        completed_rounds += 1
                        if completed_rounds >= rounds:
                            break
                        seen = set()

            print("Stopped", file=sys.stderr, flush=True)

        asyncio.run(run())
        return 0

    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_compile(args: argparse.Namespace) -> int:
    """Show compiled structure of a .loop or .vertex file."""
    from lang import parse_loop_file, parse_vertex_file, validate
    from engine import compile_loop, compile_vertex

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    try:
        if path.suffix == ".loop":
            ast = parse_loop_file(path)
            validate(ast)
            source = compile_loop(ast)

            print(f"Source: {path.name}")
            print(f"  command: {source.command}")
            print(f"  kind: {source.kind}")
            print(f"  observer: {source.observer}")
            print(f"  every: {source.every}s" if source.every else "  every: (once)")
            print(f"  format: {source.format}")
            if source.parse:
                print(f"  parse: {len(source.parse)} ops")
                for i, op in enumerate(source.parse):
                    print(f"    {i+1}. {type(op).__name__}: {op}")

        elif path.suffix == ".vertex":
            ast = parse_vertex_file(path)
            validate(ast)
            specs = compile_vertex(ast)

            print(f"Vertex: {ast.name}")
            if ast.store:
                print(f"  store: {ast.store}")
            if ast.discover:
                print(f"  discover: {ast.discover}")
            if ast.emit:
                print(f"  emit: {ast.emit}")

            print(f"\nLoops ({len(specs)}):")
            for name, spec in specs.items():
                print(f"\n  {name}:")
                print(f"    state_fields: {[f.name for f in spec.state_fields]}")
                print(f"    folds: {len(spec.folds)}")
                for fold in spec.folds:
                    print(f"      - {type(fold).__name__}: {fold}")
                if spec.boundary:
                    print(f"    boundary: {spec.boundary.kind}")

            if ast.routes:
                print(f"\nRoutes:")
                for kind, loop in ast.routes.items():
                    print(f"  {kind} -> {loop}")

        else:
            print(f"Error: Unknown file type: {path.suffix}", file=sys.stderr)
            return 1

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_store(args: argparse.Namespace) -> int:
    """Inspect store contents."""
    from cells import (
        Format,
        OutputMode,
        detect_context,
        parse_format,
        parse_mode,
        parse_zoom,
        print_block,
    )

    from .commands.store import make_fetcher
    from .lenses.store import store_view

    resolved = _resolve_vertex_path(args.file)
    if resolved is None:
        return 1
    path = resolved.resolve()
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    try:
        zoom = parse_zoom(args)
        mode = parse_mode(args)
        fmt = parse_format(args)
        ctx = detect_context(zoom, mode, fmt)

        if ctx.mode == OutputMode.INTERACTIVE:
            from .tui import StoreExplorerApp

            app = StoreExplorerApp(path)
            asyncio.run(app.run())
            return 0

        fetch = make_fetcher(path, zoom=ctx.zoom.value)
        data = fetch()

        if ctx.format == Format.JSON:
            print(json.dumps(data, indent=2, default=str))
        else:
            block = store_view(data, ctx.zoom, ctx.width)
            print_block(block, use_ansi=ctx.format != Format.PLAIN)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_start(args: argparse.Namespace) -> int:
    """Run a .vertex file (start sources and vertex)."""
    from cells import (
        Zoom,
        Format,
        detect_context,
        parse_zoom,
        parse_mode,
        parse_format,
        Block,
        Style,
        print_block,
        join_vertical,
    )
    from cells.lens import shape_lens
    from engine import load_vertex_program

    resolved = _resolve_vertex_path(args.file)
    if resolved is None:
        return 1
    path = resolved
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    if path.suffix != ".vertex":
        print(f"Error: start command only works with .vertex files", file=sys.stderr)
        return 1

    try:
        vars = _parse_vars(getattr(args, "var", []))
        program = load_vertex_program(path, vars=vars or None)

        if not program.sources:
            print("Warning: no sources discovered or configured", file=sys.stderr)
            return 0

        # Parse fidelity
        zoom = parse_zoom(args)
        mode = parse_mode(args)
        fmt = parse_format(args)
        ctx = detect_context(zoom, mode, fmt)

        print(
            f"Starting {program.vertex.name} with {len(program.sources)} source(s)...",
            file=sys.stderr,
        )

        # Collect all ticks
        results = program.collect(rounds=1)

        # Render based on format
        if ctx.format == Format.JSON:
            print(json.dumps(results, indent=2, default=str))
        elif ctx.zoom == Zoom.MINIMAL:
            print(f"{program.vertex.name}: {len(results)} ticks")
        else:
            blocks = []
            for name, payload in results.items():
                header = Block.text(f"[{name}]", Style(bold=True), width=ctx.width)
                body = shape_lens(payload, zoom=ctx.zoom.value, width=ctx.width - 2)
                blocks.extend([header, body, Block.empty(ctx.width, 1)])
            if blocks:
                blocks.pop()  # Remove trailing empty block
                use_ansi = ctx.format != Format.PLAIN
                print_block(join_vertical(*blocks), use_ansi=use_ansi)

        return 0

    except KeyboardInterrupt:
        print("\nStopped", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


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
            print(f"Error: {candidate} not found", file=sys.stderr)
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
            print(f"Auto-initialized: {vertex_path}", file=sys.stderr)

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
        print(json.dumps(fact.to_dict(), sort_keys=True, default=str))
        return 0

    try:
        store_path = _resolve_vertex_store_path(vertex_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if store_path is None:
        print("Error: vertex has no store configured", file=sys.stderr)
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
                print(
                    "Error: multiple templates in vertex; specify one as "
                    "'vertex/template' or include template=... in payload",
                    file=sys.stderr,
                )
                return 1

            template = resolve_template(ast, qualifier)
            template_name = template.template.stem if is_multi else None

            if template.from_ is None or not hasattr(template.from_, "path"):
                print(
                    "Error: template has no 'from file' population configured",
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
                print(
                    f"Error: no .list header found at {list_path}",
                    file=sys.stderr,
                )
                return 1

            if kind == POP_ADD_KIND:
                if "key" not in payload:
                    print("Error: pop.add requires key=...", file=sys.stderr)
                    return 1
                missing = [h for h in header[1:] if h not in payload]
                if missing:
                    print(
                        "Error: pop.add requires all non-key columns: "
                        + ", ".join(missing),
                        file=sys.stderr,
                    )
                    return 1
            if kind == POP_RM_KIND and "key" not in payload:
                print("Error: pop.rm requires key=...", file=sys.stderr)
                return 1

            if template_name is not None:
                if "template" in payload and payload.get("template") != template_name:
                    print(
                        f"Error: payload template={payload.get('template')!r} does not match "
                        f"resolved template {template_name!r}",
                        file=sys.stderr,
                    )
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
        print(f"Error: {e}", file=sys.stderr)
        return 1


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
        "--template", "-t", choices=["session", "tasks"],
        help="Create a local vertex from template (in cwd)",
    )

    # validate
    validate_parser = subparsers.add_parser(
        "validate", help="Validate .loop or .vertex files"
    )
    validate_parser.add_argument("files", nargs="*", help="Files to validate (default: discover from cwd)")

    # test
    test_parser = subparsers.add_parser(
        "test", help="Test parse pipeline against sample input"
    )
    test_parser.add_argument("file", help=".loop file to test")
    test_parser.add_argument(
        "--input", "-i", help="Input file (default: stdin)"
    )
    test_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )

    # run
    run_parser = subparsers.add_parser(
        "run", help="Execute a .loop or .vertex file"
    )
    run_parser.add_argument("file", nargs="?", default=None, help=".loop or .vertex file to run")
    run_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )
    run_parser.add_argument(
        "--limit", "-n", type=int, help="Limit number of facts (.loop only)"
    )
    run_parser.add_argument(
        "--rounds", "-r", type=int, default=1,
        help="Number of complete rounds; 0 = run forever (.vertex only, default: 1)",
    )
    run_parser.add_argument(
        "--daemon", "-d", action="store_true",
        help="Run forever (equivalent to --rounds 0)",
    )
    run_parser.add_argument(
        "--var", action="append", default=[], metavar="KEY=VALUE",
        help="Set vertex var (repeatable, e.g. --var hn_username=kg)",
    )

    # compile
    compile_parser = subparsers.add_parser(
        "compile", help="Show compiled structure"
    )
    compile_parser.add_argument("file", help="File to compile")

    # start
    start_parser = subparsers.add_parser(
        "start", help="Run a .vertex file"
    )
    start_parser.add_argument("file", nargs="?", default=None, help=".vertex file to start")
    start_parser.add_argument(
        "--var", action="append", default=[], metavar="KEY=VALUE",
        help="Set vertex var (repeatable, e.g. --var hn_username=kg)",
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
    ls_parser = subparsers.add_parser("ls", help="List template populations")
    ls_parser.add_argument("target", help="Vertex name or vertex/template")

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

    # status
    status_parser = subparsers.add_parser("status", help="Show local store status")
    status_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )

    # log
    log_parser = subparsers.add_parser("log", help="Show recent facts")
    log_parser.add_argument("--since", default="7d", help="Lookback window (e.g. 7d, 24h)")
    log_parser.add_argument("--kind", help="Filter by fact kind")
    log_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )

    # Add cells fidelity args: -q, -v/-vv, --json, --plain, --static/--live/-i
    from cells import add_cli_args
    add_cli_args(start_parser)
    add_cli_args(store_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return cmd_init(args)
    elif args.command == "validate":
        return cmd_validate(args)
    elif args.command == "test":
        return cmd_test(args)
    elif args.command == "run":
        return cmd_run(args)
    elif args.command == "compile":
        return cmd_compile(args)
    elif args.command == "start":
        return cmd_start(args)
    elif args.command == "store":
        return cmd_store(args)
    elif args.command == "emit":
        return cmd_emit(args)
    elif args.command == "ls":
        from .commands.pop import cmd_ls
        return cmd_ls(args)
    elif args.command == "add":
        from .commands.pop import cmd_add
        return cmd_add(args)
    elif args.command == "rm":
        from .commands.pop import cmd_rm
        return cmd_rm(args)
    elif args.command == "export":
        from .commands.pop import cmd_export
        return cmd_export(args)
    elif args.command == "status":
        from .commands.session import cmd_status
        return cmd_status(args)
    elif args.command == "log":
        from .commands.session import cmd_log
        return cmd_log(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
