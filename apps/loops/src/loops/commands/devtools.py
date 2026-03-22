"""Dev commands — validate, test, compile."""
from __future__ import annotations

import argparse
from pathlib import Path


def _run_validate(argv: list[str]) -> int:
    """Run validate command via painted CLI harness."""
    from painted import run_cli
    from painted.cli import HelpArg
    from lang import parse_loop_file, parse_vertex_file, validate
    from loops.lenses.validate import validate_view
    from loops.main import _err

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
        w = ctx.width if ctx.is_tty else None
        return validate_view(data, ctx.zoom, w)

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
    """Test a .loop file — preview facts without persistence.

    Without --input: run the command, stream output through parse, show facts.
    With --input: use file as input for parse pipeline instead of running.
    """
    from painted import run_cli
    from painted.cli import HelpArg
    from lang import parse_loop_file, validate_loop
    from engine import compile_loop
    from loops.main import _err

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("file")
    pre.add_argument("--input", "-i", default=None)
    pre.add_argument("--limit", "-n", type=int, default=None)
    known, rest = pre.parse_known_args(argv)

    path = Path(known.file)
    if not path.exists():
        _err(f"Error: {path} does not exist")
        return 1

    if path.suffix != ".loop":
        _err("Error: test command only works with .loop files")
        return 1

    if known.input:
        # Parse-only mode: feed file through parse pipeline
        from atoms import run_parse
        from loops.lenses.test import test_view

        def fetch():
            ast = parse_loop_file(path)
            validate_loop(ast)
            source = compile_loop(ast)

            if source.parse is None:
                return {"results": [], "skipped": 0, "warning": "no parse pipeline defined"}

            input_path = Path(known.input)
            if not input_path.exists():
                raise FileNotFoundError(f"{input_path} does not exist")
            lines = input_path.read_text().splitlines()

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
            w = ctx.width if ctx.is_tty else None
            return test_view(data, ctx.zoom, w)

        return run_cli(
            rest,
            fetch=fetch,
            render=render,
            prog="loops test",
            description="Test parse pipeline against sample input",
            help_args=[
                HelpArg("file", "Loop file to test", positional=True),
                HelpArg("--input", "Input file to feed through parse pipeline"),
                HelpArg("--limit", "Max facts to show"),
            ],
        )

    else:
        # Run mode: execute command, stream through parse, show facts
        from loops.lenses.run import run_facts_view

        ast = parse_loop_file(path)
        validate_loop(ast)
        source = compile_loop(ast)
        limit = known.limit

        def fetch():
            collected: list[dict] = []

            async def _collect():
                count = 0
                async for fact in source.collect():
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

            import asyncio
            asyncio.run(_collect())
            return collected

        async def fetch_stream():
            accumulated: list[dict] = []
            count = 0
            async for fact in source.collect():
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
            w = ctx.width if ctx.is_tty else None
            return run_facts_view(data, ctx.zoom, w)

        return run_cli(
            rest,
            fetch=fetch,
            fetch_stream=fetch_stream,
            render=render,
            prog="loops test",
            description=f"Run {path.name} — preview facts, no persistence",
            help_args=[
                HelpArg("file", "Loop file to test", positional=True),
                HelpArg("--input", "Input file to feed through parse pipeline"),
                HelpArg("--limit", "Max facts to show"),
            ],
        )


def _run_compile(argv: list[str]) -> int:
    """Run compile command via painted CLI harness."""
    from painted import run_cli
    from painted.cli import HelpArg
    from lang import parse_loop_file, parse_vertex_file, validate
    from engine import compile_loop, compile_vertex
    from loops.lenses.compile import compile_view
    from loops.main import _err

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
            from engine import compile_source
            source, cadence = compile_source(ast)
            data: dict = {
                "type": "loop",
                "name": path.name,
                "source_path": abs_path,
                "command": source.command,
                "kind": source.kind,
                "observer": source.observer,
                "cadence": str(cadence),
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
