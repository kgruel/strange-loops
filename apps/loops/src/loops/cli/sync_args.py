"""Render-free declaration of the ``sync`` verb's argparse arguments.

Single source for sync's own parser (Pattern A) — ``commands/sync.py``'s
``_run_sync`` calls ``add_sync_args`` for both its hand-rolled ``-h``
intercept (needed because the vertex-resolution pre-parse can raise
before argparse's own ``-h`` handling would fire) and its
``parse_known_args`` pre-parser; painted's intercepted ``-h`` and
shell-completion walk hang off the same declaration via ``cli/app.py``'s
``_add_args_for``.

``sync`` is still a legacy shim — this extraction only lifts the ARGPARSE
DECLARATION into the render-free seam; sync's own pre-parse and the
``run_cli``-delegated remainder are untouched.

``include_vertex`` mirrors the same conditional ``read_args``/
``seal_args``/``close_args`` use — painted's completion/-h walk has no
``ctx`` at declaration time, so it always builds the verb-first shape
(``include_vertex=True``).
"""
from __future__ import annotations

import argparse

from painted.cli import complete_via

from .completers import complete_vertex


def add_sync_args(
    parser: argparse.ArgumentParser, *, include_vertex: bool = True
) -> None:
    """Declare sync's DOMAIN arguments on ``parser`` and attach completers."""
    if include_vertex:
        complete_via(
            parser.add_argument("vertex", nargs="?", help="Vertex name or path"),
            complete_vertex,
        )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="Run all sources unconditionally",
    )
    parser.add_argument(
        "--var", action="append", default=[], metavar="KEY=VALUE",
        help="Variable override",
    )
