"""CLI for the loop DSL.

Commands:
    loop validate <file>           Validate syntax and flow
    loop test <file> --input <f>   Run parse pipeline against sample input
    loop run <file>                Execute a .loop file and print facts
    loop compile <file>            Show compiled structure
    loop start <file>              Run a .vertex file
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TextIO


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a .loop or .vertex file."""
    from .parser import parse_loop_file, parse_vertex_file
    from .validator import validate

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
        print(f"✓ {path} is valid")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_test(args: argparse.Namespace) -> int:
    """Test a .loop file's parse pipeline against sample input."""
    from data import run_parse

    from .mapper import compile_loop
    from .parser import parse_loop_file
    from .validator import validate_loop

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
    """Execute a .loop file and print facts."""
    from .mapper import compile_loop
    from .parser import parse_loop_file
    from .validator import validate_loop

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    if path.suffix != ".loop":
        print(f"Error: run command only works with .loop files", file=sys.stderr)
        return 1

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


def cmd_compile(args: argparse.Namespace) -> int:
    """Show compiled structure of a .loop or .vertex file."""
    from .mapper import compile_loop, compile_vertex
    from .parser import parse_loop_file, parse_vertex_file
    from .validator import validate

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


def cmd_start(args: argparse.Namespace) -> int:
    """Run a .vertex file (start sources and vertex)."""
    from .mapper import compile_loop, compile_vertex
    from .parser import parse_loop_file, parse_vertex_file
    from .validator import validate

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    if path.suffix != ".vertex":
        print(f"Error: start command only works with .vertex files", file=sys.stderr)
        return 1

    try:
        from glob import glob

        from data import Runner
        from vertex import Vertex

        ast = parse_vertex_file(path)
        validate(ast)
        specs = compile_vertex(ast)

        # Create vertex
        vertex = Vertex(ast.name)

        # Register specs
        for name, spec in specs.items():
            boundary_kind = spec.boundary.kind if spec.boundary else None
            reset = spec.boundary.reset if spec.boundary else False
            vertex.register(
                name,
                spec.initial_state(),
                spec.apply,
                boundary=boundary_kind,
                reset=reset,
            )

        # Discover and compile sources
        sources = []
        if ast.discover:
            base = path.parent
            pattern = str(base / ast.discover)
            for loop_path in glob(pattern, recursive=True):
                loop_ast = parse_loop_file(Path(loop_path))
                validate(loop_ast)
                sources.append(compile_loop(loop_ast))
                print(f"Discovered: {loop_path}", file=sys.stderr)

        if ast.sources:
            for source_path in ast.sources:
                full_path = path.parent / source_path
                loop_ast = parse_loop_file(full_path)
                validate(loop_ast)
                sources.append(compile_loop(loop_ast))

        if not sources:
            print("Warning: no sources discovered or configured", file=sys.stderr)
            return 0

        # Create runner and run
        runner = Runner(vertex)
        for source in sources:
            runner.add(source)

        print(f"Starting {ast.name} with {len(sources)} source(s)...", file=sys.stderr)

        async def run():
            async for tick in runner.run():
                if args.json:
                    print(json.dumps({"name": tick.name, "payload": tick.payload}, default=str))
                else:
                    print(f"[{tick.name}] {tick.payload}")

        asyncio.run(run())
        return 0

    except KeyboardInterrupt:
        print("\nStopped", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="loop",
        description="DSL for .loop and .vertex files",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
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
        "run", help="Execute a .loop file and print facts"
    )
    run_parser.add_argument("file", help=".loop file to run")
    run_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )
    run_parser.add_argument(
        "--limit", "-n", type=int, help="Limit number of facts"
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
    start_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )
    start_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )

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
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
