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

import argparse  # noqa: F401 — many _run_* functions below reference it lazily
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
# typing deferred — TextIO only used in annotations (strings with __future__)


def _err(msg: str, file: TextIO | None = None) -> None:
    """Show an error message — thin alias to cli.output.err.

    Kept through step 6 of the CLI refactor for back-compat with tests and
    callers that haven't been threaded with a Reporter yet. ``file`` is
    accepted for legacy signature parity but ignored — cli.output.err
    always writes to stderr via PaintedReporter.
    """
    from loops.cli.output import err as _err_impl
    _ = file
    _err_impl(msg)


def _msg(msg: str, file: TextIO | None = None) -> None:
    """Show a success/info message — thin alias to cli.output.msg.

    See _err for the back-compat note. ``file`` is accepted for legacy
    signature parity but ignored.
    """
    from loops.cli.output import msg as _msg_impl
    _ = file
    _msg_impl(msg)


def _parse_vars(raw: list[str]) -> dict[str, str]:
    """Parse ['KEY=VALUE', ...] into {key: value}."""
    result: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"Invalid --var format (expected KEY=VALUE): {item!r}")
        key, _, value = item.partition("=")
        result[key] = value
    return result


from loops.errors import LoopsError  # noqa: E402
from loops.commands.resolve import (  # noqa: E402 — re-export for back-compat
    loops_home,
    _find_local_vertex,
    _warn_missing_fold_key,
    _extract_kind_keys,
    _try_topology_from_store,
    _topology_kind_keys_and_stores,
    _resolve_entity_refs,
    _resolve_writable_vertex,
    _resolve_vertex_store_path,
    _resolve_named_store,
    _resolve_named_vertex,
    _resolve_combine_child,
    _resolve_vertex_for_dispatch,
    _resolve_observer_flag,
    _apply_vertex_scope,
)

# --- Init cluster moved to commands/init.py ---
from loops.commands.init import (  # noqa: E402 — re-export for back-compat
    _ROOT_VERTEX, _MINIMAL_INSTANCE, _extract_block_text, _extract_loops_text,
    _find_source_vertex, _init_local_vertex, _register_with_aggregator,
    _seed_config_facts, _scaffold_artifacts, cmd_init, _run_init,
)

# --- Store cluster moved to commands/store.py ---
from loops.commands.store import _run_store  # noqa: E402,F401 — re-export for back-compat

# --- Population cluster moved to commands/population.py ---
from loops.commands.population import (  # noqa: E402,F401 — re-export for back-compat
    _run_ls, _run_ls_root, _run_add, _run_rm, _run_export,
)


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



# --- Validate/test/compile moved to commands/devtools.py ---
from loops.commands.devtools import (  # noqa: E402 — re-export for back-compat
    _run_validate, _run_test, _run_compile,
)


# --- Sync cluster moved to commands/sync.py ---
from loops.commands.sync import (  # noqa: E402 — re-export for back-compat
    _resolve_combine_vertex_paths, _execute_boundary_run,
    _run_sync_aggregate, _run_sync,
)



# --- Emit cluster moved to commands/emit.py ---
from loops.commands.emit import (  # noqa: E402 — re-export for back-compat
    _parse_emit_parts, cmd_emit, _run_emit, _run_close, _add_produced,
)


def _exit_lens_not_found(
    name: str,
    view_name: str,
    vertex_dir: Path | None,
    *,
    source: str,
) -> None:
    """Print a helpful error and ``sys.exit(2)`` for an unresolvable lens request.

    Lists the file-search tiers tried so the user can drop the lens in the
    right place or fix the typo. The view_name appears in the message because
    a lens module CAN exist but lack the requested view (e.g. fold_view
    present, stream_view missing) — same surface error, distinct cause, and
    the user inspects the named module to tell them apart.
    """
    from .lens_resolver import _build_search_path

    lines = [
        f"Lens '{name}' (requested via {source}) not found, "
        f"or found but missing {view_name}().",
        "Searched:",
    ]
    for d in _build_search_path(vertex_dir):
        lines.append(f"  {d}/{name}.py")
    lines.append(f"  built-in: loops.lenses.{name}")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


