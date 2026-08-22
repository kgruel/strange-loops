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

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from .arrival import GENESIS_KIND, KEY_INTRODUCTION_KIND, ArrivalLog, ResumeMark
from .jsonl_codec import records_from_object, serialize_object
from .residence import canonical_for, index_path_for
from .sqlite_store import (
    _SCHEMA_STMTS,
    FACT_INSERT_SQL,
    TICK_INSERT_SQL,
)

__all__ = [
    "DerivedLogAgreement",
    "sort_key",
    "Rederivation",
    "audit_derived_log",
    "canonical_line",
    "derived_log_path_for",
    "derived_lines",
    "has_rows",
    "line_of_record",
    "rederive_projections",
    "rows_of_record",
    "write_derived_log",
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


def _projects(record: dict) -> bool:
    """Does this record project at all — and is it a record we may project?

    The classification BOTH projections make, spelled once. It is the same
    question in both directions (an index row and a derived-log line are two
    encodings of one row-class body), and the two projections answering it
    separately is how they would come to disagree about a store.

    ``False`` is the structural class — genesis, key introductions. Their
    bodies are not codec objects at all (the codec refuses them on unknown
    fields), and skipping them loses nothing: their content lives in the
    arrival log, which is the store. An unrecognized kind is neither class
    and refuses here, once, for both callers.
    """
    kind = record["k"]
    if kind in _STRUCTURAL_KINDS:
        return False
    if kind not in _ROW_KINDS:
        _unsupported(
            f"record kind {kind!r} at ordinal {record['ord']} is not one "
            "this store's projections know how to derive — refusing rather "
            "than silently dropping it"
        )
    return True


def rows_of_record(record: dict) -> list[tuple[str, tuple]]:
    """The index rows one arrival record expands to, in order.

    ONE definition of "what a record indexes to", consumed by both the
    catch-up indexer and the re-deriver. Two definitions is how the writer
    and the re-deriver end up disagreeing about a store, which is the one
    disagreement this cut cannot tolerate.

    Structural records expand to **no rows** — see :func:`_projects`, which
    is also where an unknown kind is refused.
    """
    if not _projects(record):
        return []
    return records_from_object(record["body"])


# --- the derived .jsonl log --------------------------------------------------


def derived_log_path_for(canonical: Path) -> Path:
    """Where an arrival log's derived ``.jsonl`` projection lives.

    ``<name>.jsonl`` beside the ``<name>.arrival`` — NO new suffix. This is
    the shape :func:`engine.probe.probe_target` already classifies as
    ``derived_log`` ("custody is the arrival log's, so this file is a
    projection, not a store"). Cut A named the half-migrated shape; cut B is
    what makes it deliberate rather than transitional, and a
    ``.derived.jsonl`` spelling would strand the classification and break
    every last-0.x reader the projection exists for.
    """
    return canonical_for(index_path_for(canonical), "jsonl")


def line_of_record(record: dict) -> str | None:
    """The derived log's line for one arrival record, or None for no line.

    Row-class records (fact/tick/batch) each emit ONE line — the codec
    encoding of that record's ``body`` and of nothing else. Because the body
    IS the codec's object for the committed row, re-encoding it is an
    identity round trip and the payload keeps riding as verbatim stored
    TEXT. A batch record's body emits as one ``batch`` line, unchanged.

    **NON-NEGOTIABLE: structural records (genesis, key introduction) have no
    derived-log line**, exactly as the index skips them — their bodies are
    not codec objects at all. Their content is not lost: it lives in the
    arrival log, which is the store.

    Not "the same arms as :func:`rows_of_record`" but literally the same
    call: both wrap :func:`_projects` and differ only in the terminal codec
    encoding, so the index and the derived log cannot disagree about which
    records project.
    """
    if not _projects(record):
        return None
    return serialize_object(record["body"])


def canonical_line(line: str) -> str:
    """One derived-log line in its canonical form, validated.

    The grammar and the sort key have ONE home. A consumer that rewrites a
    derived log — the git merge driver is the only one — imports this rather
    than re-spelling "decode, validate, re-encode in field order", so driver
    output and a fresh derivation cannot drift.
    """
    return serialize_object(json.loads(line))


def sort_key(line: str) -> bytes:
    """The derived log's ordering: byte-lexicographic over the encoded line.

    Spelled as a function because the ORDER IS A RULE, not an incidental
    ``sorted()`` call — the merge driver must sort by exactly what a fresh
    derivation sorts by.
    """
    return line.encode("utf-8")


def derived_lines(log: ArrivalLog) -> list[str]:
    """Every derived-log line for an arrival log, byte-lexicographically sorted.

    **NON-NEGOTIABLE: line order carries no meaning, and no reader may
    attribute one to it.** Byte sort is the only order that is a pure
    function of the SET: it needs no field semantics, is reproducible by
    ``sort(1)`` in any language, and is what lets the git merge driver
    produce the same bytes a fresh derivation produces without knowing any
    ordinal.

    Two consequences, stated here rather than left to be found:

    1. **The derived log is not a chain-verification surface.** Tick chain
       order is not file order — a chain walk over a byte-sorted projection
       would report breaks on a healthy store. Chain verification reads the
       arrival log.
    2. **A last-0.x reader rebuilding from this file folds in byte order.**
       That is a real interim hazard for the migration sidecar, and it is
       named here for that design; the sidecar's own answer is to consume
       the ``.arrival``, which carries the ordinal.

    **NON-NEGOTIABLE: derived from the arrival log alone, never from the
    index.** Deriving it from sqlite would make it a projection of a
    projection, and a poisoned index would launder itself into a second
    artifact.
    """
    lines = set()
    for record in log.walk():
        line = line_of_record(record)
        if line is not None:
            lines.add(line)
    return sorted(lines, key=sort_key)


def write_derived_log(canonical: Path) -> int:
    """Materialize the derived ``.jsonl`` projection. Returns the line count.

    **NON-NEGOTIABLE: on demand only, never on the append path.** Appending
    to a byte-sorted file is not an append, and regenerating it per emit is
    O(n) per write — the O(n^2) ingest shape this arc already paid for once.
    A lagging derived log is NOT an error: nothing in ``libs/`` reads it,
    because reads execute through the index in every mode (arrival law 1).

    Written through a temp file and renamed, so a crash mid-derivation
    leaves the previous projection rather than a truncated one.
    """
    canonical = Path(canonical)
    target = derived_log_path_for(canonical)
    lines = derived_lines(ArrivalLog(canonical))
    tmp = target.with_name(target.name + ".tmp")
    payload = "".join(line + "\n" for line in lines)
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(target)
    return len(lines)


@dataclass(frozen=True)
class DerivedLogAgreement:
    """Whether the derived log and the arrival log hold the same set.

    There is **no staleness marker**. The offset/count triple does not get a
    third sibling: the derived log's currency is a SET question, and the
    honest answer to a set question is a set comparison, not a stamp. A
    marker would also reintroduce offset custody inside the mutable artifact
    being judged.
    """

    ok: bool
    missing: int
    """Row-class records the arrival log carries and the file does not.

    Structural records are outside the projection, so a healthy store is
    never reported as missing its genesis.
    """
    extra: int
    """Lines the arrival log never carried."""
    detail: str


def _derived_digests(canonical: Path) -> set[bytes]:
    """Digest every line the arrival log projects, retaining none of them.

    Deliberately NOT ``{_digest(line) for line in derived_lines(...)}``:
    :func:`derived_lines` must materialize every line because it SORTS them,
    and an audit that borrowed it inherited a cost it does not need. Here
    each line is produced, hashed, and dropped, so what survives the walk is
    32 bytes per record.

    The bound, stated exactly rather than loosely: peak is **flat in record
    count** and **linear in the size of the LARGEST single record**. What
    survives the walk is 32 bytes per record; what is in flight is one
    record, which costs a small multiple of its own size because it is
    decoded, re-encoded and hashed. Measured: 5, 10, 20 and 40 records of
    1 MB each all peak at 7.02 MB, while one 4 MB record peaks at 28 MB.

    So "bounded by record count, never payload size" holds in the sense
    that matters — an audit over a big store does not grow with the store —
    but a single enormous record is still transiently expensive, and saying
    otherwise would be the kind of unbounded promise this module refuses to
    make elsewhere.
    """
    digests: set[bytes] = set()
    for record in ArrivalLog(canonical).walk():
        line = line_of_record(record)
        if line is not None:
            digests.add(_digest(line))
    return digests


def audit_derived_log(canonical: Path) -> DerivedLogAgreement:
    """Re-derive and diff. An operation, not a promise.

    The repo's established contract for derived artifacts (``verify_rebirth``
    is the precedent). Each side's lines are hashed to 32 bytes as they are
    produced and two set differences taken, so memory is bounded by RECORD
    COUNT and never by total payload size — see :func:`_derived_digests` for
    the exact bound.

    The reported counts survive digest-only sets, because a set difference
    over digests has the same cardinality as one over the lines they stand
    for. Nothing in :class:`DerivedLogAgreement` echoes line CONTENT — the
    detail names paths and counts — so the result is bounded too.
    """
    canonical = Path(canonical)
    target = derived_log_path_for(canonical)
    derived = _derived_digests(canonical)

    if not target.exists():
        return DerivedLogAgreement(
            ok=not derived,
            missing=len(derived),
            extra=0,
            detail=(
                f"no derived log at {target}"
                + ("" if not derived else f"; the arrival log projects {len(derived)} line(s)")
            ),
        )

    present = set()
    with target.open("rb") as fh:
        for raw in fh:
            if raw.endswith(b"\n"):
                present.add(hashlib.sha256(raw[:-1]).digest())
            elif raw:
                # A torn tail is not a line: it was never terminated, so it
                # never claimed to be a record. Counting it as `extra` would
                # report a crashed derivation as a disagreement about
                # content; the honest reading is that the file is short.
                pass

    missing = len(derived - present)
    extra = len(present - derived)
    ok = not missing and not extra
    return DerivedLogAgreement(
        ok=ok,
        missing=missing,
        extra=extra,
        detail=(
            f"{target} agrees with {canonical}"
            if ok
            else (
                f"{target} disagrees with {canonical}: {missing} record(s) the "
                f"arrival log carries are absent, {extra} line(s) it never "
                "carried are present"
            )
        ),
    )


def _digest(line: str) -> bytes:
    return hashlib.sha256(line.encode("utf-8")).digest()


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
                ord_val = record["ord"]
                for seq, (t, row) in enumerate(rows_of_record(record)):
                    conn.execute(
                        FACT_INSERT_SQL if t == "fact" else TICK_INSERT_SQL,
                        (*row, ord_val, seq),
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

    if derived_log:
        # Derived from the arrival log, in its own pass, AFTER the index
        # transaction closed — never from the rows just written. A
        # projection of a projection would let a poisoned index launder
        # itself into a second artifact.
        write_derived_log(canonical)
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
