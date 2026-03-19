"""CLI for the loops runtime.

Verb-first dispatch — three-tier:
  1. Verbs: loops <verb> [vertex] [args]
  2. Commands: loops <command> [args]
  3. Vertex shorthand: loops <vertex> [flags]  (implicit read)

Verbs (vertex operations):
    loops read project                  Read vertex state (fold, default)
    loops read project --facts          Read filtered fact history
    loops read project --facts --kind decision --since 7d
    loops project                       Implicit read (= loops read project)
    loops emit project decision topic=x Inject a fact
    loops sync project                  Run sources (cadence-gated)
    loops sync project --force          Run all sources unconditionally
    loops close thread my-thread        Resolve thread, capture artifacts

Commands:
    loops test <file>                   Test a .loop file (run command, show facts)
    loops test <file> --input <f>       Test parse pipeline against sample input
    loops compile <file>                Show compiled structure
    loops validate <file>               Validate syntax and flow
    loops store [file]                  Inspect store (name, path, or .db)
    loops init [name]                   Initialize vertex
    loops ls                            List vertices
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
# typing deferred — TextIO only used in annotations (strings with __future__)
# argparse deferred — imported lazily in main() after fast-path check (~3ms cold)


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


_MINIMAL_INSTANCE = """\
name "{name}"
store "{store}"

loops {{
}}
"""


def _extract_block_text(content: str, keyword: str) -> str | None:
    """Extract a ``keyword { ... }`` block from raw vertex file text.

    Uses brace-matching so nested ``{ }`` are handled.
    Returns the raw text including the keyword, or ``None``.
    """
    marker = f"\n{keyword} " + "{"
    idx = content.find(marker)
    if idx == -1:
        if content.startswith(f"{keyword} " + "{"):
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


def _extract_loops_text(content: str) -> str | None:
    """Extract the ``loops { ... }`` block from raw vertex file text."""
    return _extract_block_text(content, "loops")


def _find_source_vertex(name: str) -> str | None:
    """Find an existing vertex to use as source for init.

    Priority:
    1. If the config vertex declares a loops block, build a synthetic
       instance from it (name + store + loops).
    2. Direct config-level instance (has a store directive).
    """
    import re as _re

    home = loops_home()
    config_dir = home / name
    if not config_dir.exists():
        return None
    leaf = Path(name).name
    vertex_file = config_dir / f"{leaf}.vertex"
    if not vertex_file.exists():
        return None
    content = vertex_file.read_text()
    # Try loops block → synthetic instance (preserving lens block if present)
    loops_text = _extract_loops_text(content)
    if loops_text is not None:
        lens_text = _extract_block_text(content, "lens")
        parts = [f'name "{leaf}"', f'store "./data/{leaf}.db"', "", loops_text]
        if lens_text is not None:
            parts.append("")
            parts.append(lens_text)
        return "\n".join(parts) + "\n"
    # Direct instance (has a store directive, not just the word in a comment)
    if _re.search(r'^store\s', content, _re.MULTILINE):
        return content
    return None


def _init_local_vertex(
    name: str,
    source_name: str | None = None,
    *,
    iterations: int | None = None,
) -> Path:
    """Create a vertex + data dir in .loops/. Returns vertex path.

    Uses an existing config-level vertex as source if available,
    otherwise creates a minimal stub with store path and empty loops block.
    Copies vertex-local lenses from source so they travel with the instance.
    Registers with the config-level aggregator if one exists.

    If iterations is provided, substitutes boundary count and condition limits
    in the stamped vertex content (e.g. count=30 → count=50).
    """
    import re
    import shutil

    # Resolve store path as absolute — survives worktree access.
    # Project-local stores are durable data; the path is a connection string,
    # not a relative reference that assumes cwd.
    loops_dir = Path.cwd() / ".loops"
    abs_store = str((loops_dir / "data" / f"{name}.db").resolve())

    source = _find_source_vertex(source_name or name)
    if source is None:
        # Minimal stub — store + empty loops block for user to fill in
        content = _MINIMAL_INSTANCE.format(name=name, store=abs_store)
    else:
        # Stamp from existing vertex, updating name and store path
        content = re.sub(
            r'^name ".*"', f'name "{name}"', source, count=1, flags=re.MULTILINE
        )
        content = re.sub(
            r'^store ".*\.db"',
            f'store "{abs_store}"',
            content,
            count=1,
            flags=re.MULTILINE,
        )
        # Substitute vertex name references in run clauses with the absolute
        # vertex file path. The run clause executes from arbitrary cwd (worktrees),
        # so name-based resolution may fail. Absolute path always works.
        source_key = source_name or name
        abs_vertex = str((loops_dir / f"{name}.vertex").resolve())
        content = content.replace(
            f"loops read {source_key} ",
            f"loops read {abs_vertex} ",
        )
        content = content.replace(
            f"loops emit {source_key} ",
            f"loops emit {abs_vertex} ",
        )
        # TODO: This init-time substitution is too specific — it pattern-matches
        # autoresearch's boundary shape rather than being a general mechanism.
        # Remove when cross-loop condition references land (thread:
        # cross-loop-condition-ref), which lets boundaries read limits from
        # config fold state at runtime instead of baking literals at init.
        if iterations is not None:
            content = re.sub(
                r'boundary after=\d+',
                f'boundary after={iterations}',
                content,
            )
            content = re.sub(
                r'condition "n" "<" \d+',
                f'condition "n" "<" {iterations}',
                content,
            )
    loops_dir = Path.cwd() / ".loops"
    loops_dir.mkdir(exist_ok=True)
    vertex_path = loops_dir / f"{name}.vertex"
    vertex_path.parent.mkdir(parents=True, exist_ok=True)
    if not vertex_path.exists():
        vertex_path.write_text(content)
    data_dir = loops_dir / "data"
    data_dir.mkdir(exist_ok=True)
    # For slashed names like autoresearch/emit-latency, ensure data subdir exists
    store_dir = (loops_dir / "data" / name).parent
    store_dir.mkdir(parents=True, exist_ok=True)

    # Copy vertex-local lenses from source vertex directory
    source_key = source_name or name
    home = loops_home()
    source_lens_dir = home / source_key / "lenses"
    if source_lens_dir.is_dir():
        local_lens_dir = loops_dir / "lenses"
        local_lens_dir.mkdir(exist_ok=True)
        for lens_file in source_lens_dir.glob("*.py"):
            dest = local_lens_dir / lens_file.name
            if not dest.exists():
                shutil.copy2(lens_file, dest)

    # Register with config-level aggregator
    _register_with_aggregator(source_key, vertex_path)

    return vertex_path


def _register_with_aggregator(name: str, local_vertex: Path) -> None:
    """Add local instance to the config-level vertex's combine block.

    If the config-level vertex has a combine block, add a vertex line
    pointing to the new local instance. Idempotent — skips if already
    registered or if no combine block exists.
    """
    home = loops_home()
    leaf = Path(name).name
    config_vertex = home / name / f"{leaf}.vertex"
    if not config_vertex.exists():
        return

    content = config_vertex.read_text()
    abs_path = str(local_vertex.resolve())

    # Already registered?
    if abs_path in content:
        return

    # Find the combine block and add the vertex line
    combine_idx = content.find("\ncombine {")
    if combine_idx == -1:
        if content.startswith("combine {"):
            combine_idx = -1  # will add 1 to get 0
        else:
            # No combine block — this vertex doesn't aggregate.
            # Nothing to register with.
            return

    # Find the closing brace of the combine block
    start = combine_idx + 1 if combine_idx >= 0 else 0
    brace_start = content.index("{", start)
    depth = 0
    close_idx = brace_start
    for i in range(brace_start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                close_idx = i
                break

    # Insert new vertex line before the closing brace
    indent = "    "
    new_line = f'{indent}vertex "{abs_path}"\n'
    updated = content[:close_idx] + new_line + content[close_idx:]
    config_vertex.write_text(updated)



def _seed_config_facts(vertex_path: Path, config: dict[str, str]) -> None:
    """Emit config facts into a newly-created vertex store.

    Each key=value pair becomes a fact with kind="config" and
    payload={"key": k, "value": v}. Short init args are mapped
    to canonical config keys (e.g. metric → primary_metric).
    """
    from atoms import Fact
    from engine import load_vertex_program

    key_aliases = {"metric": "primary_metric"}

    program = load_vertex_program(vertex_path, validate_ast=False, skip_sources=True)
    v = program.vertex
    ts = datetime.now(timezone.utc).timestamp()

    for key, value in config.items():
        key = key_aliases.get(key, key)
        fact = Fact(
            kind="config",
            ts=ts,
            payload={"key": key, "value": value},
            observer="init",
            origin="",
        )
        v.receive(fact)
        ts += 0.001

    if hasattr(v, '_store') and v._store is not None:
        v._store.close()

    _msg(f"Seeded {len(config)} config facts")


def _scaffold_artifacts(config: dict[str, str], *, vertex_name: str = "") -> None:
    """Scaffold executable artifacts based on config values.

    If 'benchmark' is provided, creates autoresearch.sh.
    If 'checks' is provided, creates autoresearch.checks.sh.
    If vertex_name is provided, creates autoresearch.start.sh (launch script).
    Idempotent — won't overwrite existing scripts.
    """
    cwd = Path.cwd()

    benchmark = config.get("benchmark")
    if benchmark:
        script = cwd / "autoresearch.sh"
        if not script.exists():
            script.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                f"{benchmark}\n"
            )
            script.chmod(0o755)
            _msg(f"Created {script}")

    checks = config.get("checks")
    if checks:
        script = cwd / "autoresearch.checks.sh"
        if not script.exists():
            script.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                f"{checks}\n"
            )
            script.chmod(0o755)
            _msg(f"Created {script}")

    if not vertex_name:
        return

    vertex_path = f".loops/{vertex_name}.vertex"
    primary_metric = config.get("primary_metric", "metric")
    benchmark_cmd = config.get("benchmark", "./autoresearch.sh")

    # Iterate script — the boundary run clause target. One bounded agent turn.
    # Copy from config-level template and stamp placeholders.
    script = cwd / "iterate.sh"
    if not script.exists():
        template_dir = loops_home() / vertex_name.split("/")[0]
        template = template_dir / "iterate.sh"
        system_prompt = template_dir / "system-prompt.md"

        if template.exists():
            content = template.read_text()
            content = content.replace("__VERTEX__", vertex_path)
            content = content.replace("__BENCHMARK__", benchmark_cmd)
            content = content.replace("__METRIC__", primary_metric)
            content = content.replace("__SYSTEM_PROMPT__", str(system_prompt))
            script.write_text(content)
        else:
            # Fallback: minimal inline script
            script.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "\n"
                f'VERTEX="{vertex_path}"\n'
                f'BENCHMARK="{benchmark_cmd}"\n'
                f'METRIC="{primary_metric}"\n'
                "\n"
                "BEFORE=$(git rev-parse HEAD)\n"
                "\n"
                "claude --dangerously-skip-permissions -p \\\n"
                '  "$(uv run loops read $VERTEX --lens autoresearch_prompt --plain)"\n'
                "\n"
                "AFTER=$(git rev-parse HEAD)\n"
                "\n"
                'if [ "$BEFORE" != "$AFTER" ]; then\n'
                '  RESULT=$($BENCHMARK 2>&1) || true\n'
                '  VALUE=$(echo "$RESULT" | grep "^${METRIC}=" | head -1 | cut -d= -f2)\n'
                '  DESC=$(git log -1 --format=%s)\n'
                '  if [ -n "$VALUE" ]; then\n'
                '    uv run loops emit "$VERTEX" experiment \\\n'
                '      commit="$(git rev-parse --short HEAD)" status=keep \\\n'
                '      "${METRIC}=${VALUE}" description="$DESC"\n'
                "  else\n"
                '    uv run loops emit "$VERTEX" experiment \\\n'
                '      commit="$(git rev-parse --short HEAD)" status=keep \\\n'
                '      description="$DESC (no ${METRIC} in output)"\n'
                "  fi\n"
                "else\n"
                '  uv run loops emit "$VERTEX" experiment \\\n'
                '    commit="$(git rev-parse --short HEAD)" status=discard \\\n'
                '    description="No changes committed"\n'
                "fi\n"
            )
        script.chmod(0o755)
        _msg(f"Created {script}")


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a loops vertex.

    No args: create root .vertex in LOOPS_HOME.
    Name or --template: create local instance in .loops/ from config source or minimal stub.
    With key=value seed args: emit config facts and scaffold executable artifacts.
    """
    name = getattr(args, "name", None)
    template = getattr(args, "template", None)
    seed_parts = getattr(args, "seed", None) or []

    # No name + no template → root .vertex in LOOPS_HOME
    if not name and not template:
        home = loops_home()
        root = home / ".vertex"
        if root.exists():
            from painted import show, Block
            from painted.palette import current_palette

            show(
                Block.text(f"Already initialized: {root}", current_palette().muted),
                file=sys.stdout,
            )
            return 0
        home.mkdir(parents=True, exist_ok=True)
        root.write_text(_ROOT_VERTEX)
        _msg(f"Created {root}")
        return 0

    # Name and/or template → local instance in .loops/
    target = name or template

    # Parse seed key=value pairs (before init so iterations= can be extracted)
    seed_config = _parse_emit_parts(seed_parts) if seed_parts else {}

    # Extract iterations — vertex-level parameter, not a config fact.
    # TODO: Remove when cross-loop-condition-ref lands (see above).
    iterations = None
    if "iterations" in seed_config:
        try:
            iterations = int(seed_config.pop("iterations"))
        except ValueError:
            pass

    vertex_path = _init_local_vertex(target, source_name=template, iterations=iterations)
    _msg(f"Created {vertex_path}")

    if seed_config:
        _seed_config_facts(vertex_path, seed_config)
        _scaffold_artifacts(seed_config, vertex_name=target)

    return 0


