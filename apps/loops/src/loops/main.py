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
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a .loop or .vertex file."""
    from dsl import parse_loop_file, parse_vertex_file, validate

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    try:
        if path.suffix == ".loop":
            ast = parse_loop_file(path)
        elif path.suffix == ".vertex":
            ast = parse_vertex_file(path)
        else:
            print(f"Error: Unknown file type: {path.suffix}", file=sys.stderr)
            return 1

        validate(ast)
        print(f"\u2713 {path} is valid")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_test(args: argparse.Namespace) -> int:
    """Test a .loop file's parse pipeline against sample input."""
    from data import run_parse
    from dsl import parse_loop_file, validate_loop
    from vertex import compile_loop

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
    path = Path(args.file).resolve()
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
    from dsl import parse_loop_file, validate_loop
    from vertex import compile_loop

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
    """Run a .vertex file as a long-lived daemon."""
    from vertex import load_vertex_program

    try:
        program = load_vertex_program(path)

        if not program.sources:
            print("Error: no sources configured", file=sys.stderr)
            return 1

        rounds = getattr(args, "rounds", None)
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
    from dsl import parse_loop_file, parse_vertex_file, validate
    from vertex import compile_loop, compile_vertex

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

    path = Path(args.file).resolve()
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
    from vertex import load_vertex_program

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    if path.suffix != ".vertex":
        print(f"Error: start command only works with .vertex files", file=sys.stderr)
        return 1

    try:
        program = load_vertex_program(path)

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


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="loops",
        description="Runtime for .loop and .vertex files",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    validate_parser = subparsers.add_parser(
        "validate", help="Validate a .loop or .vertex file"
    )
    validate_parser.add_argument("file", help="File to validate")

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
    run_parser.add_argument("file", help=".loop or .vertex file to run")
    run_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )
    run_parser.add_argument(
        "--limit", "-n", type=int, help="Limit number of facts (.loop only)"
    )
    run_parser.add_argument(
        "--rounds", "-r", type=int, help="Number of complete rounds (.vertex only)"
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
    start_parser.add_argument("file", help=".vertex file to start")

    # store
    store_parser = subparsers.add_parser(
        "store", help="Inspect store contents"
    )
    store_parser.add_argument("file", help=".vertex or .db file")

    # Add cells fidelity args: -q, -v/-vv, --json, --plain, --static/--live/-i
    from cells import add_cli_args
    add_cli_args(start_parser)
    add_cli_args(store_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
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
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
