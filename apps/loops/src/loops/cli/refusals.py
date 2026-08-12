"""cli.refusals — shared refusal-sentence builders.

The cli-honesty-wave refuses flags rather than silently dropping them
(honor-or-refuse). Four sites refuse an explicit ``--status`` for the same
reason — the route in play never applies the status filter — and their
hand-rolled copies drifted within one wave (simplify pass, item 1). One
builder owns the sentence; call sites supply the two varying nouns.

Deliberately NOT here: dispatch's statusless-kinds refusal — that is a
different genus (an unanswerable query, not route-inertness) and keeps its
own wording.
"""
from __future__ import annotations


def status_inert_refusal(context: str, drop_flag: str) -> str:
    """The ``--status``-is-inert-here refusal sentence.

    ``context`` names what the active route does instead of applying the
    filter (e.g. ``"--why owns its own fetch"``); ``drop_flag`` is the other
    thing the user can drop to resolve the conflict.
    """
    return (
        f"read --status: {context} and does not apply the status filter — "
        f"drop --status, or drop {drop_flag}."
    )
