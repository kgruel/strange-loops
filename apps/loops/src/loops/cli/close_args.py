"""Render-free declaration of the ``close`` verb's argparse arguments.

Single source for close's own parser (Pattern A) — ``commands/emit.py``'s
``_run_close`` calls ``add_close_args`` to build its runtime parser;
painted's intercepted ``-h`` and shell-completion walk hang off the same
declaration via ``cli/app.py``'s ``_add_args_for``.

``close`` is still a legacy shim (``registry.py``:
``_legacy_view("_run_close")``) — this extraction only lifts the ARGPARSE
DECLARATION into the render-free seam; the parse/dispatch/positional-shift
logic in ``_run_close`` (the vertex-vs-kind reinterpretation when the
first positional doesn't resolve) is untouched — grammar-mirror, not a
dispatch change.

``include_vertex`` mirrors the same conditional ``read_args``/
``seal_args`` use — painted's completion/-h walk has no ``ctx`` at
declaration time, so it always builds the verb-first shape
(``include_vertex=True``).
"""
from __future__ import annotations

import argparse

from painted.cli import complete_via

from .completers import complete_vertex


def add_close_args(
    parser: argparse.ArgumentParser, *, include_vertex: bool = True
) -> None:
    """Declare close's DOMAIN arguments on ``parser`` and attach completers.

    Only the leading ``vertex`` slot carries a completer in this slice —
    ``kind``/``name`` completion (scoped to the resolved vertex's declared
    kinds / open fold items) is out of scope, deferred.
    """
    if include_vertex:
        complete_via(
            parser.add_argument("vertex", nargs="?", default=None),
            complete_vertex,
        )
    parser.add_argument("kind", help="Fact kind to close (e.g. thread, task)")
    parser.add_argument("name", help="Name/key of the item to close")
    parser.add_argument(
        "message", nargs="?", default=None, help="Resolution summary",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would happen",
    )
