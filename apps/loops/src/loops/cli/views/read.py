"""cli.views.read — the read router.

The ``read`` verb is the user-facing umbrella over four progressively
specialised display verbs:

  default (no special flag)  → fold (current state)
  --ticks                    → ticks (drill-down or list)
  --facts + --since|--as-of|--id → stream (temporal query)
  (otherwise) --facts        → fold with the facts visibility layer

``--as-of`` (SPEC §9.3, equal-cursors) rewinds both the fact window and the
ontology to a historical anchor; it routes to stream exactly as ``--since``
does.

This router does the minimum disambiguation — pre-parses the routing
flags, picks a delegate, and forwards the remaining argv. The heavy
lifting (argparse → Operation → dispatch) lives in each delegate
view.
"""
from __future__ import annotations

import argparse

from ..invocation import Invocation


def run(argv: list[str], ctx: Invocation) -> int:
    """Pre-parse routing flags, delegate to fold / stream / ticks."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--facts", action="store_true", default=False)
    pre.add_argument("--ticks", action="store_true", default=False)
    pre.add_argument("--since", default=None)
    pre.add_argument("--as-of", default=None, dest="as_of")
    pre.add_argument("--id", default=None, dest="fact_id")
    known, rest = pre.parse_known_args(argv)

    # Temporal facts query → stream (re-injects --since / --as-of / --id).
    if known.facts and (known.since or known.as_of or known.fact_id):
        stream_rest = list(rest)
        if known.since:
            stream_rest += ["--since", known.since]
        if known.as_of:
            stream_rest += ["--as-of", known.as_of]
        if known.fact_id:
            stream_rest += ["--id", known.fact_id]
        from . import stream as stream_view

        return stream_view.run(stream_rest, ctx)

    # --ticks → ticks (dedicated drill-down + lens). Re-inject the temporal
    # flags the pre-parser consumed — the ticks command owns --since/--as-of
    # semantics (window bound + ontology cursor); dropping them here silently
    # ignored the user's cursor (closing review #7).
    if known.ticks:
        ticks_rest = list(rest)
        if known.since:
            ticks_rest += ["--since", known.since]
        if known.as_of:
            ticks_rest += ["--as-of", known.as_of]
        from . import ticks as ticks_view

        return ticks_view.run(ticks_rest, ctx)

    # Default → fold. Re-inject --facts so fold's parser sees it
    # (it's a visibility layer, not a routing flag).
    fold_rest = [*rest, "--facts"] if known.facts else rest
    from . import fold as fold_view

    return fold_view.run(fold_rest, ctx)
