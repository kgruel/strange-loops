"""Dev commands — validate, test, compile."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loops.cli.output import Reporter


def _reporter(reporter: "Reporter | None") -> "Reporter":
    """Resolve a Reporter — caller-supplied or the module default."""
    if reporter is None:
        from loops.cli.output import default_reporter
        return default_reporter()
    return reporter


def _lifecycle_scan(vertex_path: Path) -> list[dict]:
    """Minimal folded-state lifecycle scan for `loops validate` (arbiter S5-F2).

    For a ``.vertex`` declaring ``lifecycle`` on any kind, fold its store and
    collect non-fatal WARN rows:

      * ``active-targets-inactive`` — a VISIBLE entity (anything not itself
        folded inactive) carries an edge/ref to an entity folded INACTIVE
        (status present but outside its kind's active set). A live reference to
        something the default view hides.
      * ``missing-status`` — an entity under a lifecycle-declared kind lacks the
        status field entirely, so the fail-open SHOW (arbiter S5-F1) is visible
        rather than silent.

    Warns never change the exit code. Edge targets resolve through
    ``atoms.Address`` readings (never string-splitting) — the SAME match
    semantic inbound counting uses, so a colon address never cross-kind aliases.
    This is the first-tenant precedent of the general folded-state constraint
    surface (design:architecture/payload-constraints-in-declarations), not its
    implementation — it scans exactly one edge class and never opens the wider
    ``--store/--refs/--foreign-refs`` surface.
    """
    from atoms import Address
    from lang import parse_vertex_file
    from loops.commands.fetch import fetch_fold

    try:
        ast = parse_vertex_file(vertex_path)
    except Exception:
        return []  # a syntax error is already reported by the main pass
    loops = ast.loops or {}
    if not any(ld.lifecycle is not None for ld in loops.values()):
        return []
    if not ast.store:
        return []
    store_path = (vertex_path.parent / ast.store).resolve()
    if not store_path.exists():
        return []
    try:
        state = fetch_fold(vertex_path)
    except Exception:
        return []

    warnings: list[dict] = []
    # Every inactive entity is reachable by its (kind,key) reading AND the bare
    # ('',key) fallback — an edge matches it iff the edge's readings intersect
    # this set (mirrors _inbound_count's `inbound[(kind,key)] + inbound[('',key)]`).
    inactive_receiving: set[Address] = set()
    inactive_label: dict[Address, str] = {}
    entities: list[dict] = []
    for section in state.sections:
        lc = section.lifecycle
        kf = section.key_field
        for item in section.items:
            key = item.payload.get(kf) if kf else None
            status_class = "none"
            if lc is not None:
                field_name, active = lc
                value = item.payload.get(field_name)
                if value is None:
                    status_class = "missing"
                    warnings.append({
                        "kind": "missing-status",
                        "source": f"{section.kind}:{key}" if key else section.kind,
                        "field": field_name,
                    })
                elif value not in active:
                    status_class = "inactive"
                    if key is not None:
                        a1 = Address(kind=section.kind, key=str(key))
                        a2 = Address(kind="", key=str(key))
                        inactive_receiving.add(a1)
                        inactive_receiving.add(a2)
                        inactive_label[a1] = f"{section.kind}:{key} (status={value})"
                else:
                    status_class = "active"
            entities.append({
                "kind": section.kind,
                "key": key,
                "status_class": status_class,
                "refs": tuple(item.refs),
                "edges": tuple(item.edges),
            })

    if not inactive_receiving:
        return warnings

    seen: set[tuple] = set()
    for e in entities:
        if e["status_class"] == "inactive":
            continue  # no warn when the source is itself inactive
        addrs = list(e["refs"]) + [edge.address for edge in e["edges"]]
        src = f"{e['kind']}:{e['key']}" if e["key"] is not None else e["kind"]
        for addr in addrs:
            hit = set(Address.readings(addr)) & inactive_receiving
            if not hit:
                continue
            target = next(
                (inactive_label[a] for a in hit if a in inactive_label), addr,
            )
            row = ("active-targets-inactive", src, target)
            if row in seen:
                continue
            seen.add(row)
            warnings.append({
                "kind": "active-targets-inactive",
                "source": src,
                "target": target,
            })
    return warnings


def _run_validate(argv: list[str], *, reporter: "Reporter | None" = None) -> int:
    """Run validate command via painted CLI harness.

    The ``files`` positional is pre-parsed; ``run_cli`` owns ``-h`` and
    lists the arg in --help via ``help_args`` (painted's pre-parse +
    describe-for-help idiom — decision:design/devtools-help-args-idiom).
    No hand-rolled help block.
    """
    from painted import run_cli
    from painted.cli import HelpArg
    from lang import parse_loop_file, parse_vertex_file, validate
    from loops.lenses.validate import validate_view

    _ = _reporter(reporter)  # reserved for future error routing

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
        warnings: list[dict] = []

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
                continue

            # Folded-state lifecycle scan (S5) — non-fatal WARNs only, over a
            # valid .vertex whose store resolves. Never touches the exit code.
            if path.suffix == ".vertex":
                for w in _lifecycle_scan(path):
                    warnings.append({**w, "path": str(path)})

        data = {
            "results": results,
            "checked": checked,
            "errors": errors,
            "warnings": warnings,
        }
        fetch_result.append(data)
        return data

    def renderer(data, fidelity, width):
        from loops.lens_resolver import zoom_from_fidelity
        return validate_view(data, zoom_from_fidelity(fidelity), width)

    run_cli(
        rest,
        fetch=fetch,
        renderer=renderer,
        prog="loops validate",
        description="Validate .loop or .vertex files",
        help_args=[HelpArg(
            "files", "Files to validate (default: all .loop/.vertex in cwd)",
            positional=True,
        )],
    )
    # run_cli always returns 0 here — fetch catches all exceptions internally.
    # Preserve exit code: 1 if validation errors or no files found
    if fetch_result:
        data = fetch_result[0]
        if data["errors"] > 0 or data["checked"] == 0:
            return 1
    return 0


def _run_test(argv: list[str], *, reporter: "Reporter | None" = None) -> int:
    """Test a .loop file — preview facts without persistence.

    Without --input: run the command, stream output through parse, show facts.
    With --input: use file as input for parse pipeline instead of running.
    """
    from painted import run_cli
    from painted.cli import HelpArg
    from lang import parse_loop_file, validate_loop
    from engine import compile_loop

    rep = _reporter(reporter)

    # test branches on --input *before* dispatching to run_cli (the two
    # modes call run_cli differently — run mode adds fetch_stream), so a
    # pre-parse is inherent here. run_cli owns -h and lists these args via
    # help_args; the fetch closures close over the pre-parsed ``known``.
    _HELP_ARGS = [
        HelpArg("file", "Loop file to test", positional=True),
        HelpArg("--input, -i", "Input file to feed through parse pipeline"),
        HelpArg("--limit, -n", "Max facts to show"),
    ]

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("file", nargs="?", default=None)
    pre.add_argument("--input", "-i", default=None)
    pre.add_argument("--limit", "-n", type=int, default=None)
    known, rest = pre.parse_known_args(argv)

    # -h must reach run_cli before the required-file guard. Route a bare
    # help request straight to run_cli's help renderer (stub fetch/render —
    # help short-circuits before either runs).
    if "-h" in rest or "--help" in rest:
        return run_cli(
            rest, fetch=lambda: None, renderer=lambda d, f, w: None,
            prog="loops test", help_args=_HELP_ARGS,
            description="Test a .loop file — preview facts",
        )

    if known.file is None:
        rep.err("Error: test requires a .loop file")
        return 2

    path = Path(known.file)
    if not path.exists():
        rep.err(f"Error: {path} does not exist")
        return 1

    if path.suffix != ".loop":
        rep.err("Error: test command only works with .loop files")
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

        def renderer(data, fidelity, width):
            from loops.lens_resolver import zoom_from_fidelity
            return test_view(data, zoom_from_fidelity(fidelity), width)

        return run_cli(
            rest,
            fetch=fetch,
            renderer=renderer,
            prog="loops test",
            description="Test parse pipeline against sample input",
            help_args=_HELP_ARGS,
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

        def renderer(data, fidelity, width):
            from loops.lens_resolver import zoom_from_fidelity
            return run_facts_view(data, zoom_from_fidelity(fidelity), width)

        return run_cli(
            rest,
            fetch=fetch,
            fetch_stream=fetch_stream,
            renderer=renderer,
            prog="loops test",
            description=f"Run {path.name} — preview facts, no persistence",
            help_args=_HELP_ARGS,
        )


def _run_compile(argv: list[str], *, reporter: "Reporter | None" = None) -> int:
    """Run compile command via painted CLI harness."""
    from painted import run_cli
    from lang import parse_loop_file, parse_vertex_file, validate
    from engine import compile_vertex
    from loops.lenses.compile import compile_view

    from painted.cli import HelpArg

    rep = _reporter(reporter)

    # Pre-parse the ``file`` positional (drives the existence guard and the
    # fetch closure); run_cli owns -h and lists it via help_args.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("file", nargs="?", default=None)
    known, rest = pre.parse_known_args(argv)
    # -h must reach run_cli (which renders help + exits before fetch); don't
    # let the required-file guard pre-empt it.
    want_help = "-h" in rest or "--help" in rest
    if known.file is None and not want_help:
        rep.err("Error: compile requires a .loop or .vertex file")
        return 2
    path = Path(known.file) if known.file else None
    if path is not None and not path.exists():
        rep.err(f"Error: {path} does not exist")
        return 1

    def fetch():
        assert path is not None  # guaranteed: help short-circuits before fetch
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

    def renderer(data, fidelity, width):
        from loops.lens_resolver import zoom_from_fidelity
        return compile_view(data, zoom_from_fidelity(fidelity), width)

    return run_cli(
        rest,
        fetch=fetch,
        renderer=renderer,
        prog="loops compile",
        description="Show compiled structure",
        help_args=[HelpArg(
            "file", "Loop or vertex file to compile", positional=True,
        )],
    )
