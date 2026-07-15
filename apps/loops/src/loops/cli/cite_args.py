"""Render-free declaration of the ``cite`` verb's argparse arguments.

Single source for cite's own parser — ``cli/views/cite.py`` calls
``add_cite_args`` directly to build its runtime parser (Pattern A, the
same seam ``cli/read_args.py`` establishes for read/fold: the walk IS the
runtime declaration, so there is no separate grammar to keep honest
against a parity test). Painted's ``run_app`` hangs cite's intercepted
``-h`` off this module too, and its shell-completion walk reads it for
``<TAB>`` candidates.

Cite never takes a vertex positional — verb-first resolves the local
vertex, and vertex-first dispatch pre-supplies ``ctx.vertex_path`` — so
there is no vertex slot to hang ``complete_vertex`` on in this slice.
Refs (``kind:key`` addresses) get no completer here either — a genuine
design question, deferred.
"""
from __future__ import annotations

import argparse


def add_cite_args(parser: argparse.ArgumentParser) -> None:
    """Declare cite's DOMAIN arguments on ``parser``.

    Pure parser builder — only calls ``add_argument``, never acts on the
    args — so it is safe both as the real runtime parser and for ``-h``/
    completion introspection.
    """
    parser.add_argument(
        "refs", nargs="+",
        help="kind/key refs or bare ULIDs — the attention targets",
    )
    parser.add_argument(
        "--context", default=None,
        help="Optional thread or task name to tag the citation",
    )
    parser.add_argument(
        "-m", "--message", default=None,
        help="Optional in-the-moment context for the citation",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the fact JSON without storing",
    )
