"""dispatch — execute an Operation, route the result through a Reporter.

The central CLI primitive after Operation. Every view's ``run(argv, ctx)``
ends with ``return dispatch(op, reporter=ctx.reporter)``. dispatch owns
the action / static / live / interactive branches; this is what painted's
``run_cli`` used to own, now ours.

Branches:

  ACTION (op.render_lens is None):
      result = op.fn(**op.params)
      if result is not None: reporter.show(result)
      return 0

  INTERACTIVE (op.mode == "interactive" and op.interactive_handler):
      return op.interactive_handler()

  LIVE (op.mode == "live" and op.stream_fn):
      fold onto painted run_cli(fetch_stream=, live_delivery="surface")

  STATIC (default for display ops):
      data = op.fn(**op.params)
      block = lens(data, zoom, width, ...) via lens_resolver
      reporter.print_block(block)

Lens resolution goes through ``loops.lens_resolver``: name → callable via
the 4-tier search (vertex-local / project-local / user-global / built-in).
Failure to resolve is reported and returns exit code 2.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .operation import Operation
from .output import Block, Reporter, Zoom

if TYPE_CHECKING:
    from .output import Fidelity


# --- Lens resolution (thin wrapper around lens_resolver) -------------------

# Maps Operation.render_lens names to the lens-module view-function name
# convention. ``"fold"`` → looks up ``fold_view`` in the lens module
# ``loops.lenses.fold`` (or any of the 4-tier override locations).
_VIEW_SUFFIX = {
    "fold": "fold_view",
    "stream": "stream_view",
    "store": "store_view",
    "ticks": "ticks_view",
}


def _resolve_lens(
    name: str,
    vertex_path: Path | None,
    *,
    lens_override: str | None = None,
):
    """Resolve a render_lens (+ optional override) to its callable.

    Delegates to ``cli.lens._resolve_render_fn`` so the strict
    "explicit lens request must resolve or sys.exit(2)" discipline
    applies uniformly.

    The function within the lens module is named ``<base>_view`` per
    ``_VIEW_SUFFIX`` (or ``<name>_view`` for new verbs). When
    ``lens_override`` is set, the lens *module* is the override but
    the function-name lookup stays anchored to the base view — so
    ``--lens autoresearch`` on a fold operation finds
    ``loops.lenses.autoresearch.fold_view`` (the re-export pattern,
    see lenses/autoresearch.py).
    """
    from loops.cli.lens import _resolve_render_fn

    view_name = _VIEW_SUFFIX.get(name, f"{name}_view")
    return _resolve_render_fn(lens_override, vertex_path, view_name)


def _surface_gate(op: Operation, data) -> bool:
    """True when the DEFAULT fold path should route through the Surface.

    Two conditions: the fetched data is a ``FoldState`` AND the effective fold
    lens is the built-in (no ``--lens`` override and no vertex ``lens{}`` fold
    declaration). ``_effective_lens_name`` returning ``None`` (no decl) or
    ``"fold"`` (explicitly the built-in) both pass; a custom name (e.g.
    ``identity_prompt``) fails the gate and keeps the raw FoldState so the
    vertex-declared lens renders its own shape. isinstance is checked first so a
    non-FoldState shape (e.g. a lens-declared fetch returning a dict)
    short-circuits.
    """
    from atoms import FoldState

    if not isinstance(data, FoldState):
        return False
    from loops.cli.lens import _effective_lens_name

    name = _effective_lens_name(op.lens_override, op.vertex_path, "fold_view")
    return name in (None, "fold")


def _spec_has_dropped_transforms(spec) -> bool:
    """True when *spec* carries read-grammar transforms that the Surface path
    would apply but the gate-fail path silently drops.

    Excludes ``queried_key`` (single ``--key`` also flows to
    ``fetch_fold(key=)``), ``--kind`` (applied at fetch, not on the spec), and
    ``count_by`` (``--by`` is a no-op without ``--count`` on EVERY path —
    ``_project_surface`` only counts when ``do_count`` is set — so warning on a
    bare ``--by`` would over-claim it was dropped for being custom-lens). Each
    is excluded for the same reason: it still functions (or no-ops everywhere)
    on a custom-lens vertex, so it is not a genuinely-dropped transform.
    Everything listed here is Surface-only and genuinely inert when the gate
    fails (B3 / thread:gate-fail-ignores-surface-transforms).
    """
    if spec is None:
        return False
    return bool(
        spec.match
        or spec.key_or
        or spec.where
        or spec.observer
        or spec.fields
        or spec.limit is not None
        or spec.last is not None
        or spec.do_count
        or spec.full
    )


def _project_surface(op: Operation, data):
    """Project a FoldState into the Surface to encode, applying the read-grammar
    transforms carried on ``op.surface_spec`` in a FIXED canonical order.

    This is the single seam both encoders go through (text lens + ``--json``), so
    plain and json carry the SAME transformed rows. ``queried_key``/``full`` flow
    into ``project()`` itself (granularity by address-specificity); the remaining
    fields are Surface→Surface transforms applied filter → select → count →
    budget. ``--kind`` is NOT here — it is already applied at fetch time on the
    FoldState, so it must not be double-applied.

    count BEFORE budget is deliberate: ``count()`` emits one row per group in
    count-desc order with ``salience=count``, so a following ``budget(limit=N)``
    takes the top-N GROUPS by count (the ``sort | uniq -c | sort | head``
    semantic). Budgeting first would instead count only the head of the raw
    population — the count-row salience would never do its job.
    """
    from loops.surface import budget, count, filter, project, search, select

    spec = op.surface_spec
    if spec is None:
        return project(data)

    surface = project(data, queried_key=spec.queried_key, full=spec.full)

    # --match runs FIRST — it changes the axis/row set (entity → event rows),
    # so every later transform (filter/select/budget/count) operates on the
    # matched event rows.
    if spec.match:
        surface = search(surface, spec.match, vertex_path=op.vertex_path)

    where = dict(spec.where) if spec.where else None
    if spec.key_or or where or spec.observer is not None:
        surface = filter(
            surface,
            key_or=spec.key_or or None,
            where=where,
            observer=spec.observer,
        )
    if spec.fields:
        surface = select(surface, spec.fields)
    if spec.do_count:
        surface = count(surface, by=spec.count_by)
    if spec.limit is not None or spec.last is not None:
        surface = budget(surface, limit=spec.limit, last=spec.last)
    return surface


def _render_foldstate_json(data, reporter: Reporter) -> int:
    """Raw-JSON dump for the legacy / lens-override path.

    The lifted body of the old ``cli/views/fold._render_json``. Used when the
    Surface gate FAILS — a vertex-declared or ``--lens`` override fold lens, or
    a non-FoldState shape (a lens-declared fetch's dict) — so ``--json`` keeps
    emitting the raw fetched shape instead of degrading to a rendered Block.
    The gate-PASS path emits ``to_dict(surface)`` instead (the structured,
    ranked encoding).
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


def _zoom_of(fidelity: "Fidelity | None") -> Zoom:
    """Extract a Zoom enum value from a Fidelity. Defaults to SUMMARY when
    fidelity is None (e.g. action ops carry no fidelity)."""
    if fidelity is None:
        return Zoom.SUMMARY
    return Zoom(fidelity.depth)


# --- Dispatch --------------------------------------------------------------


def dispatch(op: Operation, *, reporter: Reporter) -> int:
    """Execute an Operation and route output through the Reporter.

    Returns the process exit code (0 = success; non-zero = error).
    """
    # ACTION: fn has side effects; result (if any) is either an exit
    # code (legacy cmd_* contract returning 0/1) or a renderable receipt
    # (string/Block to flow through reporter.show). Ints win — keeps
    # cmd_emit/cmd_init/etc. drop-in for the pilot before we move them
    # over to "return receipt object" later.
    if op.is_action:
        result = op.fn(**op.params)
        if isinstance(result, int):
            return result
        if result is not None:
            reporter.show(result)
        return 0

    # INTERACTIVE: hand off to a TUI handler (autoresearch, etc.).
    if op.mode == "interactive":
        if op.interactive_handler is None:
            reporter.err(
                f"Interactive mode requested for {op.verb} but no handler bound."
            )
            return 2
        return op.interactive_handler()

    # LIVE: stream with InPlaceRenderer. Stubbed in Step 0 — exercised
    # when the first view migrates to live mode.
    if op.mode == "live":
        if op.stream_fn is None:
            reporter.err(f"Live mode requested for {op.verb} but no stream_fn bound.")
            return 2
        return _dispatch_live(op, reporter)

    # STATIC: fetch → lens → print_block.
    lens_fn = _resolve_lens(
        op.render_lens or "",
        op.vertex_path,
        lens_override=op.lens_override,
    )
    if lens_fn is None:
        target = op.lens_override or op.render_lens
        reporter.err(f"Lens not found: {target}")
        return 2

    try:
        data = op.fn(**op.params)
    except Exception as exc:
        reporter.err(f"Error: {exc}")
        return 1

    # --- Surface interposition (S2) --------------------------------------
    # Route the DEFAULT fold path through the typed Surface so plain and
    # --json encode the SAME structured rows. Gate: the effective fold lens is
    # the built-in (no --lens override, no vertex lens{} decl) AND the data is
    # a FoldState. Vertex-declared / override lenses (identity, comms, …) and
    # non-FoldState shapes (a lens-declared fetch's dict) keep the raw FoldState
    # — they render their own shape, and any that delegate to the built-in
    # fold_view ride its polymorphic front door (which projects for them).
    from painted.cli import Format

    render_data = data
    gate = _surface_gate(op, data)
    if not gate and _spec_has_dropped_transforms(op.surface_spec):
        # Interim signal (B3): the read grammar is inert on custom-lens /
        # --lens-override vertices — the gate keeps the raw FoldState so the
        # declared lens renders its own shape, discarding the parsed transforms.
        # The real fix is the FF (migrate the salience lenses onto Surface);
        # until then, a stderr note keeps a valid flag from silently no-opping.
        # This note lives ON the gate-fail branch and is removed when the FF
        # routes custom lenses through the Surface (thread:gate-fail-ignores-
        # surface-transforms).
        vtx = op.vertex_path.stem if op.vertex_path else "this vertex"
        reporter.err(
            f"note: read-grammar transforms (--match/--limit/--last/--fields/"
            f"--full/--count/comma-OR --key/field=value) are inert on "
            f"custom-lens vertex '{vtx}' — flags ignored "
            f"(--kind and single --key still apply)."
        )
    if op.format is Format.JSON:
        if gate:
            import json

            from loops.surface import to_dict

            reporter.msg(json.dumps(to_dict(_project_surface(op, data))))
            return 0
        # Override / vertex-decl lens, or a non-FoldState shape (lens-fetch
        # dict) → keep the legacy raw dump instead of degrading to text.
        return _render_foldstate_json(data, reporter)
    if gate:
        render_data = _project_surface(op, data)

    from loops.lens_resolver import call_lens

    # call_lens unpacks Fidelity into the legacy (zoom, **kwargs) shape that
    # existing lenses accept. visible/chars/lines flow as kwargs; the lens
    # decides whether to honor them.
    extra: dict = dict(op.render_context)
    if op.fidelity is not None:
        extra.setdefault("visible", op.fidelity.visible)
        extra.setdefault("chars", op.fidelity.chars)
        extra.setdefault("lines", op.fidelity.lines)
    if op.vertex_path is not None:
        # Vertex name + path are useful for many lenses for headers / refs.
        from loops.commands.resolve import _vertex_name

        extra.setdefault("vertex_name", _vertex_name(op.vertex_path))
        extra.setdefault("vertex_path", str(op.vertex_path))

    try:
        # Human reads show everything: the truncation budget is dropped on the
        # read render (decision:design/drop-truncation-from-human-reads). A TTY
        # read now renders full bodies + all fields like the pipe (width=None =
        # no-truncation, per normalize_width's contract), just with color. A
        # width-fit/truncate render can return later as an opt-in, not the
        # default. (Live keeps its width — the alt-screen needs it.)
        block = call_lens(
            lens_fn, render_data, _zoom_of(op.fidelity), None, **extra
        )
    except Exception as exc:
        reporter.err(f"Render error: {exc}")
        return 2
    if not isinstance(block, Block):
        # Lens may return None when there's nothing to render.
        return 0
    reporter.print_block(block)
    return 0


def _dispatch_live(op: Operation, reporter: Reporter) -> int:
    """Live-mode delegate — folds onto painted's ``run_cli`` surface tier.

    The live render loop, alt-screen ``surface`` delivery (tear-free,
    absolute per-cell diff), terminal setup/restore, and final-frame
    deposit are all painted's now: ``run_cli(fetch_stream=,
    live_delivery="surface")``. loops contributes only the resolved lens
    and the async stream closure. This replaced the hand-rolled
    ``cli/live.py`` ``InPlaceRenderer`` wrapper.

    Caller (dispatch) guarantees ``op.stream_fn is not None`` before
    reaching here; the assertion narrows for the type-checker.
    """
    assert op.stream_fn is not None, "dispatch() must verify stream_fn before calling _dispatch_live"
    lens_fn = _resolve_lens(
        op.render_lens or "",
        op.vertex_path,
        lens_override=op.lens_override,
    )
    if lens_fn is None:
        target = op.lens_override or op.render_lens
        reporter.err(f"Lens not found: {target}")
        return 2

    from painted import run_cli

    from loops.lens_resolver import call_lens, normalize_width

    # Fidelity was already resolved upstream in the view (domain visibility,
    # zoom, refs context). Capture it into the per-frame closure; run_cli
    # receives only ``--live``, so its own fidelity parse is a deliberate
    # no-op — the render contract is driven by what we captured, not by
    # re-parsing flags painted's argparse never saw (--kind/--facts/--refs…).
    zoom = _zoom_of(op.fidelity)
    extra = dict(op.render_context)
    if op.fidelity is not None:
        extra.setdefault("visible", op.fidelity.visible)
        extra.setdefault("chars", op.fidelity.chars)
        extra.setdefault("lines", op.fidelity.lines)
    if op.vertex_path is not None:
        from loops.commands.resolve import _vertex_name

        extra.setdefault("vertex_name", _vertex_name(op.vertex_path))
        extra.setdefault("vertex_path", str(op.vertex_path))

    def render(ctx, data):
        # painted's render contract: (CliContext, data) -> Block. Width is
        # the terminal width on a TTY, None when piped (no-truncation).
        width = normalize_width(ctx.width if ctx.is_tty else None)
        return call_lens(lens_fn, data, zoom, width, **extra)

    def fetch():
        # run_cli requires a static fetch; the live+stream path renders
        # frames from fetch_stream and deposits the stream's last frame, so
        # this is only a fallback. Reuse the op's one-shot fetch.
        return op.fn(**op.params)

    return run_cli(
        ["--live"],
        fetch=fetch,
        render=render,
        fetch_stream=op.stream_fn,
        live_delivery="surface",
        prog=f"loops {op.verb}",
    )
