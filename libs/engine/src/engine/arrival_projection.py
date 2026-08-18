"""arrival_projection — the two projections of an arrival log, re-derived.

Cut B of the arrival substrate (decision:design/arrival-sliceB-projections):
an arrival-canonical store has exactly two projections — the sqlite index at
the sibling ``.db`` and the derived ``.jsonl`` log beside it. Both are
functions of the arrival log, both are rebuildable at will, and neither is
ever written by anything that is not deriving it.

Why a module and not a store method
-----------------------------------
The states re-derivation resolves are exactly the states
:class:`~engine.arrival_store.ArrivalStore` refuses to open on: catch-up runs
inside the constructor, so a method on the class would be unreachable on the
very stores that need it. Making the constructor tolerate the refusal would
mean a store that opens in a broken state, which is what the consume-or-refuse
posture forbids. The precedent is :mod:`engine.canonical_audit`'s "pure
reader, by contract" — the module that must not repair never constructs the
store that does. Here it is the inverse and the same rule: the module that
repairs never constructs the store that refuses.

The second consequence is the reason it is worth a module: **no write path
can call re-derivation as a side effect.** It is not on the object the write
path holds.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    "has_rows",
]


def has_rows(conn: sqlite3.Connection) -> bool:
    """Does this index carry any fact or tick row?

    The one spelling for both log-canonical stores. It is the predicate that
    separates "an absent projection, which builds automatically because
    building it destroys nothing" from "an existing projection carrying
    state, whose re-derivation is an operator's decision" — so the two
    stores asking it differently would be two answers to the question this
    cut is about.
    """
    for table in ("facts", "ticks"):
        if conn.execute(f"SELECT EXISTS(SELECT 1 FROM {table})").fetchone()[0]:
            return True
    return False
