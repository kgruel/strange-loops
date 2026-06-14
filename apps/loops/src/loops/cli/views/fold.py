"""cli.views.fold — the read/fold view (the big one).

Collapses four legacy entry points and two helpers into a single
``argparse → Operation → dispatch`` shape:

  retired here: ``_run_fold`` (orchestrator), ``_run_fold_fast`` (the
    plain-text fast path — see decision/cli-refactor-fast-path-retired),
    ``_render_fold_plain`` (the fast path's renderer), ``_run_fold_diff``
    (the --diff lifecycle path)
  absorbed: ``_extract_refs_depth``, ``_looks_like_vertex_path``,
    ``_is_static_plain`` (now a no-op — see above)

The single parser handles every fold flag (entity disambiguation,
``--kind`` / ``--key`` / ``--lens``, visibility layers, ``--diff``,
``--refs [N]``, output mode, fidelity, density budgets, ``--plain`` /
``--json``). The view then builds one ``Operation`` and hands it to
``dispatch``. Painted is never imported at view scope — every renderer
boundary lives in ``cli.output`` (Reporter) or ``cli.live``
(InPlaceRenderer).

Design anchor: decision/design/cli-refactor-option-2-siftd-shape;
decision/cli-refactor-fast-path-retired.
"""
from __future__ import annotations

import argparse
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from painted.cli import OutputMode
from painted.cli.types import add_cli_args, parse_fidelity, parse_zoom

from ..invocation import Invocation
from ..dispatch import dispatch
from ..operation import Operation


# --- Helpers (absorbed from main.py) --------------------------------------


def _looks_like_vertex_path(s: str) -> bool:
    """True when ``s`` looks like a filesystem path to a vertex file.

    Conservative — recognises the forms tests and callers actually use:
    absolute path, ``./`` / ``../`` relative, or a ``.vertex`` suffix.
    """
    if s.startswith("/") or s.startswith("./") or s.startswith("../"):
        return True
    if s.endswith(".vertex"):
        return True
    return False


def _extract_refs_depth(rest: list[str]) -> tuple[int, list[str]]:
    """Extract ``--refs [N]`` from rest; return ``(depth, cleaned_rest)``.

    Manual scan rather than ``nargs='?'`` because the latter is brittle
    when the optional integer is followed by another flag.

      ``--refs``        → depth 1
      ``--refs 2``      → depth 2 (and the 2 is consumed)
      ``--refs=N``      → depth N
      absent            → depth 0
      ``--refs <non-int>`` → depth 1, non-int stays in rest
    """
    depth = 0
    out: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--refs":
            if i + 1 < len(rest):
                try:
                    depth = int(rest[i + 1])
                    i += 2
                    continue
                except ValueError:
                    pass
            depth = 1
            i += 1
            continue
        if arg.startswith("--refs="):
            try:
                depth = int(arg.split("=", 1)[1])
            except ValueError:
                depth = 1
            i += 1
            continue
        out.append(arg)
        i += 1
    return depth, out


# --- Argparse construction -------------------------------------------------


def _build_parser(has_vertex_path: bool) -> argparse.ArgumentParser:
    """Build the unified fold parser.

    When the dispatch layer already resolved a vertex (vertex-first form)
    the first positional collapses from ``vertex_or_entity`` to just
    ``entity``.
    """
    parser = argparse.ArgumentParser(prog="loops read")
    if not has_vertex_path:
        parser.add_argument("vertex_or_entity", nargs="?", default=None,
                            help="Vertex name, path, or kind/key entity")
        parser.add_argument("entity", nargs="?", default=None,
                            help="Entity filter (kind/key)")
    else:
        parser.add_argument("entity", nargs="?", default=None,
                            help="Entity filter (kind/key)")
    parser.add_argument("--kind", default=None, help="Filter by fact kind")
    parser.add_argument("--key", default=None, help="Filter by fold key (prefix scan with trailing /)")
    parser.add_argument("--lens", default=None, help="Lens name for rendering")
    # Domain-query selectors — these change WHAT is fetched (folded vs raw
    # stream; entity-delta trace), not how much of fixed data is shown, so
    # they stay loops-side (decision/design/disclosure-vs-domain-query-axis).
    parser.add_argument("--facts", action="store_true", default=False,
                        help="Show raw fact stream instead of folded state")
    parser.add_argument("--diff", action="store_true", default=False,
                        help="Show only facts not yet reflected in the fold")
    # Pure-terminal axes (depth, format, mode, density budgets) dissolve into
    # painted: add_cli_args owns -q/-v, --plain/--json, --static/--live/-i,
    # and --max-chars/--max-lines (decision/design/full-painted-integration-
    # residue; grow-painted-over-workaround). dests are painted's standard
    # ones (quiet/verbose/static/live/interactive/max_chars/max_lines).
    add_cli_args(parser, modes={OutputMode.LIVE, OutputMode.INTERACTIVE}, budgets=True)
    return parser


