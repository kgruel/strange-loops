"""commands.ticks — tick history and drill-down."""
from __future__ import annotations

import argparse
from pathlib import Path


def _tick_drill_header(tick_meta: dict, width: int | None) -> "Block":
    """Compact header for tick drill-down, composed above the fold/lens
    output. Row content (title, window, attest) is the shared grammar's."""
    from painted import Block, Style

    from loops.lenses._grammar import tick_drill_rows

    if not tick_meta:
        return Block.text("", Style())

    rows = tick_drill_rows(tick_meta)
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

    from loops.commands.resolve import _resolve_vertex_for_dispatch

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex_or_index", nargs="?", default=None)
        pre.add_argument("index", nargs="?", default=None)
    else:
        pre.add_argument("index", nargs="?", default=None)
    pre.add_argument("--since", default=None)
    # --as-of (SPEC §9.3, equal-cursors): rewind the tick-window listing to a
    # historical anchor. A tick DRILL always interprets its own snapshot under
    # as_of=tick.ts (engine.vertex_tick_fold) — the flag only shifts the LIST
    # window, not the per-tick interpretation.
    pre.add_argument("--as-of", default=None, dest="as_of")
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
            from loops.commands.identity import resolve_local_vertex as _rlv
            vertex_path = _rlv()
    else:
        _try_index(known.index)

    # Drill-down: show fold state snapshot from tick payload
    if tick_index is not None or tick_range is not None:
        resolved_render_fn = None

        def fetch():
            if tick_range is not None:
                from loops.commands.fetch import fetch_tick_range_fold
                return fetch_tick_range_fold(
                    vertex_path, tick_range[0], tick_range[1], since=known.since,
                )
            else:
                from loops.commands.fetch import fetch_tick_fold
                return fetch_tick_fold(vertex_path, tick_index, since=known.since)

        def render(ctx, data):
            nonlocal resolved_render_fn
            from painted import Block, Style, join_vertical
            from loops.cli.lens import _resolve_render_fn
            from loops.commands.resolve import _vertex_name

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

            from loops.lens_resolver import call_lens
            body = call_lens(
                resolved_render_fn, fold_state, ctx.zoom, w,
                vertex_name=_vertex_name(vertex_path),
                piped=not ctx.is_tty,
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
        )

    # Listing mode: show tick history
    from loops.commands.fetch import fetch_ticks

    resolved_render_fn = None

    def fetch_listing():
        return fetch_ticks(vertex_path, since=known.since, as_of=known.as_of)

    def render_listing(ctx, data):
        nonlocal resolved_render_fn
        from loops.cli.lens import _resolve_render_fn
        from loops.commands.resolve import _vertex_name
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, "ticks_view",
            )
        w = ctx.width if ctx.is_tty else None
        from loops.lens_resolver import call_lens
        return call_lens(
            resolved_render_fn, data, ctx.zoom, w,
            vertex_name=_vertex_name(vertex_path),
            piped=not ctx.is_tty,
        )

    return run_cli(
        rest,
        fetch=fetch_listing,
        render=render_listing,
        prog="loops ticks",
        description="Show tick history",
    )