def _resolve_vertex_path(file_arg: str | None) -> Path | None:
    """Resolve a vertex file path, defaulting to LOOPS_HOME/.vertex."""
    if file_arg is not None:
        return Path(file_arg)
    home = loops_home()
    root = home / ".vertex"
    if root.exists():
        return root
    _err(f"Error: {root} not found. Run 'loops init' first.")
    return None


def _run_validate(argv: list[str]) -> int:
    """Run validate command via painted CLI harness."""
    from painted import run_cli
    from painted.cli import HelpArg
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
        from .lenses.test import test_view

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
        from .lenses.run import run_facts_view

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



def _resolve_combine_vertex_paths(vertex_path: Path) -> list[Path]:
    """Resolve an aggregation vertex's combine entries to child vertex paths.

    Mirrors engine.vertex_reader._resolve_combine_stores but returns vertex
    paths instead of store paths — we need VertexPrograms, not databases.
    """
    from lang import parse_vertex_file, resolve_vertex

    ast = parse_vertex_file(vertex_path)
    if not ast.combine:
        return []

    home = loops_home()
    child_paths: list[Path] = []
    for entry in ast.combine:
        vpath = resolve_vertex(entry.name, home)
        if not vpath.is_absolute():
            vpath = (vertex_path.parent / vpath).resolve()
        if vpath.exists():
            child_paths.append(vpath)
    return child_paths


def _execute_boundary_run(command: str, tick_name: str, vertex_path: Path) -> None:
    """Execute a boundary run clause — fire and forget.

    Engine produces ticks with run metadata. This function executes
    the command as a subprocess, inheriting the vertex directory as cwd.
    The command runs asynchronously — sync continues without waiting.

    Errors are logged to stderr but don't fail the sync.
    """
    import subprocess

    cwd = vertex_path.parent
    _err(f"  boundary {tick_name} → run: {command}")
    try:
        subprocess.Popen(
            command,
            shell=True,
            cwd=str(cwd),
            start_new_session=True,  # detach from parent process group
        )
    except OSError as e:
        _err(f"  [ERROR] boundary run failed: {e}")