# --- Entity / vertex resolution -------------------------------------------


def _resolve_positionals(
    args: argparse.Namespace, has_vertex_path: bool,
) -> tuple[str | None, str | None]:
    """Disambiguate the leading positionals.

    Returns ``(vname, entity)`` where ``vname`` is the named-vertex
    reference (or None) and ``entity`` is ``"kind/key"`` (or None).
    Mirrors the disambiguation rules legacy ``_run_fold`` applied:

      vertex file path → vertex, second positional → entity
      contains "/"     → entity, vertex resolves locally
      bare token       → named vertex, second positional → entity
    """
    if has_vertex_path:
        return None, getattr(args, "entity", None)

    first = getattr(args, "vertex_or_entity", None)
    if first is None:
        return None, None
    if _looks_like_vertex_path(first):
        return first, args.entity
    if "/" in first:
        return None, first
    return first, args.entity


def _resolve_vertex_path(
    ctx: Invocation, vname: str | None,
) -> Path | None:
    """Resolve the fold's target vertex.

    Honours ``ctx.vertex_path`` first (dispatch already resolved it).
    Otherwise: name → ``_resolve_vertex_for_dispatch`` (local-first) →
    ``_resolve_named_vertex`` (config-level) → local fallback. Returns
    ``None`` only when no vertex can be located at all.
    """
    if ctx.vertex_path is not None:
        return ctx.vertex_path
    from loops.commands.identity import resolve_local_vertex
    from loops.commands.resolve import (
        _resolve_named_vertex,
        _resolve_vertex_for_dispatch,
    )

    if vname is not None:
        local = _resolve_vertex_for_dispatch(vname)
        if local is not None:
            return local
        try:
            return _resolve_named_vertex(vname)
        except Exception:
            return None
    try:
        return resolve_local_vertex()
    except FileNotFoundError:
        return None


# --- Mode resolution -------------------------------------------------------


def _resolve_mode(args: argparse.Namespace, lens: str | None) -> str:
    """Pick an output mode from flags + lens context.

    Defaults to ``"static"`` — mirrors the legacy ``default_mode=STATIC``
    for fold. ``--live`` wins over ``--static``; ``-i`` only triggers
    INTERACTIVE for views that bind a handler (autoresearch lens).
    """
    if args.live:
        return "live"
    if args.interactive and lens == "autoresearch":
        return "interactive"
    return "static"


# --- Fetch closures --------------------------------------------------------


def _build_fold_fetch(
    vertex_path: Path,
    observer: str | None,
    kind: str | None,
    key: str | None,
    refs_depth: int,
    want_facts: bool,
    lens: str | None,
) -> Any:
    """Return a zero-arg callable that produces the fold data.

    Honours lens-declared fetch (composition lenses) when present;
    otherwise calls ``commands.fetch.fetch_fold`` with the full kwarg
    surface.
    """
    from loops.commands.resolve import _apply_vertex_scope

    obs = _apply_vertex_scope(observer, vertex_path) or None
    _validate_kind_or_exit(kind, vertex_path)

    from loops.cli.lens import _resolve_lens_fetch

    lens_fetch = _resolve_lens_fetch(lens, vertex_path, "fold_view")

    def fetch_data():
        if lens_fetch is not None:
            from loops.lens_resolver import call_lens_fetch

            return call_lens_fetch(
                lens_fetch, vertex_path,
                kind=kind, key=key, observer=obs,
                retain_facts=want_facts,
                refs_depth=refs_depth,
            )
        from loops.commands.fetch import fetch_fold

        return fetch_fold(
            vertex_path, kind=kind, key=key, observer=obs,
            retain_facts=want_facts,
            refs_depth=refs_depth,
        )

    return fetch_data


