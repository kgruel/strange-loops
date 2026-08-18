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

What survives a re-derivation
-----------------------------
``facts`` and ``ticks`` are cleared and rebuilt from ordinal 0 forward —
never partially, because reproducing the original rowids is what keeps
outstanding witness positions and seals valid, and that only holds for a
replay from empty. The FTS tables are DROPPED for the reason
:meth:`engine.jsonl_store.JsonlStore._rebuild` drops them: ``DELETE FROM
facts`` resets sqlite's rowid counter, so a surviving FTS index would resolve
stale text to new facts. Search then reports ``missing``, the honest "run
reindex" state. Every ``store_meta`` row survives except the two this module
owns as projections — the resume mark and ``own_lineage``, both restamped
from the log.

Locking
-------
Re-derivation takes **the sqlite write lock only** (``BEGIN IMMEDIATE`` for
the whole clear-and-replay), and never the arrival append lock. Taking the
sqlite lock serializes it against every ``ArrivalStore._write``, so no
appender can interleave an index write into a half-replayed index. NOT
taking the append lock means an appender may land a record mid-walk; that is
harmless, because the walk stops at the last complete record and the stamped
mark names what was actually consumed. The result is the ordinary "index
behind the log" state, which the next catch-up tails forward. Holding the
append lock for an O(n) replay would block every writer in the system to buy
a property the mark already provides.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from .arrival import GENESIS_KIND, KEY_INTRODUCTION_KIND, ArrivalLog, ResumeMark
from .jsonl_codec import records_from_object
from .residence import index_path_for
from .sqlite_store import (
    _SCHEMA_STMTS,
    FACT_INSERT_SQL,
    TICK_INSERT_SQL,
)

__all__ = [
    "Rederivation",
    "has_rows",
    "rederive_projections",
    "rows_of_record",
]

# Record classes that expand to index rows, and the structural kinds that
# expand to none. Anything else refuses: a kind this indexer does not know is
# not a kind it may silently drop. The row-class literals mirror the line
# codec's "t" discriminators; the structural kinds are the grammar's own
# constants.
_ROW_KINDS = frozenset(("fact", "tick", "batch"))
_STRUCTURAL_KINDS = frozenset((GENESIS_KIND, KEY_INTRODUCTION_KIND))

_OWN_LINEAGE_KEY = "own_lineage"


def _unsupported(message: str) -> NoReturn:
    """Refuse in the arrival store's refusal family.

    Imported inside the function on purpose: :mod:`engine.arrival_store`
    sits ABOVE this module (it reaches :func:`has_rows` through
    :mod:`engine.jsonl_store`), so naming the exception at module level
    would close an import cycle. A second exception family would be two
    names for one verdict, which is worse than a deferred import.
    """
    from .arrival_store import ArrivalCanonicalUnsupported

    raise ArrivalCanonicalUnsupported(message)


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


def rows_of_record(record: dict) -> list[tuple[str, tuple]]:
    """The index rows one arrival record expands to, in order.

    ONE definition of "what a record indexes to", consumed by both the
    catch-up indexer and the re-deriver. Two definitions is how the writer
    and the re-deriver end up disagreeing about a store, which is the one
    disagreement this cut cannot tolerate.

    Structural records — genesis, key introductions — expand to **no rows**.
    Their bodies are not codec objects (the codec would refuse them on
    unknown fields), and their content is not lost by being skipped: it
    lives in the arrival log, which is the store.
    """
    kind = record["k"]
    if kind in _STRUCTURAL_KINDS:
        return []
    if kind not in _ROW_KINDS:
        _unsupported(
            f"record kind {kind!r} at ordinal {record['ord']} is not one "
            "this index knows how to consume — refusing rather than "
            "silently dropping it"
        )
    return records_from_object(record["body"])


def licensed_own_lineage(conn: sqlite3.Connection, lineage: str) -> str | None:
    """The ``own_lineage`` value this index's rows license, or None.

    The stamp is licensed by a **consumed ``_decl.genesis`` fact row whose
    id is the log's lineage** — movement 2, the declaration absorb, which is
    what stamps the marker on the live path. Two narrowings, both
    load-bearing:

    * NOT the mere existence of the arrival genesis at ordinal 0 (movement
      1). Stamping on that would flip a minted-but-never-absorbed store to
      "adopted", and ``witness.durable_handle`` would start emitting
      portable handles for stores that never opened a declaration lineage —
      a witness-semantics widening that is not this cut's.
    * NOT any ``_decl.genesis`` row. A merged store's log can carry a
      FOREIGN genesis row verbatim, and stamping that would mint the
      "marker without its genesis" corruption the declaration resolver
      already names.

    Restricted this way the stamp is a pure projection restore with zero
    semantic change.
    """
    from lang.document import DECL_GENESIS

    row = conn.execute(
        "SELECT id FROM facts WHERE id = ? AND kind = ?", (lineage, DECL_GENESIS)
    ).fetchone()
    return None if row is None else row[0]