def _declared_kinds(vertex_path: Path) -> set[str]:
    """Return the set of kinds declared by a vertex (instance or aggregation).

    For an instance vertex, returns the kinds in its ``loops {}`` block.
    For an aggregation vertex that defines its own loops, those kinds.
    For an aggregation vertex with no loops block (pure combine), returns
    the union of source-vertex kinds — same union ``vertex_fold`` uses.

    Returns an empty set on parse/compile failure (validation is best-effort
    — callers should treat empty as "couldn't determine" rather than "vertex
    declares nothing").
    """
    try:
        from lang import parse_vertex_file
        from engine.compiler import compile_vertex
        from engine.vertex_reader import _collect_source_specs

        ast = parse_vertex_file(vertex_path)
        specs = compile_vertex(ast)
        if (ast.combine is not None or ast.discover is not None) and not specs:
            source_specs = _collect_source_specs(
                ast, vertex_path, override_kinds=frozenset(specs),
            )
            return set(source_specs.keys()) | set(specs.keys())
        return set(specs.keys())
    except Exception:
        return set()


def _validate_kind_or_exit(kind: str | None, vertex_path: Path | None) -> None:
    """If ``--kind X`` is set and X is not declared by the vertex, exit 2.

    Silent empty results hide the indistinguishability between:
    - typo in kind name (``--kind decsion``)
    - real kind that this vertex doesn't declare (``--kind decision`` on
      coupling-kernels, which only declares hypothesis/query-run/query-comparison)
    - valid kind with zero facts yet

    Strict validation surfaces the first two as actionable errors; the third
    keeps current "No data yet" behavior because the kind IS declared.

    Same fix shape as ``_exit_lens_not_found`` — third instance of the
    measurement-fidelity discipline. Honest naming: this is consumer-side
    validation of declared kinds, not the broader sensor-registry that
    alcove pointed at (that waits for concrete sensor use cases).

    Skips validation when ``kind`` is None (no filter requested) or the
    vertex's declared-kinds set is empty (couldn't determine — don't block).
    Path-style ``kind/key`` is split: only the kind half is validated.
    """
    if kind is None or vertex_path is None:
        return
    # kind/key drill-down: validate only the kind half.
    kind_only = kind.split("/", 1)[0]
    declared = _declared_kinds(vertex_path)
    if not declared:
        return  # Couldn't determine — don't second-guess the caller.
    if kind_only in declared:
        return

    import difflib
    suggestions = difflib.get_close_matches(
        kind_only, sorted(declared), n=3, cutoff=0.5,
    )
    lines = [
        f"Vertex '{vertex_path.stem}' does not declare kind '{kind_only}'.",
    ]
    if suggestions:
        lines.append(f"Did you mean: {', '.join(suggestions)}?")
    lines.append(f"Declared kinds: {', '.join(sorted(declared)) or '(none)'}")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


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

    Explicit lens requests fail loudly. When ``--lens NAME`` or a vertex
    ``lens { fold "NAME" }`` declaration cannot be resolved in any tier
    (vertex-local, cwd, user-global, built-in), this prints a helpful error
    listing the search path and calls ``sys.exit(2)``. Silent fallback to a
    different view would hide measurement misalignment — same failure shape
    as alcove's recency-counter-vs-emitted-kind bug. The user explicitly
    asked for a lens by name; they get either that lens or a clear failure.

    Implicit fallbacks (no ``lens_flag``, no vertex decl) still return the
    built-in default — that path is the normal "no lens requested" case.
    """
    from .lens_resolver import resolve_lens

    # Determine vertex directory for lens search path
    vertex_dir = vertex_path.parent if vertex_path is not None else None

    # Tier 1: --lens flag — explicit request, fail loudly if unresolvable
    if lens_flag is not None:
        fn = resolve_lens(lens_flag, view_name, vertex_dir=vertex_dir)
        if fn is not None:
            return fn
        _exit_lens_not_found(lens_flag, view_name, vertex_dir, source="--lens flag")

    # Tier 2: vertex lens{} declaration — explicit decl, fail loudly if unresolvable
    if vertex_path is not None:
        vertex_lens = _get_vertex_lens_decl(vertex_path)
        if vertex_lens is not None:
            if view_name == "fold_view" and vertex_lens.fold:
                fn = resolve_lens(vertex_lens.fold, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn
                _exit_lens_not_found(
                    vertex_lens.fold, view_name, vertex_dir,
                    source=f"vertex lens decl in {vertex_path.name}",
                )
            elif view_name == "stream_view" and vertex_lens.stream:
                fn = resolve_lens(vertex_lens.stream, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn
                _exit_lens_not_found(
                    vertex_lens.stream, view_name, vertex_dir,
                    source=f"vertex lens decl in {vertex_path.name}",
                )

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
    elif view_name == "trace_view":
        from .lenses.trace import trace_view
        return trace_view

    from .lenses.fold import fold_view
    return fold_view


def _effective_lens_name(
    lens_flag: str | None,
    vertex_path: Path | None,
    view_name: str,
) -> str | None:
    """Return the effective lens name for a command — flag or vertex decl.

    Used by fetch resolution so a lens-declared ``fetch`` overrides the
    default command fetch, regardless of whether the lens was requested
    via --lens or via the vertex's lens{} block.
    """
    if lens_flag is not None:
        return lens_flag
    if vertex_path is None:
        return None
    vertex_lens = _get_vertex_lens_decl(vertex_path)
    if vertex_lens is None:
        return None
    if view_name == "fold_view" and vertex_lens.fold:
        return vertex_lens.fold
    if view_name == "stream_view" and vertex_lens.stream:
        return vertex_lens.stream
    return None


def _resolve_lens_fetch(
    lens_flag: str | None,
    vertex_path: Path | None,
    view_name: str,
):
    """Return a lens-declared fetch callable, or None to fall through to default.

    A lens module may export ``fetch(vertex_path, **kwargs)`` alongside its
    view function. When present, the lens owns its input contract — useful
    for composition lenses (fold + ticks, etc.).
    """
    name = _effective_lens_name(lens_flag, vertex_path, view_name)
    if name is None:
        return None
    from .lens_resolver import resolve_lens_fetch
    vertex_dir = vertex_path.parent if vertex_path is not None else None
    return resolve_lens_fetch(name, vertex_dir=vertex_dir)


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

from loops.commands.stream import _run_stream  # noqa: F401 — re-export for back-compat


# --- Fold helpers moved to cli.views.fold; re-exported for test back-compat ---
from loops.cli.views.fold import (  # noqa: E402
    _extract_refs_depth,
    _looks_like_vertex_path,
)









# --- whoami cluster moved to commands/whoami.py ---
from loops.commands.whoami import _run_whoami, _whoami_from_identity_store  # noqa: F401


# Verb-first dispatch: `loops <verb> [vertex] [args]`.
# These are the primary CLI verbs — read (implicit default), emit, sync, close, cite.
# `trace` retired 2026-05-17 (D of trace-dissolution); use `read --diff`
# for entity lifecycle, optionally with --refs N for ref-graph walks.
_VERBS = frozenset({"read", "emit", "close", "sync", "cite"})

# Dev and setup commands dispatched directly.
_DEV_COMMANDS = frozenset({"test", "compile", "validate", "store"})
_SETUP_COMMANDS = frozenset({"init", "whoami", "ls", "add", "rm", "export"})

# Combined for dispatch check (verbs checked first, then these).
_COMMANDS = _DEV_COMMANDS | _SETUP_COMMANDS

# Vertex-first operations: `loops <vertex> <op>`.
_VERTEX_OPS = frozenset({
    "read", "emit", "close", "sync", "store", "cite",
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
            HelpFlag(None, "read", "Read vertex state", detail="[vertex] [kind/key] [--diff] [--refs [N]] [--facts] [--ticks] [--kind K] [--key PREFIX]"),
            HelpFlag(None, "emit", "Inject a fact", detail="[vertex] <kind> [KEY=VALUE ...] [--dry-run]"),
            HelpFlag(None, "sync", "Run sources (cadence-gated)", detail="[vertex] [--force] [--var KEY=VALUE]"),
            HelpFlag(None, "close", "Resolve and capture artifacts", detail="[vertex] <kind> <name> [message] [--dry-run]"),
            HelpFlag(None, "cite", "Attention signal — inform current work with prior refs", detail="[vertex] <ref1> <ref2> ... [--context NAME] [-m MSG]"),
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



def main(argv: list[str] | None = None) -> int:
    """Main entry point — delegates to ``cli.app.main``.

    Behaviour is owned by the new dispatcher; this function only exists
    as the legacy entry point that the console-script and ``python -m
    loops`` resolve to.
    """
    from loops.cli.app import main as _cli_main

    return _cli_main(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