def _build_diff_fetch(
    vertex_path: Path,
    observer: str | None,
    kind: str,
    key: str,
    refs_depth: int,
) -> Any:
    """Return a zero-arg callable that produces diff (trace) data.

    Reuses the trace fetch path. ``_diff`` flag is set on the returned
    dict so the trace lens renders the field-delta view.
    """
    from loops.commands.resolve import _apply_vertex_scope

    obs = _apply_vertex_scope(observer, vertex_path) or None
    _validate_kind_or_exit(kind, vertex_path)

    def fetch_data():
        from loops.commands.fetch import fetch_trace

        data = fetch_trace(
            vertex_path,
            kind=kind, key=key, observer=obs,
            refs_depth=refs_depth,
        )
        data["_diff"] = True
        return data

    return fetch_data


async def _build_fold_stream(fetch_data) -> AsyncIterator[Any]:
    """Wrap a sync fetch into an async generator for live mode."""
    import asyncio

    yield fetch_data()
    while True:
        await asyncio.sleep(2)
        yield fetch_data()


def _validate_kind_or_exit(kind: str | None, vertex_path: Path | None) -> None:
    """Validate kind against vertex declarations; exit 2 on mismatch."""
    if vertex_path is None:
        return
    from loops.commands.resolve import _validate_kind_or_exit as _impl

    _impl(kind, vertex_path)


# --- JSON short-circuit ----------------------------------------------------


def _render_json(data: Any, reporter) -> int:
    """Render the fold data as JSON to stdout and return 0.

    Bypasses dispatch's lens path — JSON wants the raw fetched shape,
    not a rendered Block. Goes through ``reporter.msg`` so test
    reporters can capture it.
    """
    import json

    def _default(obj):
        if hasattr(obj, "_asdict"):
            return obj._asdict()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    reporter.msg(json.dumps(data, default=_default))
    return 0


# --- Entry point -----------------------------------------------------------