def _run_sync_aggregate(
    child_paths: list[Path],
    *,
    vars: dict[str, str] | None,
    force: bool,
    parent_name: str,
    rest: list[str],
) -> int:
    """Sync each combine child independently and aggregate results."""
    from painted import run_cli, show, Block
    from painted.cli import HelpArg
    from painted.palette import current_palette
    from engine import load_vertex_program

    label = "force" if force else "cadence-gated"
    show(
        Block.text(
            f"Syncing {parent_name}: {len(child_paths)} children ({label})",
            current_palette().muted,
        ),
        file=sys.stderr,
    )

    def log_error(fact):
        payload = dict(fact.payload) if hasattr(fact.payload, "items") else fact.payload
        _err(f"[ERROR] {fact.observer}: {payload}")

    def fetch():
        all_ran: list[str] = []
        all_skipped: list[dict] = []
        all_errors: list[dict] = []
        all_ticks: list[dict] = []
        all_fact_counts: dict[str, int] = {}
        children: list[dict] = []

        for child_path in child_paths:
            child_program = load_vertex_program(child_path, vars=vars)
            if not child_program.sources:
                continue
            result = child_program.sync(on_error=log_error, force=force)

            # Execute boundary run clauses — fire and forget
            for tick in result.ticks:
                if tick.run:
                    _execute_boundary_run(tick.run, tick.name, child_path)

            all_ran.extend(result.ran)
            all_skipped.extend(
                {"kind": s.kind, "last_run_ts": s.last_run_ts, "cadence_interval": s.cadence_interval}
                for s in result.skipped
            )
            for kind, count in result.fact_counts.items():
                all_fact_counts[kind] = all_fact_counts.get(kind, 0) + count
            all_errors.extend(
                {
                    "kind": e.kind,
                    "observer": e.observer,
                    "payload": dict(e.payload) if hasattr(e.payload, "items") else e.payload,
                }
                for e in result.errors
            )
            all_ticks.extend(
                {
                    "name": tick.name,
                    "ts": tick.ts,
                    "payload": tick.payload,
                    "origin": getattr(tick, "origin", ""),
                    **({"run": tick.run} if tick.run else {}),
                }
                for tick in result.ticks
            )
            children.append({
                "name": child_program.vertex.name,
                "ran": result.ran,
                "skipped": [
                    {"kind": s.kind, "last_run_ts": s.last_run_ts, "cadence_interval": s.cadence_interval}
                    for s in result.skipped
                ],
                "fact_counts": result.fact_counts,
            })

        return {
            "ran": all_ran,
            "skipped": all_skipped,
            "fact_counts": all_fact_counts,
            "errors": all_errors,
            "ticks": all_ticks,
            "children": children,
        }

    def render(ctx, data):
        from .lenses.sync import sync_view
        return sync_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops sync",
        description=f"Sync vertex {parent_name} (aggregation)",
        help_args=[
            HelpArg("vertex", "Vertex name", positional=True),
            HelpArg("--force", "Run all sources unconditionally"),
            HelpArg("--var", "Set variable KEY=VALUE"),
        ],
    )


