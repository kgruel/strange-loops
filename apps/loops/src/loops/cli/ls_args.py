"""Render-free declaration of the top-level ``ls`` command's argparse arguments.

Mirrors ``cli/read_args.py`` (see that module's header for the pattern this
copies): the single source painted's ``run_app`` walks for ``ls``'s
intercepted ``-h`` and for shell ``<TAB>`` completion. It is NOT the parser
that actually runs — that stays ``commands.ls._run_ls`` (per-vertex) and
``commands.population._run_ls_root`` (no vertex), reached through
``cli/views/population.py``.

Grammar mirrored (``commands/ls.py`` module docstring + ``_run_ls_root``):

  loops ls                              root listing
  loops ls --all / -a                   expand the config layer
  loops ls -1                           terse, names-only
  loops ls <vertex>                     unified declarations for one vertex
  loops ls <vertex> --kind [NAME]       KINDS listing, or descend into NAME
  loops ls <vertex> --observer [NAME]   OBSERVERS section
  loops ls <vertex> --combine [PATH]    COMBINE section
  loops ls <vertex> --row [TEMPLATE]    SOURCES section

Two things NOT mirrored, deliberately out of scope for this slice:

- The positional-alias back-compat form (``loops ls <vertex> kind`` without
  the ``--``) — the flag form above is canonical (``commands/ls.py``'s own
  module docstring says so); the alias would need a second bareword
  positional this slice doesn't add.
- ``--key`` (drilling one namespace inside a ``--kind NAME`` descent) — this
  slice wires vertex-name completion and ``--kind`` only, per scope.
"""
from __future__ import annotations

import argparse

from painted.cli import complete_via

from .completers import complete_ls_kind, complete_ls_vertex


def add_ls_args(parser: argparse.ArgumentParser) -> None:
    """Declare the ls DOMAIN arguments on ``parser`` and attach completers.

    ``vertex`` carries a domain completer (every resolvable vertex name,
    ls-scoped — see ``complete_ls_vertex``); ``--kind`` carries one too (the
    declared kinds of the vertex on the line, ls-scoped — see
    ``complete_ls_kind``). The remaining declaration-narrowing flags
    (``--observer``/``--combine``/``--row``) and the root-listing flags
    (``--all``/``-1``) are declared for -h honesty (so a real, still-legal
    flag isn't hidden from the intercepted help) but carry no completer —
    out of scope for this slice.
    """
    complete_via(
        parser.add_argument(
            "vertex", nargs="?", default=None,
            help="Vertex name (omit for root listing); accepts vertex/qualifier",
        ),
        complete_ls_vertex,
    )
    parser.add_argument(
        "--all", "-a", dest="all_", action="store_true", default=False,
        help="Expand the config layer (root listing only)",
    )
    parser.add_argument(
        "-1", dest="terse", action="store_true", default=False,
        help="Terse, names-only root listing",
    )
    complete_via(
        parser.add_argument(
            "--kind", nargs="?", const=True, default=None,
            help="Show the KINDS listing, or descend into one kind's entries",
        ),
        complete_ls_kind,
    )
    parser.add_argument(
        "--observer", nargs="?", const=True, default=None,
        help="Show OBSERVERS section (or one named entry)",
    )
    parser.add_argument(
        "--combine", nargs="?", const=True, default=None,
        help="Show COMBINE section (or one named entry)",
    )
    parser.add_argument(
        "--row", nargs="?", const=True, default=None,
        help="Show SOURCES section (or one named template)",
    )
