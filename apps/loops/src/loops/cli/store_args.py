"""Render-free declaration of the ``store`` verb's argparse arguments.

Mirrors ``cli/read_args.py`` (see that module's header for the pattern this
copies): the single source painted's ``run_app`` walks for ``store``'s
intercepted ``-h`` and for shell ``<TAB>`` completion. It is NOT the parser
that actually runs on ``loops store ...`` — that stays
``commands.store._run_store`` and its seven per-subcommand parsers
(``_run_verify``/``_run_rebirth``/``_run_reanchor``/``_run_absorb``/
``_run_adopt``/``_run_store_ticks``/``_run_store_stats``, each its own
``argparse.ArgumentParser``).

**Subparsers are not walkable here — verified empirically.** painted's parser
walk (``painted.cli._argwalk.walk_args``) reads ``parser._actions`` flat; it
has no ``argparse._SubParsersAction`` handling, so there is no way to scope a
flag's completion/``-h`` visibility to "only when subcommand X is chosen."
Declaring every subcommand's flags (``--json``, ``--chain``, ``--rule``, ...)
on one flat parser would offer e.g. ``--rule`` while completing
``store verify ...``, which verify's real parser rejects — a completion
dishonesty the flat walk can't structurally prevent.

Given that, this module takes the documented fallback: complete the seven
subcommand names as static ``choices`` on the first positional, and stop
there. Per-subcommand flags and the ``rebirth``-only second positional
(``target``) are out of scope for this slice.

The second positional (``file``) is deliberately left WITHOUT a completer —
every subcommand's own first positional is a store/vertex target, an
unenumerable open value. painted has no built-in files-completer to attach
here (checked: ``painted.cli`` exposes no such helper), and a value completer
on this slot would suppress the shell's native path completion
(``wants_file_completion`` requires ``choices`` AND ``completer`` both
absent) — so leaving it undeclared-completer is the honest choice: the shell
fills it with real filesystem paths.
"""
from __future__ import annotations

import argparse

# The subcommand names `_run_store` dispatches on, in commands/store.py's
# own if/elif order — a parity test (test_store_completion.py) holds this
# tuple against that dispatcher so a new subcommand doesn't silently go
# uncompleted.
STORE_SUBCOMMANDS = (
    "verify", "rebirth", "reanchor", "absorb", "adopt", "ticks", "stats",
)


def add_store_args(parser: argparse.ArgumentParser) -> None:
    """Declare the store DOMAIN arguments on ``parser`` for -h/completion.

    Two positionals only — see module docstring for why flags stop here.
    """
    parser.add_argument(
        "subcommand", nargs="?", default=None, choices=STORE_SUBCOMMANDS,
        help="verify | rebirth | reanchor | absorb | adopt | ticks | stats "
             "(omit for the base inspect view)",
    )
    parser.add_argument(
        "file", nargs="?", default=None,
        help="Store .db or .vertex file, or vertex name",
    )