def run(argv: list[str], ctx: Invocation) -> int:
    """Fold view entry — single argparse → Operation → dispatch.

    Steps:
      1. Pre-extract ``--refs [N]`` (manual scan; argparse can't model
         the optional-int-or-flag form cleanly).
      2. Parse remaining argv with the unified parser.
      3. Resolve positionals → vertex name + entity.
      4. Route an embedded entity into ``--kind`` (when --kind/--key
         not already set).
      5. Resolve the vertex path.
      6. Build the fetch closure (diff vs fold) and the Operation.
      7. Dispatch — static / live / interactive branches.
    """
    has_vertex_path = ctx.vertex_path is not None
    refs_depth, argv = _extract_refs_depth(argv)
    parser = _build_parser(has_vertex_path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    # Plain / ANSI: --plain forces ANSI off. Reporter exposes use_ansi
    # for PaintedReporter; setting it pre-dispatch is the canonical
    # honour-point. The mutation is harmless for BufferReporter (it
    # carries the attr but the buffer doesn't care).
    if args.plain and hasattr(ctx.reporter, "use_ansi"):
        ctx.reporter.use_ansi = False

    vname, entity = _resolve_positionals(args, has_vertex_path)

    # Entity → --kind when neither --kind nor --key is set. Matches the
    # legacy disambiguation: "kind/" / "kind/prefix/" / "kind/key" all
    # fold into fetch_fold's _split_kind_key helper.
    if (
        entity is not None and "/" in entity
        and args.kind is None and args.key is None
    ):
        args.kind = entity

    vertex_path = _resolve_vertex_path(ctx, vname)
    if vertex_path is None:
        ctx.reporter.err("No vertex resolved — run `loops init` first.")
        return 1

    # --diff routes to the trace fetcher + trace_view lens. Diff requires
    # a target entity (kind/key); error out clearly when missing.
    if args.diff:
        target = args.kind if "/" in (args.kind or "") else None
        if target is None:
            ctx.reporter.err(
                "usage: sl read [vertex] <kind>/<key> --diff\n"
                "  --diff renders cumulative field-deltas of one entity's "
                "lifecycle; supply a kind/key."
            )
            return 2
        diff_kind, diff_key = target.split("/", 1)
        fetch_data = _build_diff_fetch(
            vertex_path, ctx.observer, diff_kind, diff_key, refs_depth,
        )
        # Base view stays "trace" — --lens overrides the *module* only.
        render_lens = "trace"
        lens_override = args.lens
    else:
        # "trace" is the internal lens for --diff; requesting it directly
        # routes trace_view through the fold fetcher (FoldState), which crashes.
        # The dissolution landing point is --diff — redirect clearly.
        if args.lens == "trace":
            ctx.reporter.err(
                "'trace' is an internal lens — use --diff to render entity deltas:\n"
                "  sl read [vertex] <kind>/<key> --diff"
            )
            return 2
        fetch_data = _build_fold_fetch(
            vertex_path, ctx.observer,
            kind=args.kind, key=args.key,
            refs_depth=refs_depth,
            want_facts=args.facts,
            lens=args.lens,
        )
        render_lens = "fold"
        lens_override = args.lens

    # --json short-circuits the lens path entirely.
    if args.json:
        try:
            data = fetch_data()
        except Exception as exc:
            ctx.reporter.err(f"Error: {exc}")
            return 1
        return _render_json(data, ctx.reporter)

    # Fidelity: painted compiles the pure-terminal axes (depth from -q/-v,
    # density from --max-chars/--max-lines). The domain-query selectors'
    # visibility (--facts, --refs N>0) is merged in loops-side — they are not
    # painted disclosure tags (decision/design/disclosure-vs-domain-query-axis).
    from dataclasses import replace as _replace

    base = parse_fidelity(args, parse_zoom(args), tags=None)
    domain_visible = set(base.visible)
    if args.facts:
        domain_visible.add("facts")
    if refs_depth > 0:
        domain_visible.add("refs")
    fidelity = _replace(base, visible=frozenset(domain_visible))

    mode = _resolve_mode(args, args.lens)

    # Stream / interactive bindings ---------------------------------------
    stream_fn: Callable[[], AsyncIterator[Any]] | None = None
    if mode == "live":
        # Capture the closure-bound fetch_data for the async generator.
        stream_fn = lambda: _build_fold_stream(fetch_data)  # noqa: E731

    interactive_handler = None
    if mode == "interactive":
        interactive_handler = _build_autoresearch_handler(vertex_path, ctx.observer)

    op = Operation(
        verb="read",
        fn=fetch_data,
        params={},
        render_lens=render_lens,
        lens_override=lens_override,
        fidelity=fidelity,
        render_context={"_diff": True} if args.diff else {},
        vertex_path=vertex_path,
        observer=ctx.observer,
        mode=mode,  # type: ignore[arg-type]
        stream_fn=stream_fn,
        interactive_handler=interactive_handler,
    )
    return dispatch(op, reporter=ctx.reporter)


# --- Interactive handler (autoresearch TUI) -------------------------------


def _build_autoresearch_handler(vertex_path: Path, observer: str | None):
    """Bind the autoresearch TUI to the resolved vertex + observer.

    The handler runs the asyncio TUI app and returns its exit code (or
    0 on graceful close). Lives here rather than in dispatch so it
    stays one indirection from the args that triggered it.
    """

    def handle() -> int:
        import asyncio

        from loops.commands.resolve import _apply_vertex_scope
        from loops.tui.autoresearch_app import AutoresearchApp

        obs = _apply_vertex_scope(observer, vertex_path)
        app = AutoresearchApp(vertex_path, observer=obs)
        asyncio.run(app.run())
        return 0

    return handle