def _run_sync(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Sync verb — cadence-gated source execution.

    ``loops sync [vertex] [--force] [--var KEY=VALUE]``

    Default: evaluate cadence predicates, run stale sources.
    --force: run all sources unconditionally.
    """
    from painted import run_cli, show, Block
    from painted.cli import HelpArg
    from painted.palette import current_palette
    from engine import load_vertex_program

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex", nargs="?", default=None)
    pre.add_argument("--force", "-f", action="store_true", default=False)
    pre.add_argument("--var", action="append", default=[])
    known, rest = pre.parse_known_args(argv)

    # Resolve vertex path — accepts name or file path
    if vertex_path is None:
        vname = getattr(known, "vertex", None)
        if vname is not None:
            # File path: direct .vertex file
            vpath = Path(vname)
            if vname.endswith(".vertex") or vpath.suffix == ".vertex":
                vertex_path = vpath.resolve()
            else:
                try:
                    vertex_path = _resolve_named_vertex(vname)
                except FileNotFoundError as e:
                    _err(str(e))
                    return 1
        else:
            vertex_path = _resolve_vertex_path(None)
            if vertex_path is None:
                return 1

    if not vertex_path.exists():
        _err(f"Error: {vertex_path} does not exist")
        return 1

    try:
        vars = _parse_vars(known.var)
    except ValueError as e:
        _err(str(e))
        return 1

    program = load_vertex_program(vertex_path, vars=vars or None)

    # Aggregation vertex: no own sources but has combine children — sync each child
    if not program.sources:
        child_paths = _resolve_combine_vertex_paths(vertex_path)
        if child_paths:
            return _run_sync_aggregate(
                child_paths, vars=vars or None, force=known.force,
                parent_name=program.vertex.name, rest=rest,
            )
        # Sourceless vertex with a store: still sync to evaluate boundaries.
        # Vertices like orchestration have no sources but boundaries with
        # run clauses that fire on externally-emitted facts.
        if program.vertex._store is None:
            _err("No sources configured")
            return 1

    force = known.force

    def log_error(fact):
        payload = dict(fact.payload) if hasattr(fact.payload, "items") else fact.payload
        _err(f"[ERROR] {fact.observer}: {payload}")

    label = "force" if force else "cadence-gated"
    show(
        Block.text(
            f"Syncing {program.vertex.name}: {len(program.sources)} sources ({label})",
            current_palette().muted,
        ),
        file=sys.stderr,
    )

    def fetch():
        result = program.sync(on_error=log_error, force=force)

        # Execute boundary run clauses — fire and forget.
        # Engine produces ticks with run metadata; app layer executes.
        for tick in result.ticks:
            if tick.run:
                _execute_boundary_run(tick.run, tick.name, vertex_path)

        return {
            "ran": result.ran,
            "skipped": [
                {"kind": s.kind, "last_run_ts": s.last_run_ts, "cadence_interval": s.cadence_interval}
                for s in result.skipped
            ],
            "fact_counts": result.fact_counts,
            "errors": [
                {
                    "kind": e.kind,
                    "observer": e.observer,
                    "payload": dict(e.payload) if hasattr(e.payload, "items") else e.payload,
                }
                for e in result.errors
            ],
            "ticks": [
                {
                    "name": tick.name,
                    "ts": tick.ts,
                    "payload": tick.payload,
                    "origin": getattr(tick, "origin", ""),
                    **({"run": tick.run} if tick.run else {}),
                }
                for tick in result.ticks
            ],
        }

    def render(ctx, data):
        from .lenses.sync import sync_view

        return sync_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops sync",
        description=f"Sync vertex {program.vertex.name}",
        help_args=[
            HelpArg("vertex", "Vertex name", positional=True),
            HelpArg("--force", "Run all sources unconditionally"),
            HelpArg("--var", "Set variable KEY=VALUE"),
        ],
    )


def _run_compile(argv: list[str]) -> int:
    """Run compile command via painted CLI harness."""
    from painted import run_cli
    from painted.cli import HelpArg
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


def _warn_missing_fold_key(
    vertex_path: Path,
    kind: str,
    payload: dict,
) -> None:
    """Warn on stderr if the payload lacks the fold key field.

    When a kind folds 'by' a key field (e.g. thread folds by 'name'),
    a fact without that field will be stored but silently skipped by the
    fold — orphaned data that never appears in the folded state.
    """
    from lang import parse_vertex_file
    from lang.ast import FoldBy

    # Follow combine chain to the vertex with actual loop declarations
    writable = _resolve_writable_vertex(vertex_path)
    if writable is not None:
        vertex_path = writable

    try:
        ast = parse_vertex_file(vertex_path)
    except Exception:
        return

    loop_def = ast.loops.get(kind)
    if loop_def is None:
        return

    for fold_decl in loop_def.folds:
        if isinstance(fold_decl.op, FoldBy) and fold_decl.op.key_field not in payload:
            key = fold_decl.op.key_field
            _err(
                f"Warning: kind '{kind}' folds by '{key}' but payload has no "
                f"'{key}=' field — fact will be stored but not foldable"
            )
            return


def _extract_kind_keys(vertex_path: Path) -> dict[str, str]:
    """Extract kind → fold key_field map from a vertex's AST.

    Returns {kind_name: key_field} for each kind that folds "by" a key field.
    Skips kinds that use collect or other non-keyed folds.
    """
    from lang import parse_vertex_file
    from lang.ast import FoldBy

    try:
        ast = parse_vertex_file(vertex_path)
    except Exception:
        return {}

    kind_keys: dict[str, str] = {}
    for kind_name, loop_def in ast.loops.items():
        for fold_decl in loop_def.folds:
            if isinstance(fold_decl.op, FoldBy):
                kind_keys[kind_name] = fold_decl.op.key_field
                break
    return kind_keys


def _try_topology_from_store(
    store_path: Path,
) -> tuple[dict[str, str], list[Path]] | None:
    """Try reading _topology fold from a store. Returns None on miss.

    Validates that all cached store paths exist on disk. If any are
    stale (deleted vertex), returns None to trigger fallback+refresh.
    """
    from engine import StoreReader

    try:
        with StoreReader(store_path) as reader:
            facts = reader.facts_by_kind("_topology")
    except Exception:
        return None

    if not facts:
        return None

    # Replay upsert fold manually: latest per name wins
    topology: dict[str, dict] = {}
    for fact in facts:
        payload = fact["payload"]
        name = payload.get("name")
        if name:
            topology[name] = payload

    # Validate store paths exist and collect results
    merged_kind_keys: dict[str, str] = {}
    store_paths: list[Path] = []

    for entry in topology.values():
        store_str = entry.get("store", "")
        if store_str:
            sp = Path(store_str)
            if sp.exists():
                store_paths.append(sp)
            else:
                return None  # Stale — trigger fallback

        kind_keys = entry.get("kind_keys", {})
        merged_kind_keys.update(kind_keys)

    return merged_kind_keys, store_paths


def _topology_kind_keys_and_stores(
    root_vertex_path: Path,
) -> tuple[dict[str, str], list[Path]]:
    """Collect kind_keys and store paths from a root vertex's topology.

    Cache-first: tries reading _topology fold from the root's own store.
    On miss (no store, no _topology facts, or stale store paths), falls
    back to filesystem walk and refreshes the cache.
    """
    from lang import parse_vertex_file

    try:
        ast = parse_vertex_file(root_vertex_path)
    except Exception:
        return {}, []

    # Fast path: try _topology facts from root's own store
    if ast.store is not None:
        own_store = ast.store
        if not own_store.is_absolute():
            own_store = (root_vertex_path.parent / own_store).resolve()
        if own_store.exists():
            result = _try_topology_from_store(own_store)
            if result is not None:
                return result

    # Slow path: filesystem walk
    from engine.vertex_reader import _resolve_stores

    store_paths = _resolve_stores(ast, root_vertex_path)

    merged_kind_keys: dict[str, str] = {}
    base_dir = root_vertex_path.parent

    if ast.discover is not None:
        for match in sorted(base_dir.glob(ast.discover)):
            if match.suffix != ".vertex" or match.resolve() == root_vertex_path.resolve():
                continue
            merged_kind_keys.update(_extract_kind_keys(match))
    elif ast.combine is not None:
        from lang.population import resolve_vertex

        home = loops_home()
        for entry in ast.combine:
            vpath = resolve_vertex(entry.name, home)
            if not vpath.is_absolute():
                vpath = (base_dir / vpath).resolve()
            if vpath.exists():
                merged_kind_keys.update(_extract_kind_keys(vpath))

    # Refresh cache for next time
    from engine.vertex_reader import emit_topology

    try:
        emit_topology(root_vertex_path)
    except Exception:
        pass  # Cache refresh is best-effort

    return merged_kind_keys, store_paths


def _resolve_entity_refs(
    vertex_path: Path,
    store_path: Path,
    payload: dict[str, str],
) -> dict[str, str]:
    """Resolve entity addresses in payload values to ULIDs.

    Scans payload values for entity addresses (kind/fold_key_value format).
    When a value matches a declared kind, looks up the most recent fact ULID
    for that entity — first in the local store, then across the full topology
    if the local store misses.

    The original field is preserved (navigable address). A sibling field
    {name}_ref is added with the pinned ULID (provenance anchor).

    Returns the payload with any resolved references added.
    """
    from engine import StoreReader

    # Build kind → key_field map from local vertex declaration
    writable = _resolve_writable_vertex(vertex_path)
    if writable is not None:
        vertex_path = writable

    local_kind_keys = _extract_kind_keys(vertex_path)

    # Lazy topology widening — only computed on first local miss
    _topo: dict | None = None

    def _ensure_topology() -> tuple[dict[str, str], list[Path]]:
        nonlocal _topo
        if _topo is not None:
            return _topo["kind_keys"], _topo["stores"]
        root = _find_local_vertex()
        if root is None or root.resolve() == vertex_path.resolve():
            _topo = {"kind_keys": {}, "stores": []}
            return _topo["kind_keys"], _topo["stores"]
        topo_kind_keys, topo_stores = _topology_kind_keys_and_stores(root)
        _topo = {"kind_keys": topo_kind_keys, "stores": topo_stores}
        return topo_kind_keys, topo_stores

    def _try_resolve(sp: Path, kind: str, key_field: str, value: str) -> str | None:
        try:
            reader = StoreReader(sp)
            try:
                return reader.resolve_entity_id(kind, key_field, value)
            finally:
                reader.close()
        except (FileNotFoundError, Exception):
            return None

    # Scan payload values for entity address pattern: kind/fold_key_value
    refs: dict[str, str] = {}
    for field_name, value in payload.items():
        if not isinstance(value, str) or "/" not in value:
            continue
        # Split on first / only: decision/design/format-dissolves → ("decision", "design/format-dissolves")
        addr_kind, addr_value = value.split("/", 1)

        # Try local store first
        if addr_kind in local_kind_keys:
            key_field = local_kind_keys[addr_kind]
            ulid = _try_resolve(store_path, addr_kind, key_field, addr_value)
            if ulid is not None:
                refs[f"{field_name}_ref"] = ulid
                continue

        # Local miss or kind not declared locally — widen to topology
        topo_kind_keys, topo_stores = _ensure_topology()
        if addr_kind not in local_kind_keys and addr_kind not in topo_kind_keys:
            continue  # Not a known kind anywhere in the topology

        key_field = topo_kind_keys.get(addr_kind) or local_kind_keys.get(addr_kind)
        if key_field is None:
            continue

        for sp in topo_stores:
            if sp.resolve() == store_path.resolve():
                continue  # Already searched
            ulid = _try_resolve(sp, addr_kind, key_field, addr_value)
            if ulid is not None:
                refs[f"{field_name}_ref"] = ulid
                break

    if refs:
        payload = {**payload, **refs}

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


def _resolve_combine_child(parent_vertex: Path, alias: str) -> Path | None:
    """Resolve a combine child by alias.

    Given a combine vertex and an alias string, find the child entry
    with a matching alias and return its resolved vertex path.
    Returns None if the parent isn't a combine vertex or no alias matches.
    """
    from lang import parse_vertex_file
    from lang.population import resolve_vertex

    try:
        ast = parse_vertex_file(parent_vertex)
    except Exception:
        return None

    if ast.combine is None:
        return None

    for entry in ast.combine:
        if entry.alias == alias:
            ref = resolve_vertex(entry.name, loops_home())
            if not ref.is_absolute():
                ref = (parent_vertex.parent / ref).resolve()
            if ref.exists():
                return ref.resolve()
    return None


def _resolve_vertex_for_dispatch(name: str) -> Path | None:
    """Try to resolve a name as a vertex for CLI dispatch. Returns None to fall through.

    Resolution chain (local instance wins over config template):
    1. Path-like strings (.vertex suffix, ./ or / prefix) — resolve directly if file exists
    2. Local: .loops/name.vertex
    3. Local: cwd/name.vertex
    4. Config-level: LOOPS_HOME/name/name.vertex
    5. Combine alias: parent/alias → parent's combine child with that alias
    """
    if name.endswith(".vertex") or name.startswith("./") or name.startswith("/"):
        p = Path(name)
        if p.exists():
            return p.resolve()
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

    # Combine alias: project/loops → resolve "project" then find child "loops"
    # Combine vertices live at config level, so we try both local and
    # config-level resolution for the parent.
    if "/" in name:
        parent_name, child_alias = name.split("/", 1)

        # Try local resolution first (might be a local combine vertex)
        parent = _resolve_vertex_for_dispatch(parent_name)
        if parent is not None:
            child = _resolve_combine_child(parent, child_alias)
            if child is not None:
                return child

        # Try config-level explicitly (combine vertices typically live here)
        config_parent = resolve_vertex(parent_name, loops_home())
        if config_parent.exists() and (parent is None or config_parent.resolve() != parent):
            child = _resolve_combine_child(config_parent.resolve(), child_alias)
            if child is not None:
                return child

    return None


def cmd_emit(args: argparse.Namespace, *, vertex_path: Path | None = None) -> int:
    """Inject a fact directly into a vertex store (or print in --dry-run)."""
    from atoms import Fact
    from loops.commands.identity import resolve_observer, validate_emit
    from loops.pop_store import POP_ADD_KIND, POP_RM_KIND
    # painted deferred — only imported when display is needed (error/tick paths).
    # _lp caches the lazy-loaded (show, Block, palette) tuple.
    _lp: list = []

    def _show(*args, **kwargs):
        if not _lp:
            from painted import show as _s, Block as _B
            from painted.palette import current_palette
            _lp.extend([_s, _B, current_palette()])
        return _lp[0](*args, **kwargs)

    class _BlockProxy:
        """Proxy that loads painted.Block on first attribute access."""
        def __getattr__(self, name):
            if not _lp:
                from painted import show as _s, Block as _B
                from painted.palette import current_palette
                _lp.extend([_s, _B, current_palette()])
            return getattr(_lp[1], name)

    class _PaletteProxy:
        """Proxy that loads painted palette on first attribute access."""
        def __getattr__(self, name):
            if not _lp:
                from painted import show as _s, Block as _B
                from painted.palette import current_palette
                _lp.extend([_s, _B, current_palette()])
            return getattr(_lp[2], name)

    show = _show
    Block = _BlockProxy()
    p = _PaletteProxy()

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
            # Local-first resolution (matches vertex-first dispatch behavior)
            local_candidate = _resolve_vertex_for_dispatch(vertex_ref)
            if local_candidate is not None:
                vertex_path = local_candidate
            else:
                # Try config-level resolution (handles slashed names like comms/native)
                from lang.population import resolve_vertex
                candidate = resolve_vertex(vertex_ref, loops_home()).resolve()

                if not candidate.exists() and "/" in vertex_ref and not _is_path_like(vertex_ref):
                    # Full name didn't resolve — try splitting as vertex/template
                    vertex_ref, template_qualifier = vertex_ref.split("/", 1)
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

        # Warn if payload is missing the fold key field (data quality)
        _warn_missing_fold_key(vertex_path, kind, payload)

    # Resolve store path early — needed for entity reference resolution
    try:
        writable_path = _resolve_writable_vertex(vertex_path)
        if writable_path is None:
            if not args.dry_run:
                show(
                    Block.text("Error: vertex has no store configured", p.error),
                    file=sys.stderr,
                )
                return 1
            store_path = None
        else:
            store_path = _resolve_vertex_store_path(writable_path)
            if store_path is None and not args.dry_run:
                show(
                    Block.text("Error: vertex has no store configured", p.error),
                    file=sys.stderr,
                )
                return 1
    except Exception as e:
        if not args.dry_run:
            show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
            return 1
        store_path = None

    # Resolve entity references in payload values (kind/fold_key_value → ULID)
    # store_path may not exist yet (first emit to this vertex) — cross-vertex
    # resolution can still succeed via topology widening.
    if vertex_path is not None and store_path is not None:
        payload = _resolve_entity_refs(vertex_path, store_path, payload)

    ts = datetime.now(timezone.utc).timestamp()
    fact = Fact(
        kind=kind,
        ts=ts,
        payload=payload,
        observer=observer,
        origin="",
    )

    if args.dry_run:
        import json
        show(
            Block.text(
                json.dumps(fact.to_dict(), sort_keys=True, default=str), p.muted
            ),
            file=sys.stdout,
        )
        return 0

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
            from lang import parse_vertex_file
            from lang.population import resolve_template, list_file_header, list_file_read
            from loops.pop_store import pop_materialize_list, pop_store_has_facts
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
                # Execute boundary run clause if present — fire and forget
                if tick.run:
                    _execute_boundary_run(tick.run, tick.name, writable_path)
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
    view_name: str,
):
    """Resolve render function via 3-tier chain.

    Resolution order:
    1. --lens CLI flag (resolved via lens_resolver)
    2. Vertex lens{} declaration (resolved via lens_resolver)
    3. Built-in default
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
            if view_name == "fold_view" and vertex_lens.fold:
                fn = resolve_lens(vertex_lens.fold, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn
            elif view_name == "stream_view" and vertex_lens.stream:
                fn = resolve_lens(vertex_lens.stream, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn

    # Tier 3: built-in defaults
    if view_name == "fold_view":
        from .lenses.fold import fold_view
        return fold_view
    elif view_name == "stream_view":
        from .lenses.stream import stream_view
        return stream_view
    elif view_name == "ticks_view":
        from .lenses.ticks import ticks_view
        return ticks_view

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




def _vertex_name(vertex_path: Path | None) -> str | None:
    """Extract vertex name from path — stem without extension."""
    if vertex_path is None:
        return None
    name = vertex_path.stem
    # .vertex (bare dotfile) → infer from parent dir
    if name == "":
        return vertex_path.parent.name
    return name




def _run_stream(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
    """Run stream command — unified event history with optional search.

    Dissolves the old log + search into one temporal mode.
    When vertex_path is None (verb-first), the first positional is tried as
    a vertex name before falling back to search query.
    """
    from painted import run_cli
    from painted.cli import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex_or_query", nargs="?", default=None)
        pre.add_argument("query", nargs="?", default=None)
    else:
        pre.add_argument("query", nargs="?", default=None)
    pre.add_argument("--kind", default=None)
    pre.add_argument("--since", default=None)
    pre.add_argument("--lens", default=None)
    pre.add_argument("--id", default=None, dest="fact_id")
    known, rest = pre.parse_known_args(argv)

    # Render function resolved lazily — vertex_path may not be known until fetch()
    resolved_render_fn = None

    def fetch():
        nonlocal vertex_path, observer
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

        # Apply vertex scope — deferred until vertex_path is known
        observer = _apply_vertex_scope(observer, vertex_path)
        obs_for_engine = observer if observer else None

        # --id: single fact lookup by ID or prefix
        if known.fact_id is not None:
            from .commands.fetch import fetch_fact_by_id
            try:
                fact = fetch_fact_by_id(vertex_path, known.fact_id)
            except ValueError as e:
                _err(str(e))
                return {"facts": [], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}
            if fact is None:
                return {"facts": [], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}
            return {"facts": [fact], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}

        from .commands.fetch import fetch_stream
        return fetch_stream(
            vertex_path,
            query=query,
            kind=known.kind,
            since=known.since,
            observer=obs_for_engine,
        )

    def render(ctx, data):
        nonlocal resolved_render_fn
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, "stream_view",
            )
        w = ctx.width if ctx.is_tty else None
        from .lens_resolver import call_lens
        return call_lens(
            resolved_render_fn, data, ctx.zoom, w,
            vertex_name=_vertex_name(vertex_path),
        )

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops stream",
        description="Show event stream",
        help_args=[
            HelpArg("query", "Search text (FTS5)", positional=True),
            HelpArg("--id", "Look up fact by ID or prefix"),
            HelpArg("--kind", "Filter by fact kind"),
            HelpArg("--observer", "Filter by observer (default: you)"),
            HelpArg("--since", "Time window (7d, 24h, 1h)", default="7d"),
            HelpArg("--lens", "Render lens (prompt)"),
        ],
    )


def _run_fold(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
    """Run fold command — show collapsed vertex state."""
    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex", nargs="?", default=None)
    pre.add_argument("--kind", default=None)
    pre.add_argument("--lens", default=None)
    known, rest = pre.parse_known_args(argv)

    # Fast path: --static --plain bypasses the CLI framework import (~7ms).
    # Detect these flags before importing painted.cli.
    if _is_static_plain(rest):
        return _run_fold_fast(known, rest, vertex_path=vertex_path, observer=observer)

    from painted import run_cli
    from painted.cli import HelpArg

    # Render function resolved lazily — vertex_path may not be known until fetch()
    resolved_render_fn = None

    def fetch():
        nonlocal vertex_path, observer
        if vertex_path is None:
            from .commands.identity import resolve_local_vertex as _resolve_local_vertex
            vname = getattr(known, "vertex", None)
            if vname is not None:
                # Local-first: .loops/name.vertex → cwd → config-level
                local = _resolve_vertex_for_dispatch(vname)
                vertex_path = local if local is not None else _resolve_named_vertex(vname)
            else:
                vertex_path = _resolve_local_vertex()
        # Apply vertex scope — deferred until vertex_path is known
        observer = _apply_vertex_scope(observer, vertex_path)
        obs_for_engine = observer if observer else None
        from .commands.fetch import fetch_fold
        return fetch_fold(vertex_path, kind=known.kind, observer=obs_for_engine)

    def render(ctx, data):
        nonlocal resolved_render_fn
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, "fold_view",
            )
        # When piped (not TTY), pass width=None so text flows without
        # truncation or padding. The fold output IS the data — useful
        # directly as a system prompt or piped to other tools.
        w = ctx.width if ctx.is_tty else None
        from .lens_resolver import call_lens
        return call_lens(
            resolved_render_fn, data, ctx.zoom, w,
            vertex_name=_vertex_name(vertex_path),
            vertex_path=str(vertex_path) if vertex_path else None,
            visible=ctx.fidelity.visible,
        )

    def _add_fold_args(parser):
        """Add fold-specific flags: visibility layers."""
        parser.add_argument("--refs", action="store_true", default=False,
                            help="Show reference connections")

    def _build_fold_fidelity(parsed, base):
        """Inject visibility tags from fold-specific flags."""
        visible = set()
        if getattr(parsed, "refs", False):
            visible.add("refs")
        if not visible:
            return base
        return base.with_visible(*visible)

    async def fetch_stream():
        """Poll the store for updates — enables --live mode."""
        import asyncio
        yield fetch()
        while True:
            await asyncio.sleep(2)
            yield fetch()

    from painted.cli import OutputMode

    # Interactive handler for autoresearch TUI
    handlers: dict | None = None
    if known.lens == "autoresearch":
        def _handle_autoresearch_interactive(ctx):
            nonlocal vertex_path, observer
            if vertex_path is None:
                from .commands.identity import resolve_local_vertex as _rlv
                vname = getattr(known, "vertex", None)
                if vname is not None:
                    local = _resolve_vertex_for_dispatch(vname)
                    vertex_path = local if local is not None else _resolve_named_vertex(vname)
                else:
                    vertex_path = _rlv()
            observer = _apply_vertex_scope(observer, vertex_path)
            import asyncio as _asyncio
            from .tui.autoresearch_app import AutoresearchApp
            app = AutoresearchApp(vertex_path, observer=observer)
            _asyncio.run(app.run())
            return 0
        handlers = {OutputMode.INTERACTIVE: _handle_autoresearch_interactive}

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        fetch_stream=fetch_stream,
        default_mode=OutputMode.STATIC,
        handlers=handlers,
        add_args=_add_fold_args,
        build_fidelity=_build_fold_fidelity,
        prog="loops fold",
        description="Show folded state",
        help_args=[
            HelpArg("--kind", "Filter by fact kind"),
            HelpArg("--observer", "Filter by observer (default: you)"),
            HelpArg("--lens", "Render lens (prompt)"),
        ],
    )


def _is_static_plain(rest: list[str]) -> bool:
    """Check if rest args contain --static --plain without help flags."""
    has_static = "--static" in rest
    has_plain = "--plain" in rest
    has_help = "-h" in rest or "--help" in rest
    has_json = "--json" in rest
    has_live = "--live" in rest
    has_interactive = "-i" in rest
    return has_static and has_plain and not has_help and not has_json and not has_live and not has_interactive


def _render_fold_plain(data: Any, zoom_level: int, width: int) -> str:
    """Render fold state as plain text without importing painted (~15ms saved).

    Produces identical output to fold_view + print_block(use_ansi=False)
    for MINIMAL and SUMMARY zoom levels. Falls back to None for DETAILED/FULL
    which need the full lens for metadata rendering.

    This avoids the painted.core.block → _text_width → wcwidth import chain
    (~13ms) and the writer/icon_set imports (~2ms).
    """
    populated = [s for s in data.sections if s.items]
    if not populated:
        return "No data yet."

    # MINIMAL: one-liner counts
    if zoom_level == 0:
        parts = [f"{s.count} {s.kind}s" for s in populated]
        return ", ".join(parts)

    # SUMMARY: section headers + item lines
    lines: list[str] = []
    for s in populated:
        if lines:
            lines.append("")

        # Header
        label = s.kind.title()
        if not s.kind.endswith("s"):
            label += "s"
        lines.append(f"{label} ({s.count}):")

        # Items
        is_by = s.fold_type == "by"
        for item in s.items:
            payload = item.payload
            if is_by and s.key_field:
                item_label = str(payload.get(s.key_field, ""))
                used_label_field = s.key_field
            else:
                item_label = "?"
                used_label_field = None
                for k, v in payload.items():
                    if v:
                        item_label = str(v)
                        used_label_field = k
                        break

            # Body: first non-label payload field
            body = None
            skip = {used_label_field} if used_label_field else set()
            for k, v in payload.items():
                if k in skip or not v:
                    continue
                body = str(v)
                break

            if body:
                # Truncate body to fit within width (matches fold_view logic)
                reserved = len(item_label) + 6  # "  label: snippet"
                max_body = width - reserved
                if max_body < 10:
                    max_body = 10
                if len(body) > max_body:
                    body = body[: max_body - 1] + "\u2026"
                line = f"  {item_label}: {body}"
            else:
                line = f"  {item_label}"
            lines.append(line)

    return "\n".join(lines)


def _run_fold_fast(
    known, rest: list[str],
    *,
    vertex_path: Path | None = None,
    observer: str | None = None,
) -> int:
    """Fast path for --static --plain: skip CLI framework import.

    For MINIMAL/SUMMARY zoom with no custom lens, renders fold state
    directly as plain text — skipping the entire painted import chain
    (~15ms: Block→wcwidth, writer, icons). Falls back to painted for
    DETAILED/FULL zoom or custom lenses.
    """
    import shutil

    # Resolve zoom from rest args (lightweight, no painted import)
    zoom_level = 1  # SUMMARY default
    for arg in rest:
        if arg == "-q" or arg == "--quiet":
            zoom_level = 0
        elif arg == "-vv":
            zoom_level = 3
        elif arg == "-v" or arg == "--verbose":
            zoom_level = 2

    # Fetch data
    if vertex_path is None:
        from .commands.identity import resolve_local_vertex as _resolve_local_vertex
        vname = getattr(known, "vertex", None)
        if vname is not None:
            local = _resolve_vertex_for_dispatch(vname)
            vertex_path = local if local is not None else _resolve_named_vertex(vname)
        else:
            vertex_path = _resolve_local_vertex()

    observer = _apply_vertex_scope(observer, vertex_path)
    obs_for_engine = observer if observer else None

    from .commands.fetch import fetch_fold
    try:
        data = fetch_fold(vertex_path, kind=known.kind, observer=obs_for_engine)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Text-only rendering for MINIMAL/SUMMARY with default lens —
    # skips the entire painted import chain (~15ms).
    if known.lens is None and zoom_level <= 1:
        width = shutil.get_terminal_size().columns
        text = _render_fold_plain(data, zoom_level, width)
        print(text)
        return 0

    # DETAILED/FULL or custom lens: fall back to painted rendering
    if known.lens is not None:
        render_fn = _resolve_render_fn(known.lens, vertex_path, "fold_view")
    else:
        from .lenses.fold import fold_view
        render_fn = fold_view
    from painted.core.zoom import Zoom

    zoom = Zoom(zoom_level)
    width = shutil.get_terminal_size().columns

    from .lens_resolver import call_lens
    try:
        block = call_lens(
            render_fn, data, zoom, width,
            vertex_name=_vertex_name(vertex_path),
            vertex_path=str(vertex_path) if vertex_path else None,
        )
    except Exception as exc:
        print(f"Render error: {exc}", file=sys.stderr)
        return 2

    # Output — plain text, no ANSI
    from painted.core.writer import print_block
    from painted.icon_set import ASCII_ICONS, use_icons

    with use_icons(ASCII_ICONS):
        print_block(block, use_ansi=False)
    return 0


def _run_store(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Run store command via painted CLI harness."""
    from painted import run_cli, OutputMode
    from painted.cli import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
    known, rest = pre.parse_known_args(argv)
    file_arg = getattr(known, "file", None)

    def _resolve_store_target() -> Path:
        """Resolve file arg: vertex name, path, or LOOPS_HOME/.vertex fallback."""
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


def _run_ls(argv: list[str]) -> int:
    """Run ls command via painted CLI harness."""
    from painted import run_cli
    from painted.cli import HelpArg
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
    """Thin wrapper: parse argv for init, delegate to cmd_init.

    Accepts key=value pairs after the name for seeding config facts:
        loops init autoresearch objective="Reduce latency" metric=emit_ms
    """
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
    parser.add_argument(
        "seed",
        nargs="*",
        help="key=value pairs to emit as config facts after creation",
    )
    args = parser.parse_args(argv)
    return cmd_init(args)


def _run_emit(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
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


def _run_close(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
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


# Verb-first dispatch: `loops <verb> [vertex] [args]`.
# These are the primary CLI verbs — read (implicit default), emit, sync, close.
_VERBS = frozenset({"read", "emit", "close", "sync"})

# Dev and setup commands dispatched directly.
_DEV_COMMANDS = frozenset({"test", "compile", "validate", "store"})
_SETUP_COMMANDS = frozenset({"init", "whoami", "ls", "add", "rm", "export"})

# Combined for dispatch check (verbs checked first, then these).
_COMMANDS = _DEV_COMMANDS | _SETUP_COMMANDS

# Vertex-first operations: `loops <vertex> <op>`.
_VERTEX_OPS = frozenset({
    "read", "emit", "close", "sync", "store",
    "ls", "add", "rm", "export",
})


def _tick_drill_header(tick_meta: dict, width: int | None) -> "Block":
    """Render a compact header for tick drill-down.

    Shows tick index, boundary trigger, and time window. Returns a
    Block that can be composed above the fold/lens output.
    """
    from painted import Block, Style, join_vertical

    if not tick_meta:
        return Block.text("", Style())

    boundary = tick_meta.get("boundary", {})
    bname = boundary.get("name", "")
    bstatus = boundary.get("status", "")
    trigger = f" — {bname} {bstatus}" if bname else ""

    range_end = tick_meta.get("range_end")
    if range_end is not None:
        # Range mode: "Ticks #0:3 of 120"
        range_boundaries = tick_meta.get("range_boundaries", [])
        observers = list(dict.fromkeys(
            b.get("name", "") for b in range_boundaries if b.get("name")
        ))
        if observers:
            trigger = f" — {', '.join(observers)}"
        title = f"Ticks #{tick_meta['index']}:{range_end} of {tick_meta['total']}{trigger}"
    else:
        title = f"Tick #{tick_meta['index']} of {tick_meta['total']}{trigger}"

    rows: list[tuple[str, Style]] = [(title, Style(bold=True))]

    if tick_meta.get("since") and tick_meta.get("ts"):
        rows.append((f"  window: {tick_meta['since']} → {tick_meta['ts']}", Style(dim=True)))

    rows.append(("", Style()))
    return Block.column(rows, width=width)


def _run_ticks(
    argv: list[str],
    *,
    vertex_path: Path | None = None,
    observer: str | None = None,
) -> int:
    """Tick history and drill-down.

    ``loops read project --ticks``       — list recent ticks
    ``loops read project --ticks 0``     — drill into most recent tick
    ``loops read project --ticks 0:3``   — drill into last 3 ticks (range)
    ``loops read project --ticks 3``     — drill into 4th most recent tick
    """
    from painted import run_cli
    from painted.cli import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex_or_index", nargs="?", default=None)
        pre.add_argument("index", nargs="?", default=None)
    else:
        pre.add_argument("index", nargs="?", default=None)
    pre.add_argument("--since", default=None)
    pre.add_argument("--lens", default=None)
    known, rest = pre.parse_known_args(argv)

    # Parse index: int for single, "start:end" for range
    tick_index: int | None = None
    tick_range: tuple[int, int] | None = None

    def _try_index(s: str | None) -> bool:
        """Try parsing s as single index or range. Returns True if parsed."""
        nonlocal tick_index, tick_range
        if s is None:
            return False
        if ":" in s:
            parts = s.split(":", 1)
            try:
                tick_range = (int(parts[0]), int(parts[1]))
                return True
            except ValueError:
                return False
        try:
            tick_index = int(s)
            return True
        except ValueError:
            return False

    if vertex_path is None:
        first = getattr(known, "vertex_or_index", None)
        if first is not None:
            if not _try_index(first):
                # Not an index — try as vertex name
                resolved = _resolve_vertex_for_dispatch(first)
                if resolved is not None:
                    vertex_path = resolved
                    _try_index(known.index)
        if tick_index is None and tick_range is None:
            _try_index(known.index)
        if vertex_path is None:
            from .commands.identity import resolve_local_vertex as _rlv
            vertex_path = _rlv()
    else:
        _try_index(known.index)

    # Drill-down: show fold state snapshot from tick payload
    if tick_index is not None or tick_range is not None:
        resolved_render_fn = None

        def fetch():
            if tick_range is not None:
                from .commands.fetch import fetch_tick_range_fold
                return fetch_tick_range_fold(
                    vertex_path, tick_range[0], tick_range[1], since=known.since,
                )
            else:
                from .commands.fetch import fetch_tick_fold
                return fetch_tick_fold(vertex_path, tick_index, since=known.since)

        def render(ctx, data):
            nonlocal resolved_render_fn
            from painted import Block, Style, join_vertical

            w = ctx.width if ctx.is_tty else None

            # Error case
            if data.get("_tick_error"):
                return Block.text(data["_tick_error"], Style(dim=True))

            fold_state = data["fold_state"]
            tick_meta = data.get("_tick", {})

            # Resolve fold lens (not stream — tick payload is fold state)
            if resolved_render_fn is None:
                resolved_render_fn = _resolve_render_fn(
                    known.lens, vertex_path, "fold_view",
                )

            from .lens_resolver import call_lens
            body = call_lens(
                resolved_render_fn, fold_state, ctx.zoom, w,
                vertex_name=_vertex_name(vertex_path),
            )

            # Compose tick header + fold rendering
            header = _tick_drill_header(tick_meta, w)
            return join_vertical(header, body) if header else body

        return run_cli(
            rest,
            fetch=fetch,
            render=render,
            prog="loops ticks",
            description="Show fold state at tick boundary",
            help_args=[
                HelpArg("index", "Tick index or range (0, 0:3)", positional=True),
                HelpArg("--since", "Time window for tick search (30d)", default="30d"),
                HelpArg("--lens", "Render lens"),
            ],
        )

    # Listing mode: show tick history
    from .commands.fetch import fetch_ticks

    resolved_render_fn = None

    def fetch_listing():
        return fetch_ticks(vertex_path, since=known.since)

    def render_listing(ctx, data):
        nonlocal resolved_render_fn
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, "ticks_view",
            )
        w = ctx.width if ctx.is_tty else None
        from .lens_resolver import call_lens
        return call_lens(
            resolved_render_fn, data, ctx.zoom, w,
            vertex_name=_vertex_name(vertex_path),
        )

    return run_cli(
        rest,
        fetch=fetch_listing,
        render=render_listing,
        prog="loops ticks",
        description="Show tick history",
        help_args=[
            HelpArg("index", "Tick index to drill into (0 = most recent)", positional=True),
            HelpArg("--since", "Time window (30d, 7d, 1h)", default="30d"),
            HelpArg("--lens", "Render lens"),
        ],
    )


def _run_read(
    argv: list[str],
    *,
    vertex_path: Path | None = None,
    observer: str | None = None,
) -> int:
    """Unified read verb — routes to fold (default) or stream (--facts/--ticks).

    ``loops read [vertex] [flags]`` is the primary read interface.
    Default (no flags) shows fold state. ``--facts`` shows filtered fact
    history. ``--ticks`` shows tick history.

    This is a thin router — delegates to ``_run_fold`` or ``_run_stream``
    which handle their own argument parsing, fetch, and rendering.
    """
    # Pre-parse only the mode flags to decide which path to take.
    # Strip mode flags before delegating — delegates don't know about them.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--facts", action="store_true", default=False)
    pre.add_argument("--ticks", action="store_true", default=False)
    known, rest = pre.parse_known_args(argv)

    if known.facts:
        # Fact history mode — delegate to stream (without --facts flag)
        return _run_stream(rest, vertex_path=vertex_path, observer=observer)
    elif known.ticks:
        # Tick history mode — dedicated tick fetch and lens
        return _run_ticks(rest, vertex_path=vertex_path, observer=observer)
    else:
        # Default: fold state
        return _run_fold(rest, vertex_path=vertex_path, observer=observer)


def _render_main_help(argv: list[str]) -> int:
    """Render two-group help: vertex operations + root commands."""
    import shutil
    from painted.cli import (
        Format,
        HelpData,
        HelpFlag,
        HelpGroup,
        Zoom,
        render_help,
        scan_help_args,
    )
    from painted.core.writer import print_block

    zoom, fmt = scan_help_args(argv)

    verbs_group = HelpGroup(
        name="Verbs",
        hint="loops <verb> [vertex] [args]",
        detail="Implicit read: loops project = loops read project",
        flags=(
            HelpFlag(None, "read", "Read vertex state (default)", detail="[vertex] [--facts] [--ticks] [--kind KIND] [--since SINCE]"),
            HelpFlag(None, "emit", "Inject a fact", detail="[vertex] <kind> [KEY=VALUE ...] [--dry-run]"),
            HelpFlag(None, "sync", "Run sources (cadence-gated)", detail="[vertex] [--force] [--var KEY=VALUE]"),
            HelpFlag(None, "close", "Resolve and capture artifacts", detail="[vertex] <kind> <name> [message] [--dry-run]"),
        ),
    )

    commands_group = HelpGroup(
        name="Commands",
        flags=(
            HelpFlag(None, "test", "Test a .loop file", detail="<file> [--input FILE] [--limit N]"),
            HelpFlag(None, "compile", "Show compiled structure", detail="<file>"),
            HelpFlag(None, "validate", "Validate syntax and flow", detail="[files...]"),
            HelpFlag(None, "store", "Inspect store contents", detail="[file]"),
            HelpFlag(None, "init", "Initialize vertex", detail="[name] [--template NAME]"),
            HelpFlag(None, "ls", "List vertices"),
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
        groups=(verbs_group, commands_group, zoom_group, format_group, help_group),
    )

    if fmt == Format.JSON:
        import json
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


def _resolve_observer_flag(raw: str | None) -> str | None:
    """Resolve --observer flag, handling the special 'all' value.

    Returns:
        None — no flag given, defer to vertex scope declaration
        ""   — explicit 'all', always unscoped
        str  — explicit observer name, always scoped
    """
    if raw is None:
        return None  # no flag — vertex decides
    if raw.lower() == "all":
        return ""  # unscoped — will pass None to engine
    from .commands.identity import resolve_observer
    return resolve_observer(raw)


def _apply_vertex_scope(observer: str | None, vertex_path: Path | None) -> str | None:
    """Resolve observer default from vertex scope declaration.

    When observer is None (no flag given), checks the vertex's
    observer_scoped flag. Scoped vertices default to current observer.
    Unscoped vertices default to all.
    """
    if observer is not None:
        return observer  # explicit flag — use as-is

    # No flag: check vertex scope
    if vertex_path is not None:
        # Fast check: scan file text for scope declaration before full parse.
        # Full KDL parse costs ~1.5ms; text scan is ~0.1ms. Only parse if
        # the scope keyword is present (rare — most vertices are unscoped).
        try:
            text = vertex_path.read_text()
        except OSError:
            return None
        if 'scope "observer"' not in text:
            return None  # unscoped — show all
        # Keyword found — confirm with full parse (handles comments, etc.)
        from lang import parse_vertex_file
        ast = parse_vertex_file(vertex_path)
        if ast.observer_scoped:
            from .commands.identity import resolve_observer
            return resolve_observer(None)

    # Unscoped vertex or no vertex resolved yet — show all
    return None


def _dispatch_verb_first(verb: str, rest: list[str]) -> int:
    """Dispatch verb-first operations: ``loops <verb> [vertex] [args]``.

    Resolves ``--observer`` the same way as ``_dispatch_observer``, then
    delegates to the appropriate ``_run_*`` function with ``vertex_path=None``
    so they resolve the vertex from context (optional positional or local).
    """
    import argparse

    # Pre-parse --observer from rest (same pattern as _dispatch_observer)
    obs_parser = argparse.ArgumentParser(add_help=False)
    obs_parser.add_argument("--observer", default=None)
    obs_known, rest = obs_parser.parse_known_args(rest)
    observer = _resolve_observer_flag(obs_known.observer)

    if verb == "read":
        return _run_read(rest, vertex_path=None, observer=observer)
    if verb == "emit":
        return _run_emit(rest, vertex_path=None, observer=observer)
    if verb == "close":
        return _run_close(rest, vertex_path=None, observer=observer)
    if verb == "sync":
        return _run_sync(rest, vertex_path=None)

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

    Default (no subcommand or flags only) → read (fold by default).
    """
    import argparse

    # Pre-parse --observer from rest (before subcommand dispatch)
    obs_parser = argparse.ArgumentParser(add_help=False)
    obs_parser.add_argument("--observer", default=None)
    obs_known, rest = obs_parser.parse_known_args(rest)
    observer = _resolve_observer_flag(obs_known.observer)

    # Default: no subcommand or flags only → read (fold by default)
    if not rest or rest[0].startswith("-"):
        return _run_read(rest, vertex_path=vertex_path, observer=observer)

    op = rest[0]
    args = rest[1:]

    # Primary verbs
    if op == "read":
        return _run_read(args, vertex_path=vertex_path, observer=observer)
    if op == "emit":
        return _run_emit(args, vertex_path=vertex_path, observer=observer)
    if op == "close":
        return _run_close(args, vertex_path=vertex_path, observer=observer)
    if op == "sync":
        return _run_sync(args, vertex_path=vertex_path)

    # Dev tools
    if op == "store":
        return _run_store(args, vertex_path=vertex_path)

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

    _err(f"Unknown operation: {op}")
    return 1


def _dispatch_command(cmd: str, argv: list[str]) -> int:
    """Dispatch dev tools and setup commands."""
    from painted.cli.app_runner import run_app, AppCommand
    from painted.cli import HelpArg

    commands = [
        # Dev tools
        AppCommand(
            "test",
            "Test a .loop file — preview facts, no persistence",
            _run_test,
            detail="<file> [--input FILE] [--limit N]",
        ),
        AppCommand("compile", "Show compiled structure", _run_compile, detail="<file>"),
        AppCommand(
            "validate",
            "Validate syntax and flow",
            _run_validate,
            detail="[files...] — defaults to *.loop/*.vertex in cwd",
        ),
        AppCommand(
            "store",
            "Inspect store contents",
            _run_store,
            detail="[file] — vertex name, path, or .db file",
        ),
        # Setup / utility
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
        AppCommand("ls", "List vertices", _run_ls_root),
        AppCommand("add", "Add to template population", _run_add, detail="<target> <values...>"),
        AppCommand("rm", "Remove from template population", _run_rm, detail="<target> <key>"),
        AppCommand("export", "Materialize .list from store", _run_export, detail="<target>"),
    ]
    return run_app(
        [cmd] + argv, commands, prog="loops", description="Runtime for .loop and .vertex files"
    )


def _try_fast_read(argv: list[str]) -> int | None:
    """Ultra-fast path for ``read <vertex> --static --plain``.

    Detects the common read pattern before importing argparse (~3ms) or
    entering the 4-parser dispatch chain (~2ms). Returns exit code on match,
    None to fall through to regular dispatch.

    Matches: ``read <vertex> [--static] [--plain] [-q|-v|-vv]``
    Excludes: --facts, --ticks, --kind, --lens, --observer, --help, --json, --live, -i
    """
    # Must be verb-first read with at least: read <vertex> --static --plain
    if len(argv) < 4 or argv[0] != "read":
        return None

    rest = argv[1:]

    # Check for flags that require full dispatch
    has_static = False
    has_plain = False
    vertex_name = None

    for arg in rest:
        if arg == "--static":
            has_static = True
        elif arg == "--plain":
            has_plain = True
        elif arg in ("--facts", "--ticks", "--refs", "--kind", "--lens", "--observer",
                      "-h", "--help", "--json", "--live", "-i"):
            return None  # needs full dispatch
        elif arg.startswith("--") and "=" in arg:
            # --kind=X, --lens=X, --observer=X etc
            return None
        elif not arg.startswith("-") and vertex_name is None:
            vertex_name = arg
        elif not arg.startswith("-"):
            return None  # unexpected positional

    if not (has_static and has_plain and vertex_name):
        return None

    # Resolve vertex path (no argparse needed)
    vertex_path = _resolve_vertex_for_dispatch(vertex_name)
    if vertex_path is None:
        vertex_path = _resolve_named_vertex(vertex_name)

    # Build fast args — kind=None, lens=None, observer=None (no --observer flag)
    class _Ns:
        __slots__ = ("kind", "lens")
    known = _Ns()
    known.kind = None
    known.lens = None

    # Pass remaining flags (--static, --plain, -q, -v, -vv) as rest
    return _run_fold_fast(known, rest, vertex_path=vertex_path, observer=None)


def main(argv: list[str] | None = None) -> int:
    """Main entry point — three-tier dispatch.

    1. Known verbs (read, emit, sync, close) → verb-first dispatch
    2. Dev/setup commands (test, compile, validate, ...) → direct dispatch
    3. Vertex name → implicit read (or vertex-first op for backward compat)
    """
    if argv is None:
        argv = sys.argv[1:]

    # No args → help
    if not argv:
        return _render_main_help([])

    # Top-level help: -h/--help only when it's the first arg (no command yet)
    if argv[0] in ("-h", "--help"):
        return _render_main_help(argv)

    # Ultra-fast path: skip argparse + dispatch chain for common read pattern.
    # Must be checked before importing argparse (~3ms) and before entering
    # the 4-parser dispatch chain (~2ms).
    if argv[0] == "read":
        fast_result = _try_fast_read(argv)
        if fast_result is not None:
            return fast_result

    # Lazy argparse import — only pay the ~3ms cost when actually needed.
    # Injected into module globals so all functions in this module can use it.
    import argparse
    globals()["argparse"] = argparse

    # Tier 1: Known verbs → verb-first dispatch
    if argv[0] in _VERBS:
        return _dispatch_verb_first(argv[0], argv[1:])

    # Tier 2: Dev tools and setup commands → direct dispatch
    if argv[0] in _COMMANDS:
        return _dispatch_command(argv[0], argv[1:])

    # Tier 3: Try as vertex name → implicit read (with backward compat for old ops)
    vertex_name = argv[0]
    vertex_path = _resolve_vertex_for_dispatch(vertex_name)

    if vertex_path is not None:
        return _dispatch_observer(vertex_name, vertex_path, argv[1:])

    # Path-like arg → suggest the right invocation
    if vertex_name.endswith(".vertex") or vertex_name.startswith("./") or vertex_name.startswith("/"):
        _err(f"File arguments go with a command: loops sync {vertex_name}")
        return 1

    # Unknown command
    _err(f"Unknown command: {vertex_name}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
