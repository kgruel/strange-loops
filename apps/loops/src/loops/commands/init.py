"""Init command — vertex creation and template stamping."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


_ROOT_VERTEX = """\
// Root vertex — discovers all .vertex files under this directory
discover "./**/*.vertex"
"""


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
    from loops.commands.resolve import loops_home

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
    from loops.commands.resolve import loops_home

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
    from loops.commands.resolve import loops_home

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
    from loops.main import _msg

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
    from loops.commands.resolve import loops_home
    from loops.main import _msg

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
    from loops.commands.resolve import loops_home
    from loops.commands.emit import _parse_emit_parts
    from loops.main import _msg

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
