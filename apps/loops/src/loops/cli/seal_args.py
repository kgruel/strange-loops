"""Render-free declaration of the ``seal`` verb's argparse arguments.

Single source for seal's own parser (Pattern A, mirrors ``cli/read_args.py``
and ``cli/cite_args.py``) — ``cli/views/seal.py`` calls ``add_seal_args``
directly to build its runtime parser; painted's intercepted ``-h`` and
shell-completion walk hang off the same declaration via ``cli/app.py``'s
``_add_args_for``.

``include_vertex`` mirrors seal's own conditional: the ``vertex``
positional is only declared when ``ctx.vertex_path`` hasn't already been
resolved (verb-first dispatch; vertex-first dispatch pre-supplies it).
painted's completion/-h walk has no ``ctx`` at declaration time, so it
always builds the verb-first shape (``include_vertex=True``) — the same
convention ``read_args``/``emit_args`` use for their unconditional
``tokens`` bucket.

Not quite pure Pattern A: seal's own ``-q``/``--quiet`` ("suppress the
receipt line") collides with painted's framework zoom ``-q`` (the same
collision ``emit_args.py`` documents for emit's domain ``-q``) — painted's
``build_parser`` (the parser this seam is walked through) already adds
the framework zoom/format block itself, so declaring a second ``-q``
here would raise ``ArgumentError: conflicting option strings``. This
module omits it; ``cli/views/seal.py``'s own bare ``ArgumentParser`` (no
framework block) adds it separately, right after calling
``add_seal_args``.
"""
from __future__ import annotations

import argparse

from painted.cli import complete_via

from .completers import complete_vertex


def add_seal_args(
    parser: argparse.ArgumentParser, *, include_vertex: bool = True
) -> None:
    """Declare seal's DOMAIN arguments on ``parser`` and attach completers."""
    if include_vertex:
        # Seal resolves the vertex through the DISPATCH resolver (slashed
        # names legal), matching emit's runtime — not read's entity
        # classification — so this reuses ``complete_vertex`` (not
        # ``complete_read_vertex``).
        complete_via(
            parser.add_argument(
                "vertex", nargs="?", default=None,
                help="Vertex name or .vertex path (auto-resolves local vertex)",
            ),
            complete_vertex,
        )
    parser.add_argument(
        "-m", "--message", default=None,
        help="Why this boundary is being drawn — sealed inside its own window",
    )
    parser.add_argument(
        "--observer", default=None,
        help="Observer string (defaults to .vertex declaration / $LOOPS_OBSERVER)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the seal fact JSON without storing",
    )
    # -q/--quiet intentionally NOT declared here — see module docstring.
