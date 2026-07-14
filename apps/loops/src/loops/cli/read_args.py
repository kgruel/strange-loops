"""Render-free declaration of the ``read`` verb's argparse arguments.

The single source for the read/fold parser. Three consumers read it:

- ``cli/views/fold.py`` builds its parser from ``add_read_args`` and runs it
  (the parse reflection);
- painted's ``run_app`` hangs the ``read`` command's intercepted ``-h`` off it
  (the help reflection);
- painted's shell completion walks it for ``<TAB>`` candidates (the completion
  reflection) — and it is the site where loops domain completers attach to
  individual actions via ``complete_via``.

Kept import-light on purpose — ``argparse`` plus the render-free
``painted.cli`` completion seam plus loops' own render-free completers — so it
can be introspected on the no-renderer-on-TAB path (``_build_commands`` in
``cli/app.py`` references it while building the roster, which runs on every
invocation, completion included). Importing the fold view instead would drag
``dispatch`` → ``output`` → the renderer onto that path.

**Attaching a new completer (the pattern the follow-up slices copy):** add the
callable to ``cli/completers.py``, then wrap its argument here in
``complete_via`` — one line, at the ``add_argument`` that declares the flag::

    complete_via(parser.add_argument("--kind", ...), complete_kind)

That is the whole seam: a completer file + one wrapped declaration.
"""
from __future__ import annotations

import argparse

from painted.cli import complete_via

from .completers import complete_lens, complete_vertex


def add_read_args(parser: argparse.ArgumentParser) -> None:
    """Declare the read/fold DOMAIN arguments on ``parser`` and attach completers.

    Domain args only — the loops-specific selectors and read-grammar transforms.
    The framework flags (``-q``/``-v``, ``-i``/``--static``/``--live``,
    ``--json``/``--plain``) are NOT declared here: painted owns them, and
    ``build_parser`` (the parser the intercepted ``-h`` and completion walk)
    adds them itself via ``add_cli_args``. Registering them here too would
    collide there. The fold view's handler parser bypasses ``build_parser``, so
    it adds the framework block itself around this call (see ``_build_parser``).

    A single ``tokens`` bucket (``nargs='*'``) absorbs the vertex/entity
    positionals AND intermixed ``field=value`` predicates;
    ``parse_intermixed_args`` + ``_classify_tokens`` (in the fold view) do the
    disambiguation. Pure parser builder: it only calls ``add_argument`` (and
    ``complete_via``, which sets the ``.completer`` attribute and returns the
    action) — never acts on the args, so it is safe to introspect for ``-h``
    and completion without running the command.
    """
    # ``tokens`` carries a domain completer too: the leading slot is the
    # vertex name (every candidate ``resolve_vertex``/dispatch would accept);
    # once that slot is filled, ``complete_vertex`` defers with ``[]`` — later
    # slots (kind/key, ``field=value``) aren't this slice's scope.
    complete_via(
        parser.add_argument(
            "tokens", nargs="*", default=[],
            help="[vertex] [kind/key] [field=value ...]",
        ),
        complete_vertex,
    )
    # Domain selectors — change WHAT is fetched (folded state vs raw facts).
    parser.add_argument("--kind", default=None, help="Filter by fact kind")
    parser.add_argument(
        "--key", default=None,
        help="Filter by fold key (prefix; comma-OR for multiple)",
    )
    # --lens carries a domain completer: every resolvable lens (built-in +
    # custom, scoped to the vertex on the line) as a described row.
    complete_via(
        parser.add_argument(
            "--lens", default=None, help="Lens name for rendering"
        ),
        complete_lens,
    )
    parser.add_argument(
        "--facts", action="store_true", default=False,
        help="Show raw fact stream instead of folded state",
    )
    parser.add_argument(
        "--why", action="store_true", default=False,
        help="Per-field provenance drill for one exact kind/key address",
    )
    parser.add_argument(
        "--match", "--grep", default=None, metavar="QUERY", dest="match",
        help="Content search — FTS5 for indexed kinds, substring for the rest",
    )
    # Read-grammar transforms (S4) — applied over the projected Surface, so
    # plain and --json carry the same transformed rows.
    parser.add_argument(
        "--full", action="store_true", default=False,
        help="Force full-body (whole) granularity on every row",
    )
    parser.add_argument(
        "--fields", default=None,
        help="Comma-separated payload fields to project (narrow each row)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Keep the top-N rows by salience",
    )
    parser.add_argument(
        "--last", type=int, default=None,
        help="Keep the newest-N rows by timestamp",
    )
    parser.add_argument(
        "--count", action="store_true", default=False,
        help="Aggregate rows into counts (with --by, one row per group)",
    )
    parser.add_argument(
        "--by", default=None,
        help="Group --count by a row attribute / payload field",
    )
