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

    # Pre-check --facts for fetch (it stays in rest for painted's parser too)
    want_facts = "--facts" in rest

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
        return fetch_fold(
            vertex_path, kind=known.kind, observer=obs_for_engine,
            retain_facts=want_facts,
        )

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
        parser.add_argument("--facts", action="store_true", default=False,
                            help="Show source facts per item")

    def _build_fold_fidelity(parsed, base):
        """Inject visibility tags from fold-specific flags."""
        visible = set()
        if getattr(parsed, "refs", False):
            visible.add("refs")
        if getattr(parsed, "facts", False):
            visible.add("facts")
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
    """Unified read verb — routes to fold (default, with visibility layers) or stream/ticks.

    ``loops read [vertex] [flags]`` is the primary read interface.
    Default (no flags) shows fold state. ``--facts`` and ``--refs`` are
    visibility layers on the fold view. ``--ticks`` routes to tick history.
    ``--facts`` with ``--since`` or ``--id`` routes to stream (temporal query).

    This is a thin router — delegates to ``_run_fold``, ``_run_stream``,
    or ``_run_ticks``.
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--facts", action="store_true", default=False)
    pre.add_argument("--ticks", action="store_true", default=False)
    pre.add_argument("--since", default=None)
    pre.add_argument("--id", default=None, dest="fact_id")
    known, rest = pre.parse_known_args(argv)

    if known.facts and (known.since or known.fact_id):
        # Temporal query — delegate to stream (without --facts flag)
        stream_rest = rest
        if known.since:
            stream_rest = [*stream_rest, "--since", known.since]
        if known.fact_id:
            stream_rest = [*stream_rest, "--id", known.fact_id]
        return _run_stream(stream_rest, vertex_path=vertex_path, observer=observer)
    elif known.ticks:
        # Tick history mode — dedicated tick fetch and lens
        return _run_ticks(rest, vertex_path=vertex_path, observer=observer)
    else:
        # Default: fold state (re-inject --facts if present — it's a visibility layer)
        fold_rest = [*rest, "--facts"] if known.facts else rest
        return _run_fold(fold_rest, vertex_path=vertex_path, observer=observer)


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



# _resolve_observer_flag, _apply_vertex_scope — moved to commands/resolve.py, re-exported above


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
