"""jsonl — export a sqlite store to the canonical JSONL log, and rebuild from it.

The migration oracle for design/architecture/jsonl-canonical-store: JSONL is
the canonical store, sqlite a derived rebuildable index. This module is the
bridge between the two representations for stores that predate the flip.

``export_jsonl`` walks an existing store and writes ONE interleaved log
(``<name>.jsonl``) through ``engine.jsonl_codec`` — every field, including
``payload``, rides as the VERBATIM stored TEXT. ``rebuild_jsonl`` reads that
log back into a fresh sqlite store with the canonical schema. Round-tripping
re-derives byte-identical row hashes (``engine.tick_row_hash``) and every
signature keeps verifying; that is the property the oracle test asserts.

ORDERING RULE (global receipt order)
------------------------------------
Facts and ticks live in separate tables with independent rowids, so the
interleave needs a defensible total order. The tick row itself carries the
join: ``fact_cursor`` is the id of the newest fact by WITNESS order (rowid)
at mint time, and ``window_hash`` commits to the fact rows in
``(window_start, fact_cursor]`` — again by rowid. So a tick's receipt position
is exactly "immediately after the fact at its ``fact_cursor``".

The order is therefore the sort by key:

- fact at rowid *r* → ``(r, 1, 0)``
- tick with cursor resolving to fact rowid *r* → ``(r, 2, tick_rowid)``

which places each tick after every fact of its window and before the next
fact appended, and breaks ties between ticks sharing a cursor (a tick minted
with no new facts since the last one) by tick append order. Two edges:

- ``fact_cursor = ""`` — the genesis case of an empty store (``append_tick``
  writes ``""`` when no fact exists yet). Key ``(0, 2, rowid)``: the tick
  sorts ahead of every fact, which is its true receipt position.
- ``fact_cursor`` NULL (the pre-chain era) or naming a fact absent from this
  store (a sliced/compacted custody context). Neither can be resolved, so the
  cursor cannot order it; such ticks fall back to their own append order
  relative to the tick sequence, anchored at the cursor of the nearest
  preceding resolvable tick — monotone, deterministic, and never reordering
  the chain against itself.

Receipt order is never id order — mixed uuid4/ULID eras and late-arriving
facts both break it (see the ORDERING AUTHORITY note in engine.sqlite_store).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ._conn import _open

__all__ = ["ExportResult", "RebuildResult", "export_jsonl", "rebuild_jsonl"]

_FACT_COLS = "id, kind, ts, observer, origin, payload"
_TICK_COLS = (
    "id, name, ts, since, origin, payload, "
    "prev_hash, window_start, fact_cursor, window_hash"
)


@dataclass(frozen=True)
class ExportResult:
    """Counts from an export."""

    facts: int
    ticks: int
    lines: int
    path: Path


@dataclass(frozen=True)
class RebuildResult:
    """Counts from a rebuild."""

    facts: int
    ticks: int
    path: Path


_FACT_FIELDS = (*_FACT_COLS.split(", "), "signature")
_TICK_FIELDS = (*_TICK_COLS.split(", "), "signature")


def _read_rows(conn: sqlite3.Connection) -> tuple[list, list]:
    """Read fact and tick rows in append order, era-aware on missing columns.

    A truly pre-chain store has a NARROW schema — no chain columns, no
    signature column at all — so column presence is read from the schema and
    absent columns are selected as NULL. Rows come back at full arity
    (7 fact fields / 11 tick fields), the shape the hashers and the codec
    take: an absent column and a NULL value are the same era claim.
    """

    def rows(table: str, fields: tuple[str, ...]) -> list:
        present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        sql = ", ".join(f if f in present else "NULL" for f in fields)
        return [
            (raw[0], tuple(raw[1:]))
            for raw in conn.execute(
                f"SELECT rowid, {sql} FROM {table} ORDER BY rowid"
            )
        ]

    return rows("facts", _FACT_FIELDS), rows("ticks", _TICK_FIELDS)


def _receipt_order(facts: list, ticks: list) -> list[tuple[str, tuple]]:
    """Interleave facts and ticks into global receipt order.

    See the ORDERING RULE in the module docstring. Pure function over the
    two row lists — the ordering logic is testable without a database.
    """
    fact_rowid_by_id = {row[0]: rowid for rowid, row in facts}

    keyed: list[tuple[tuple[int, int, int], str, tuple]] = [
        ((rowid, 1, 0), "fact", row) for rowid, row in facts
    ]

    anchor = 0  # last resolvable cursor position; unresolvable ticks inherit it
    for rowid, row in ticks:
        cursor = row[8]
        if cursor == "":
            anchor = 0
        elif cursor is not None and cursor in fact_rowid_by_id:
            anchor = fact_rowid_by_id[cursor]
        keyed.append(((anchor, 2, rowid), "tick", row))

    keyed.sort(key=lambda item: item[0])
    return [(t, row) for _, t, row in keyed]


def export_jsonl(source: Path, target: Path) -> ExportResult:
    """Write ``source``'s facts and ticks to ``target`` as one JSONL log.

    Raises FileNotFoundError if the source is missing, FileExistsError if the
    target already exists (export never overwrites a log).
    """
    from engine.jsonl_codec import serialize_fact_row, serialize_tick_row

    source, target = Path(source), Path(target)
    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")
    if target.exists():
        raise FileExistsError(f"Export target already exists: {target}")

    conn = _open(source, read_only=True)
    try:
        facts, ticks = _read_rows(conn)
    finally:
        conn.close()

    ordered = _receipt_order(facts, ticks)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialize = {"fact": serialize_fact_row, "tick": serialize_tick_row}
    with target.open("w", encoding="utf-8") as fh:
        for t, row in ordered:
            fh.write(serialize[t](row))
            fh.write("\n")
        fh.flush()

    return ExportResult(
        facts=len(facts), ticks=len(ticks), lines=len(ordered), path=target
    )


def rebuild_jsonl(source: Path, target: Path) -> RebuildResult:
    """Rebuild a fresh sqlite store at ``target`` from the JSONL log ``source``.

    Schema comes from ``engine.SqliteStore``'s own creation path (the widest
    canonical schema — chain columns AND both signature columns); rows are
    then inserted verbatim in log order, so target rowid order reproduces the
    receipt order the log carries. No append/mint machinery runs: this is an
    index rebuild, not a re-emit — hashes and signatures must not change.
    """
    from engine import SqliteStore
    from engine.jsonl_codec import deserialize_row

    source, target = Path(source), Path(target)
    if not source.exists():
        raise FileNotFoundError(f"JSONL log not found: {source}")
    if target.exists():
        raise FileExistsError(f"Rebuild target already exists: {target}")

    fact_rows: list[tuple] = []
    tick_rows: list[tuple] = []
    with source.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            t, row = deserialize_row(line)
            (fact_rows if t == "fact" else tick_rows).append(row)

    target.parent.mkdir(parents=True, exist_ok=True)
    # Constructing the store creates the canonical schema; append() is never
    # called, so the serializers are never invoked.
    store = SqliteStore(path=target, serialize=lambda d: d,
                        deserialize=lambda d: d)
    store.close()

    conn = _open(target)
    try:
        conn.executemany(
            f"INSERT INTO facts ({_FACT_COLS}, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            fact_rows,
        )
        conn.executemany(
            f"INSERT INTO ticks ({_TICK_COLS}, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tick_rows,
        )
        conn.commit()
    finally:
        conn.close()

    return RebuildResult(facts=len(fact_rows), ticks=len(tick_rows),
                         path=target)
