"""Stream command — temporal event history (raw facts, reverse-chrono)."""
from __future__ import annotations

import argparse
from pathlib import Path


def _run_stream(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
    """Run stream command — the temporal event history (raw facts, reverse-chrono).

    Content search re-bound onto ``read --match`` (S5), so this is now purely a
    temporal mode: an optional leading vertex name, ``--kind``/``--since``
    filters, and ``--id`` single-fact lookup. The first positional is a vertex
    name only (no search-query fallback).
    """
    from painted import run_cli
    from loops.commands.resolve import _validate_kind_or_exit, _vertex_name
    from loops.cli.lens import _resolve_render_fn
    from loops.cli.output import err as _err
    from .resolve import _resolve_vertex_for_dispatch, _apply_vertex_scope

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex_name", nargs="?", default=None)
    pre.add_argument("--kind", default=None)
    pre.add_argument("--since", default=None)
    pre.add_argument("--lens", default=None)
    pre.add_argument("--id", default=None, dest="fact_id")
    known, rest = pre.parse_known_args(argv)

    # Render function resolved lazily — vertex_path may not be known until fetch()
    resolved_render_fn = None

    def fetch():
        nonlocal vertex_path, observer

        if vertex_path is None:
            from .identity import resolve_local_vertex as _resolve_local_vertex

            first = getattr(known, "vertex_name", None)
            if first is not None:
                resolved = _resolve_vertex_for_dispatch(first)
                if resolved is not None:
                    vertex_path = resolved
            if vertex_path is None:
                vertex_path = _resolve_local_vertex()

        # Apply vertex scope — deferred until vertex_path is known
        observer = _apply_vertex_scope(observer, vertex_path)
        obs_for_engine = observer if observer else None

        # Kind validation: --kind X against vertex.declared_kinds.
        # Same fix shape as _exit_lens_not_found — surfaces consumer-side
        # measurement misalignment loudly instead of silent empty results.
        _validate_kind_or_exit(known.kind, vertex_path)

        # --id: single fact lookup by ID or prefix
        if known.fact_id is not None:
            from .fetch import fetch_fact_by_id
            try:
                fact = fetch_fact_by_id(vertex_path, known.fact_id)
            except ValueError as e:
                _err(str(e))
                return {"facts": [], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}
            if fact is None:
                return {"facts": [], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}
            return {"facts": [fact], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}

        from .fetch import fetch_stream
        return fetch_stream(
            vertex_path,
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
        from ..lens_resolver import call_lens
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
    )
