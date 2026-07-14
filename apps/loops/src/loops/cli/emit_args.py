"""Render-free declaration of the ``emit`` verb's argparse arguments.

Mirrors ``cli/read_args.py`` (see that module's header for the pattern this
copies): the single source painted's ``run_app`` walks for ``emit``'s
intercepted ``-h`` and for shell ``<TAB>`` completion. It is NOT the parser
that actually runs on ``loops emit ...`` — that stays
``commands.emit._build_emit_parser``, shared by ``cli/views/emit.py`` and the
legacy ``_run_emit``. This module only has to describe the same DOMAIN grammar
closely enough for help/completion to reflect it honestly.

Domain args only — ``-q``/``-v``/``--json`` are NOT declared here even though
``_build_emit_parser`` declares them for the real parse: painted's
``build_parser`` (the parser this seam is walked through) adds the framework
zoom/format block itself, and declaring them here too would collide (the exact
``-q`` collision S1 hit and documented in ``read_args.py``).

Attaching a completer follows the same one-line seam as ``read_args.py``:
wrap the ``add_argument`` call in ``complete_via``.
"""
from __future__ import annotations

import argparse

from painted.cli import complete_via

from .completers import complete_emit_tokens


def add_emit_args(parser: argparse.ArgumentParser) -> None:
    """Declare the emit DOMAIN arguments on ``parser`` and attach completers.

    A single ``tokens`` bucket (``nargs='*'``) carries ``[vertex] kind
    [KEY=VALUE ...]`` — ``_classify_emit_positionals`` (in
    ``commands/emit.py``) does the disambiguation at real-parse time; this
    declaration only needs to expose the shape for help/completion.
    """
    # ``tokens`` carries a domain completer scoped by position:
    # ``complete_emit_tokens`` offers vertex names for the first (empty)
    # slot and kind names (scoped to that vertex) for the second — see its
    # docstring in ``completers.py``. Payload ``field=value`` parts are out
    # of scope for this slice.
    complete_via(
        parser.add_argument(
            "tokens", nargs="*", default=[],
            help="[vertex] <kind> [KEY=VALUE ... | message text]",
        ),
        complete_emit_tokens,
    )
    parser.add_argument(
        "--observer",
        default=None,
        help="Observer string (default: from .vertex declaration or $LOOPS_OBSERVER)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the fact JSON without storing",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Refuse on validation failures (unknown kind, missing fold-key, "
            "unresolved ref, undeclared observer). Overridden by vertex "
            "'strict true' declaration (which always refuses)."
        ),
    )
    parser.add_argument(
        "--declare-observer",
        action="store_true",
        help=(
            "When the observer is undeclared, print the observers{} KDL snippet "
            "and its location (PRINT-not-write — loops never edits the .vertex)."
        ),
    )
    parser.add_argument(
        "--stdin",
        metavar="FIELD",
        default=None,
        help=(
            "Read sys.stdin into the named payload field (e.g. --stdin message). "
            "Sidesteps shell-quoting friction for natural-voice prose. "
            "Errors if stdin is a TTY. Single trailing newline stripped."
        ),
    )
    parser.add_argument(
        "--file",
        action="append",
        metavar="FIELD=PATH",
        default=None,
        help=(
            "Read file contents into the named payload field (e.g. --file message=notes.md). "
            "May repeat for different fields. Tilde expansion supported. "
            "Single trailing newline stripped."
        ),
    )