@dataclass(frozen=True)
class Rederivation:
    """What a re-derivation did — counts, not a promise."""

    lineage: str
    ordinal: int
    """The last record consumed; -1 when the log carried none."""
    records: int
    facts: int
    ticks: int
    projections: tuple[str, ...]


def rederive_projections(
    canonical: Path, *, derived_log: bool = False
) -> Rederivation:
    """Discard an arrival store's projections and rebuild them from the log.

    The explicit operator verb. Building an ABSENT projection stays
    automatic (an absent projection destroys nothing when built); an
    EXISTING projection carrying rows is evidence, and discarding evidence
    is an operator's decision — so it is spelled here, off the object the
    write path holds.

    Replays from **ordinal 0, never partially**: the rowids handed out by a
    replay from empty reproduce the original assignment exactly, which is
    what keeps outstanding witness positions and seals valid across a
    re-derivation. A partial rebuild would renumber.

    Refuses (:class:`~engine.arrival_store.ArrivalCanonicalUnsupported`)
    when ``own_lineage`` is present and names a lineage other than the
    log's — that index is some other log's projection, and silently
    repointing it would be the strongest lie available in this design. The
    check runs BEFORE anything is cleared.
    """
    canonical = Path(canonical)
    log = ArrivalLog(canonical)
    lineage = log.lineage()  # refuses when this is not an arrival log
    index = index_path_for(canonical)

    conn = sqlite3.connect(str(index))
    conn.isolation_level = None  # explicit transaction control
    try:
        _ensure_index_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            marker = _meta_get(conn, _OWN_LINEAGE_KEY)
            if marker is not None and marker != lineage:
                _unsupported(
                    f"{index} carries an own_lineage marker of {marker!r}, "
                    f"but the log at {canonical} opens lineage {lineage!r} — "
                    "this index is some other log's projection; re-deriving "
                    "it would repoint an identity claim rather than rebuild "
                    "one"
                )

            conn.execute("DELETE FROM facts")
            conn.execute("DELETE FROM ticks")
            conn.execute("DROP TABLE IF EXISTS facts_fts")
            conn.execute("DROP TABLE IF EXISTS fts_state")

            records = facts = ticks = 0
            last: ResumeMark | None = None
            _, walked = log.walk_marked(None)
            for record, mark in walked:
                for t, row in rows_of_record(record):
                    conn.execute(
                        FACT_INSERT_SQL if t == "fact" else TICK_INSERT_SQL, row
                    )
                    if t == "fact":
                        facts += 1
                    else:
                        ticks += 1
                records += 1
                last = mark

            own = licensed_own_lineage(conn, lineage)
            if own is not None:
                _meta_set(conn, _OWN_LINEAGE_KEY, own)
            if last is not None:
                _stamp_mark(conn, last)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    projections = ("index", "derived-log") if derived_log else ("index",)
    return Rederivation(
        lineage=lineage,
        ordinal=-1 if last is None else last.arrival_ordinal,
        records=records,
        facts=facts,
        ticks=ticks,
        projections=projections,
    )


# --- index plumbing, kept off the store classes ------------------------------


def _ensure_index_schema(conn: sqlite3.Connection) -> None:
    """Make the index connectable as an index, whatever era it is from.

    Every statement is idempotent. The schema statements are the store
    class's own — imported rather than restated, so a schema column and a
    re-derived row can never drift apart — and the two column migrations
    mirror the store's, so an index written before the chain columns or the
    fact signature existed re-derives instead of failing on a missing
    column.
    """
    for stmt in _SCHEMA_STMTS:
        conn.execute(stmt)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    fact_cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
    if "signature" not in fact_cols:
        conn.execute("ALTER TABLE facts ADD COLUMN signature TEXT")
    tick_cols = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
    for col in ("prev_hash", "window_start", "fact_cursor", "window_hash", "signature"):
        if col not in tick_cols:
            conn.execute(f"ALTER TABLE ticks ADD COLUMN {col} TEXT")
    conn.commit()


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM store_meta WHERE key = ?", (key,)
    ).fetchone()
    return None if row is None else row[0]


def _meta_set(conn: sqlite3.Connection, key: str, value: object) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)",
        (key, str(value)),
    )


def _stamp_mark(conn: sqlite3.Connection, mark: ResumeMark) -> None:
    """The resume mark's three fields, written through this module's own
    connection. The key names are the store's — imported inside the
    function because :mod:`engine.arrival_store` sits above this one."""
    from .arrival_store import (
        ARRIVAL_LINEAGE_KEY,
        ARRIVAL_OFFSET_KEY,
        ARRIVAL_ORDINAL_KEY,
    )

    _meta_set(conn, ARRIVAL_LINEAGE_KEY, mark.arrival_lineage)
    _meta_set(conn, ARRIVAL_OFFSET_KEY, mark.arrival_offset)
    _meta_set(conn, ARRIVAL_ORDINAL_KEY, mark.arrival_ordinal)
