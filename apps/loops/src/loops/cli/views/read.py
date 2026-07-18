"""cli.views.read — the read router.

The ``read`` verb is the user-facing umbrella over four progressively
specialised display verbs:

  default (no special flag)  → fold (current state)
  --ticks                    → ticks (drill-down or list)
  --facts + --since|--as-of|--id → stream (temporal query)
  (otherwise) --facts        → fold with the facts visibility layer

``--as-of`` (SPEC §9.3, equal-cursors) rewinds both the fact window and the
ontology to a historical anchor; combined with ``--facts`` it routes to
stream exactly as ``--since`` does (unchanged, shipped behavior).

On the FOLD route (no ``--facts``/``--ticks``), temporal flags are honored
directly by the fold view (0.8.0 temporal-cursor, A11): ``--at`` (a
witness-cursor address — head/fact:/seq:/tick:/ISO), ``--as-of`` (the
explicit event-time projection, mutually exclusive with ``--at``), and
``--diff`` (a structural fold diff between two addresses, C2). ``--since``
and ``--id`` have no fold-route meaning and stay refused, teaching the
cursor flags plus the existing --facts/--ticks routes.

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
    pre.add_argument("--at", default=None)
    pre.add_argument("--diff", default=None)
    known, rest = pre.parse_known_args(argv)

    # --at/--diff are fold-route-only concerns (A9/A11). Resolve their
    # incompatibility with every route that would otherwise consume argv
    # BEFORE any route is selected — the stream branch immediately below
    # used to run first and silently swallow --at/--diff whenever --facts
    # combined with --since/--as-of/--id (or --ticks) triggered it, so
    # e.g. `--facts --at head --as-of 30d` ran the event-time stream query
    # with --at discarded, never refused (review finding 1). A bare
    # `--facts --at ADDRESS` (no since/as-of/id) is unaffected — that
    # legitimately falls through to the fold route below, unchanged.
    routes_away_from_fold = (
        known.facts and (known.since or known.as_of or known.fact_id)
    ) or known.ticks
    if routes_away_from_fold and (known.at or known.diff):
        if known.ticks:
            reason = "`--ticks` does not support cursor addressing yet"
        else:
            reason = (
                "`--facts` with a temporal window/anchor routes to the "
                "event-history view, not the fold read"
            )
        ctx.reporter.err(f"read: --at/--diff address the fold route only — {reason}.")
        return 2

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
    # ignored the user's cursor (closing review #7). --at/--diff incompatibility
    # with --ticks is already refused above.
    if known.ticks:
        ticks_rest = list(rest)
        if known.since:
            ticks_rest += ["--since", known.since]
        if known.as_of:
            ticks_rest += ["--as-of", known.as_of]
        from . import ticks as ticks_view

        return ticks_view.run(ticks_rest, ctx)

    # --since / --id have no fold-route meaning: the folded read cannot
    # honor a window bound or a single-fact address, and silently dropping
    # a cursor renders head state as if it were T — a silent anachronism
    # (SPEC §9.3's honesty posture: rewound reads must never silently lie).
    dropped = [
        flag
        for flag, value in (
            ("--since", known.since),
            ("--id", known.fact_id),
        )
        if value
    ]
    if dropped:
        flags = ", ".join(dropped)
        ctx.reporter.err(
            f"read: {flags} needs a temporal view — the folded read"
            " cannot honor it.\n"
            "  event history:  read <vertex> --facts --since/--as-of/--id …\n"
            "  tick windows:   read <vertex> --ticks --since/--as-of …\n"
            "  witness cursor: read <vertex> --at <address>      (head / "
            "fact:ID / seq:N / tick:ID / ISO date)\n"
            "  event-time:     read <vertex> --as-of <ts>        "
            "(explicit retrospective projection)"
        )
        return 2

    if known.at and known.as_of:
        ctx.reporter.err(
            "read: --at and --as-of are mutually exclusive — a read is "
            "either witness-cursor'd (--at) or event-time-projected "
            "(--as-of), never both (A8)."
        )
        return 2

    # Default → fold. Re-inject --facts/--at/--as-of/--diff so fold's own
    # parser sees them (routing flags here, domain flags there).
    fold_rest = list(rest)
    if known.facts:
        fold_rest.append("--facts")
    if known.at:
        fold_rest += ["--at", known.at]
    if known.as_of:
        fold_rest += ["--as-of", known.as_of]
    if known.diff:
        fold_rest += ["--diff", known.diff]
    from . import fold as fold_view

    return fold_view.run(fold_rest, ctx)
