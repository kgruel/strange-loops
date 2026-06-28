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
    "trace": "trace_view",
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

    from loops.lens_resolver import call_lens, normalize_width

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
        block = call_lens(
            lens_fn, data, _zoom_of(op.fidelity), normalize_width(reporter.width), **extra
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
    # zoom, --diff context). Capture it into the per-frame closure; run_cli
    # receives only ``--live``, so its own fidelity parse is a deliberate
    # no-op — the render contract is driven by what we captured, not by
    # re-parsing flags painted's argparse never saw (--kind/--facts/--diff…).
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
