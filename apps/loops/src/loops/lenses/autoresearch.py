"""autoresearch lens — sentinel + non-interactive renderer.

The ``--lens autoresearch`` flag has dual semantics:
- INTERACTIVE mode (TUI): main.py special-cases ``known.lens == "autoresearch"``
  to install AutoresearchApp as the interactive handler (see main.py:574).
- Non-interactive (--static/--plain): falls through to standard fold rendering.

This module makes the non-interactive path explicit. Without it, ``--lens
autoresearch --plain`` would silently fall back to the default fold view via
the lens-not-found path — and after the lens-resolution-strict fix
(_exit_lens_not_found), that fallback became a hard error. Re-exporting the
default fold_view here preserves the dual-semantic behavior cleanly: the
sentinel is also a real lens module, and the test that exercises ``--lens
autoresearch --plain`` keeps passing because resolution succeeds.
"""
from __future__ import annotations

from .fold import fold_view

__all__ = ["fold_view"]
