"""SQLite schema and metadata for file-backed Arrival projections.

The definitions here are storage mechanics shared by the File adapter and
temporary legacy stores.  The module does not import either authority class or
the projection coordinator, which keeps the dependency direction acyclic.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from typing import Literal

from . import jsonl_codec

__all__ = [
    "ARRIVAL_LINEAGE_KEY",
    "ARRIVAL_OFFSET_KEY",
    "ARRIVAL_ORDINAL_KEY",
    "ArrivalCanonicalUnsupported",
    "FACT_ALL_COLUMNS",
    "FACT_COLUMN_INDEX",
    "FACT_COLUMNS",
    "FACT_CONTENT_COLUMNS",
    "FACT_INSERT_SQL",
    "TICK_ALL_COLUMNS",
    "TICK_COLUMN_INDEX",
    "TICK_COLUMNS",
    "TICK_CONTENT_COLUMNS",
    "TICK_INSERT_SQL",
    "ensure_coordinate_schema",
]

ARRIVAL_LINEAGE_KEY = "arrival_lineage"
ARRIVAL_OFFSET_KEY = "arrival_offset"
ARRIVAL_ORDINAL_KEY = "arrival_ordinal"


class ArrivalCanonicalUnsupported(NotImplementedError):
    """A file projection operation cannot preserve canonical Arrival truth."""


_CHAIN_COLUMNS = ("prev_hash", "window_start", "fact_cursor", "window_hash", "signature")

# Column definitions for facts and ticks.
#
# FACT_CONTENT_COLUMNS / TICK_CONTENT_COLUMNS define the canonical content
# payload order derived from the codec's field tuples (+ signature). This is the
# row layout shared by the JSONL log lines, codec serializations, and content-row
# assemblies.
#
# FACT_ALL_COLUMNS / TICK_ALL_COLUMNS append the trailing coordinate columns
# (arrival_ordinal, arrival_seq) required by the persisted SQLite tables and
# full INSERT statements.
FACT_CONTENT_COLUMNS = (*jsonl_codec.FACT_FIELDS, "signature")
TICK_CONTENT_COLUMNS = (*jsonl_codec.TICK_FIELDS, "signature")

FACT_COLUMNS = FACT_CONTENT_COLUMNS
TICK_COLUMNS = TICK_CONTENT_COLUMNS

FACT_ALL_COLUMNS = (*FACT_CONTENT_COLUMNS, "arrival_ordinal", "arrival_seq")
TICK_ALL_COLUMNS = (*TICK_CONTENT_COLUMNS, "arrival_ordinal", "arrival_seq")

# Name -> position in a content row. Consumers index rows by name through
# these instead of re-deriving positions with .index() at each call site,
# so a new content column moves every reader at once.
FACT_COLUMN_INDEX = {name: i for i, name in enumerate(FACT_CONTENT_COLUMNS)}
TICK_COLUMN_INDEX = {name: i for i, name in enumerate(TICK_CONTENT_COLUMNS)}


def _insert_sql(table: str, columns: tuple[str, ...]) -> str:
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"


FACT_INSERT_SQL = _insert_sql("facts", FACT_ALL_COLUMNS)
TICK_INSERT_SQL = _insert_sql("ticks", TICK_ALL_COLUMNS)

_TICK_ROW_SQL = ", ".join(TICK_COLUMNS)

# Delta-1 column set — used by the read-only verify path against stores that
# predate the signature column (verify never migrates schema).
_TICK_ROW_SQL_V1 = ", ".join(jsonl_codec.TICK_FIELDS)


_SCHEMA_STMTS = (
    """CREATE TABLE IF NOT EXISTS facts (
        id       TEXT NOT NULL PRIMARY KEY,
        kind     TEXT NOT NULL,
        ts       REAL NOT NULL,
        observer TEXT NOT NULL,
        origin   TEXT NOT NULL DEFAULT '',
        payload  TEXT NOT NULL CHECK (json_valid(payload)),
        signature TEXT,
        arrival_ordinal INTEGER NOT NULL,
        arrival_seq     INTEGER NOT NULL,
        UNIQUE (arrival_ordinal, arrival_seq)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind)",
    "CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts)",
    """CREATE TABLE IF NOT EXISTS ticks (
        id           TEXT NOT NULL PRIMARY KEY,
        name         TEXT NOT NULL,
        ts           REAL NOT NULL,
        since        REAL,
        origin       TEXT NOT NULL,
        payload      TEXT NOT NULL CHECK (json_valid(payload)),
        prev_hash    TEXT,
        window_start TEXT,
        fact_cursor  TEXT,
        window_hash  TEXT,
        signature    TEXT,
        arrival_ordinal INTEGER NOT NULL,
        arrival_seq     INTEGER NOT NULL,
        UNIQUE (arrival_ordinal, arrival_seq)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ticks_name ON ticks(name)",
    "CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts)",
)


def _quote_ident(ident: str) -> str:
    """Quote a SQLite identifier using double quotes, escaping embedded quotes."""
    return '"' + ident.replace('"', '""') + '"'


def _verify_coordinate_schema(conn: sqlite3.Connection, table: str) -> tuple[bool, str | None]:
    """Verify table has arrival_ordinal and arrival_seq columns with NOT NULL
    and a UNIQUE (arrival_ordinal, arrival_seq) constraint.

    Returns (True, None) if valid, or (False, defect_description) if invalid.
    """
    cols = {
        r[1]: {"notnull": bool(r[3]), "pk": bool(r[5])}
        for r in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")
    }
    if "arrival_ordinal" not in cols:
        return False, f"{table} lacks arrival_ordinal column"
    if not cols["arrival_ordinal"]["notnull"]:
        return False, f"{table} lacks NOT NULL on arrival_ordinal"
    if "arrival_seq" not in cols:
        return False, f"{table} lacks arrival_seq column"
    if not cols["arrival_seq"]["notnull"]:
        return False, f"{table} lacks NOT NULL on arrival_seq"

    has_unique = False
    for idx_row in conn.execute(f"PRAGMA index_list({_quote_ident(table)})"):
        is_unique = bool(idx_row[2])
        # Only a table-owned constraint counts (origin 'u' = auto-index from a
        # table-level UNIQUE). A standalone CREATE UNIQUE INDEX (origin 'c')
        # can be dropped without a rebuild, so the invariant would not live in
        # the table as D0 requires.
        if not is_unique or idx_row[3] != "u":
            continue
        idx_name = idx_row[1]
        idx_cols = [r[2] for r in conn.execute(f"PRAGMA index_info({_quote_ident(idx_name)})")]
        if idx_cols == ["arrival_ordinal", "arrival_seq"]:
            has_unique = True
            break

    if not has_unique:
        schema_row = conn.execute(
            "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if (
            schema_row
            and schema_row[0]
            and re.search(
                r"UNIQUE\s*\(\s*arrival_ordinal\s*,\s*arrival_seq\s*\)",
                schema_row[0],
                re.IGNORECASE,
            )
        ):
            has_unique = True

    if not has_unique:
        return False, f"{table} lacks UNIQUE (arrival_ordinal, arrival_seq) constraint"

    return True, None


def _stamp_coordinate_axis(conn: sqlite3.Connection, mode: str = "mirrored") -> None:
    """Write the store_meta.coordinate_axis marker for mirrored mode.

    Arrival mode MUST go through _stamp_arrival_axis to ensure provider agreement.
    """
    if mode == "arrival":
        raise ValueError("coordinate_axis='arrival' must be stamped via _stamp_arrival_axis")
    conn.execute("CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('coordinate_axis', ?)",
        (mode,),
    )


def _stage_arrival_coordinates(
    conn: sqlite3.Connection,
    coordinates: Callable[[], Iterator[tuple[str, str, int, int]]] | None,
) -> None:
    """Stage coordinates from provider into _coordinate_staging temp table."""
    if coordinates is None:
        raise ValueError("coordinates provider is required for mode='arrival' when validate=True")

    from .arrival import ArrivalCorrupt, GenesisRefused

    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _coordinate_staging ("
        "table_name TEXT NOT NULL, "
        "row_id TEXT NOT NULL, "
        "arrival_ordinal INTEGER NOT NULL, "
        "arrival_seq INTEGER NOT NULL, "
        "PRIMARY KEY (table_name, row_id)"
        ")"
    )
    conn.execute("DELETE FROM _coordinate_staging")

    try:
        staged = list(coordinates())
    except BaseException as exc:
        if (
            isinstance(exc, (FileNotFoundError, ArrivalCorrupt, GenesisRefused))
            or "is empty — mint a genesis first" in str(exc)
            or "does not exist" in str(exc)
            or "No such file" in str(exc)
        ):
            raise ArrivalCanonicalUnsupported(
                "an index without its log cannot be reconciled, and re-derivation cannot "
                "manufacture a log: offering it here would name an operation that destroys "
                "the only surviving artifact. Restore the log, or open the db as a "
                "plain sqlite store"
            ) from exc
        raise ArrivalCanonicalUnsupported(
            f"error retrieving coordinates from arrival log: {exc} — "
            "run engine.arrival_projection.rederive_projections to rebuild the index from the log"
        ) from exc

    for item in staged:
        if not isinstance(item, tuple) or len(item) != 4:
            raise ArrivalCanonicalUnsupported(
                "coordinate provider yielded invalid tuple format — "
                "run engine.arrival_projection.rederive_projections to rebuild the "
                "index from the log"
            )
        tbl, r_id, ord_val, seq_val = item
        if tbl not in ("facts", "ticks"):
            raise ArrivalCanonicalUnsupported(
                f"invalid table name {tbl!r} in coordinate provider — "
                "run engine.arrival_projection.rederive_projections to rebuild the "
                "index from the log"
            )

    try:
        conn.executemany(
            "INSERT INTO _coordinate_staging (table_name, row_id, arrival_ordinal, arrival_seq) "
            "VALUES (?, ?, ?, ?)",
            staged,
        )
    except sqlite3.IntegrityError as exc:
        raise ArrivalCanonicalUnsupported(
            f"duplicate or conflicting coordinates in arrival log: {exc} — "
            "run engine.arrival_projection.rederive_projections to rebuild the index from the log"
        ) from exc

    dup = conn.execute(
        "SELECT table_name, arrival_ordinal, arrival_seq, COUNT(*) "
        "FROM _coordinate_staging "
        "GROUP BY table_name, arrival_ordinal, arrival_seq "
        "HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if dup is not None:
        raise ArrivalCanonicalUnsupported(
            f"duplicate coordinate ({dup[1]}, {dup[2]}) in log for {dup[0]} — "
            "run engine.arrival_projection.rederive_projections to rebuild the index from the log"
        )


def _check_arrival_provider_agreement(
    conn: sqlite3.Connection,
    coordinates: Callable[[], Iterator[tuple[str, str, int, int]]] | None,
) -> None:
    """Stage coordinates from provider and verify exact agreement with existing tables."""
    _stage_arrival_coordinates(conn, coordinates)

    tables_to_check = ("facts", "ticks")
    existing_tables = [
        t
        for t in tables_to_check
        if conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (t,)
        ).fetchone()
        is not None
    ]

    # Mismatch checks against existing tables:
    for t in existing_tables:
        index_count = conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(t)}").fetchone()[0]
        staging_count = conn.execute(
            "SELECT COUNT(*) FROM _coordinate_staging WHERE table_name = ?", (t,)
        ).fetchone()[0]
        if index_count != staging_count:
            raise ArrivalCanonicalUnsupported(
                f"index content does not match arrival log coordinates ({t} has "
                f"{index_count} rows, log has {staging_count}) — "
                "run engine.arrival_projection.rederive_projections to rebuild the "
                "index from the log"
            )

        missing_in_staging = conn.execute(
            f"SELECT f.id FROM {_quote_ident(t)} f LEFT JOIN _coordinate_staging s ON "
            "s.table_name = ? AND s.row_id = f.id WHERE s.row_id IS NULL LIMIT 1",
            (t,),
        ).fetchone()
        if missing_in_staging is not None:
            raise ArrivalCanonicalUnsupported(
                f"index content does not match arrival log coordinates ({t} row "
                f"{missing_in_staging[0]!r} not in log) — "
                "run engine.arrival_projection.rederive_projections to rebuild the "
                "index from the log"
            )

        missing_in_index = conn.execute(
            f"SELECT s.row_id FROM _coordinate_staging s LEFT JOIN {_quote_ident(t)} f "
            "ON s.row_id = f.id WHERE s.table_name = ? AND f.id IS NULL LIMIT 1",
            (t,),
        ).fetchone()
        if missing_in_index is not None:
            raise ArrivalCanonicalUnsupported(
                f"index content does not match arrival log coordinates (log {t} row "
                f"{missing_in_index[0]!r} not in index) — "
                "run engine.arrival_projection.rederive_projections to rebuild the "
                "index from the log"
            )

        # Staging join agreement check for existing coordinate columns
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({_quote_ident(t)})")}
        if "arrival_ordinal" in cols and "arrival_seq" in cols:
            coord_mismatch = conn.execute(
                f"SELECT f.id, f.arrival_ordinal, f.arrival_seq, s.arrival_ordinal, s.arrival_seq "
                f"FROM {_quote_ident(t)} f JOIN _coordinate_staging s ON s.table_name "
                "= ? AND s.row_id = f.id "
                f"WHERE f.arrival_ordinal != s.arrival_ordinal OR f.arrival_seq != s.arrival_seq "
                f"LIMIT 1",
                (t,),
            ).fetchone()
            if coord_mismatch is not None:
                raise ArrivalCanonicalUnsupported(
                    f"index coordinates do not match arrival log ({t} row "
                    f"{coord_mismatch[0]!r} has "
                    f"({coord_mismatch[1]}, {coord_mismatch[2]}), log has "
                    f"({coord_mismatch[3]}, {coord_mismatch[4]})) — "
                    "run engine.arrival_projection.rederive_projections to rebuild "
                    "the index from the log"
                )

    non_existing = set(tables_to_check) - set(existing_tables)
    for non_t in non_existing:
        extra = conn.execute(
            "SELECT COUNT(*) FROM _coordinate_staging WHERE table_name = ?", (non_t,)
        ).fetchone()[0]
        if extra > 0:
            raise ArrivalCanonicalUnsupported(
                "index content does not match arrival log coordinates (log has "
                f"{extra} {non_t} rows but table does not exist) — "
                "run engine.arrival_projection.rederive_projections to rebuild the "
                "index from the log"
            )


def _stamp_arrival_axis(
    conn: sqlite3.Connection,
    coordinates: Callable[[], Iterator[tuple[str, str, int, int]]] | None = None,
    *,
    validate: bool = True,
) -> None:
    """The ONLY gatekeeper path allowed to write coordinate_axis='arrival' into store_meta.

    Always runs the provider-agreement check (staging join) when validate=True:
    - empty index + empty provider = agreement (stamps)
    - empty index + any provider row = refusal toward rederive_projections
    - coordinate disagreement or count mismatch = refusal toward rederive_projections
    """
    if validate:
        _check_arrival_provider_agreement(conn, coordinates)

    conn.execute("CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('coordinate_axis', 'arrival')"
    )


def ensure_coordinate_schema(
    conn: sqlite3.Connection,
    *,
    mode: Literal["mirrored", "arrival"],
    coordinates: Callable[[], Iterator[tuple[str, str, int, int]]] | None = None,
    validate: bool = True,
) -> None:
    """Ensure facts and ticks have arrival_ordinal and arrival_seq columns with
    NOT NULL and table-level UNIQUE (arrival_ordinal, arrival_seq) constraints.

    Structurally verifies that each existing table (facts, ticks) has both
    arrival_ordinal and arrival_seq columns with notnull=1 and a
    UNIQUE (arrival_ordinal, arrival_seq) constraint.

    When the store_meta.coordinate_axis marker is present:
        If the marker matches the requested mode:
            Performs structural verification across all existing tables.
            If all tables conform, returns immediately (fast path).
            If any structural requirement fails, raises ArrivalCanonicalUnsupported
            naming the table and defect, refusing out-of-band stamped incomplete stores
            without modifying them.
        If the marker does not match the requested mode:
            If the store has zero rows in both tables (fresh store case), verifies
            structure and corrects the marker to the requested mode.
            If any rows are present in existing tables, raises ArrivalCanonicalUnsupported
            naming both the existing marker and the requested mode.

    When the store_meta.coordinate_axis marker is absent:
        Structurally verified tables are skipped.
        Incomplete or legacy tables are rebuilt in dependency-closed order.
        Stamps store_meta.coordinate_axis upon successful migration.

    In mode="mirrored":
        Rebuilds legacy tables, assigning arrival_ordinal = rowid, arrival_seq = 0.
        Preserves rowids explicitly, and recreates indexes, triggers, and dependent
        views in dependency-closed order.
        Stamps store_meta.coordinate_axis = 'mirrored'.
    In mode="arrival":
        When validate=True:
            Rebuilds legacy tables using coordinates provided by `coordinates` closure
            which yields (table, row_id, arrival_ordinal, arrival_seq).
            Preserves rowids explicitly, and recreates indexes, triggers, and dependent
            views in dependency-closed order.
            Stamps store_meta.coordinate_axis = 'arrival' via the _stamp_arrival_axis gatekeeper.
            Refuses if index and provider walk mismatch.
        When validate=False:
            Rebuilds legacy tables populating existing rows with placeholder coordinates
            (arrival_ordinal = rowid, arrival_seq = 0) without provider validation.
            Preserves rowids explicitly, and recreates indexes, triggers, and dependent
            views in dependency-closed order.
            Stamps store_meta.coordinate_axis = 'arrival'.
    """
    if mode not in ("mirrored", "arrival"):
        raise ValueError(f"unknown coordinate mode: {mode!r}")
    if mode == "mirrored" and coordinates is not None:
        raise ValueError("coordinates provider is forbidden for mode='mirrored'")
    if mode == "arrival" and validate and coordinates is None:
        raise ValueError("coordinates provider is required for mode='arrival' when validate=True")

    # Check store_meta for existing coordinate_axis marker or arrival lineage
    meta_table_exists = (
        conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='store_meta'"
        ).fetchone()
        is not None
    )

    if meta_table_exists:
        # Mis-mode refusal: if store_meta carries ARRIVAL_LINEAGE_KEY and mode="mirrored"

        lineage_row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (ARRIVAL_LINEAGE_KEY,)
        ).fetchone()
        if lineage_row is not None and lineage_row[0] and mode == "mirrored":
            raise ArrivalCanonicalUnsupported(
                "cannot apply mirrored coordinate schema to arrival-canonical index "
                f"(store carries {ARRIVAL_LINEAGE_KEY}={lineage_row[0]!r})"
            )

    # Check which tables exist
    tables_to_check = ("facts", "ticks")
    existing_tables = [
        t
        for t in tables_to_check
        if conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (t,)
        ).fetchone()
        is not None
    ]

    if meta_table_exists:
        axis_row = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        if axis_row is not None and axis_row[0]:
            if axis_row[0] == mode:
                for t in existing_tables:
                    valid, defect = _verify_coordinate_schema(conn, t)
                    if not valid:
                        raise ArrivalCanonicalUnsupported(
                            f"{defect} — coordinate_axis marker disagrees with table structure "
                            "(out-of-band interference)"
                        )
                return  # Fast path: marker present, mode matches, and structure complete

            # Marker value does not match requested mode
            all_empty = all(
                conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(t)}").fetchone()[0] == 0
                for t in existing_tables
            )
            if not all_empty:
                raise ArrivalCanonicalUnsupported(
                    f"coordinate_axis marker {axis_row[0]!r} disagrees with requested "
                    f"mode {mode!r} "
                    "on non-empty store"
                )
            for t in existing_tables:
                valid, defect = _verify_coordinate_schema(conn, t)
                if not valid:
                    raise ArrivalCanonicalUnsupported(
                        f"{defect} — coordinate_axis marker disagrees with table structure "
                        "(out-of-band interference)"
                    )
            if mode == "arrival":
                _stamp_arrival_axis(conn, coordinates, validate=validate)
            else:
                _stamp_coordinate_axis(conn, mode)
            conn.commit()
            return

    if not existing_tables:
        if mode == "arrival":
            _stamp_arrival_axis(conn, coordinates, validate=validate)
        else:
            _stamp_coordinate_axis(conn, mode)
        conn.commit()
        return

    already_migrated = all(_verify_coordinate_schema(conn, t)[0] for t in existing_tables)

    if already_migrated:
        if mode == "arrival":
            _stamp_arrival_axis(conn, coordinates, validate=validate)
        else:
            _stamp_coordinate_axis(conn, mode)
        conn.commit()
        return

    # Non-migrated / legacy tables path
    prev_iso = conn.isolation_level
    conn.isolation_level = None  # explicit transaction control
    try:
        if mode == "arrival" and validate:
            _check_arrival_provider_agreement(conn, coordinates)

        for table in tables_to_check:
            if table not in existing_tables:
                continue

            valid, _ = _verify_coordinate_schema(conn, table)
            if valid:
                continue

            conn.execute("BEGIN IMMEDIATE")
            try:
                _rebuild_table(conn, table, mode=mode, validate=validate)
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

        # Post-rebuild stamp
        conn.execute("BEGIN IMMEDIATE")
        try:
            if mode == "arrival":
                _stamp_arrival_axis(conn, coordinates, validate=validate)
            else:
                _stamp_coordinate_axis(conn, mode)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        if mode == "arrival" and validate:
            conn.execute("DROP TABLE IF EXISTS _coordinate_staging")
        conn.isolation_level = prev_iso


def _rebuild_table(
    conn: sqlite3.Connection,
    table: str,
    *,
    mode: str,
    validate: bool = True,
) -> None:
    # 1. Collect views in dependency closure (fixed-point iteration)
    all_views = conn.execute(
        "SELECT name, sql FROM sqlite_schema WHERE type = 'view' AND sql IS NOT NULL"
    ).fetchall()

    collected_view_names: set[str] = set()
    collected_views_ordered: list[tuple[str, str]] = []
    target_names: set[str] = {table}

    while True:
        newly_found: list[tuple[str, str]] = []
        for v_name, v_sql in all_views:
            if v_name in collected_view_names:
                continue
            for target in target_names:
                if re.search(rf"\b{re.escape(target)}\b", v_sql, re.IGNORECASE):
                    newly_found.append((v_name, v_sql))
                    break
        if not newly_found:
            break
        for v_name, v_sql in newly_found:
            collected_view_names.add(v_name)
            collected_views_ordered.append((v_name, v_sql))
        target_names = {v_name for v_name, _ in newly_found}

    # 2. Collect triggers on table and collected views
    collected_triggers: list[tuple[str, str, str]] = []
    for target in [table, *collected_views_ordered]:
        t_target_name = target if isinstance(target, str) else target[0]
        t_rows = conn.execute(
            "SELECT name, tbl_name, sql FROM sqlite_schema WHERE type = 'trigger' AND "
            "tbl_name = ? AND sql IS NOT NULL",
            (t_target_name,),
        ).fetchall()
        collected_triggers.extend(t_rows)

    # 3. Collect indexes on table (skipping auto-indexes)
    collected_indexes = conn.execute(
        "SELECT name, sql FROM sqlite_schema WHERE type = 'index' AND tbl_name = ? "
        "AND sql IS NOT NULL",
        (table,),
    ).fetchall()

    # 4. Drop triggers, views (reverse dependency order), and indexes
    for t_name, _, _ in collected_triggers:
        conn.execute(f"DROP TRIGGER IF EXISTS {_quote_ident(t_name)}")

    for v_name, _ in reversed(collected_views_ordered):
        conn.execute(f"DROP VIEW IF EXISTS {_quote_ident(v_name)}")

    for idx_name, _ in collected_indexes:
        conn.execute(f"DROP INDEX IF EXISTS {_quote_ident(idx_name)}")

    # 5. Create new table with full schema
    temp_table = f"{table}_new"
    conn.execute(f"DROP TABLE IF EXISTS {_quote_ident(temp_table)}")
    if table == "facts":
        conn.execute(f"""CREATE TABLE {_quote_ident(temp_table)} (
            id       TEXT NOT NULL PRIMARY KEY,
            kind     TEXT NOT NULL,
            ts       REAL NOT NULL,
            observer TEXT NOT NULL,
            origin   TEXT NOT NULL DEFAULT '',
            payload  TEXT NOT NULL CHECK (json_valid(payload)),
            signature TEXT,
            arrival_ordinal INTEGER NOT NULL,
            arrival_seq     INTEGER NOT NULL,
            UNIQUE (arrival_ordinal, arrival_seq)
        )""")
        existing_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")}
        sig_sel = "signature" if "signature" in existing_cols else "NULL"
        if mode == "mirrored" or not validate:
            conn.execute(f"""
                INSERT INTO {_quote_ident(temp_table)} (rowid, id, kind, ts,
                    observer, origin, payload, signature, arrival_ordinal,
                    arrival_seq)
                SELECT rowid, id, kind, ts, observer, origin, payload, {sig_sel}, rowid, 0
                FROM {_quote_ident(table)}
            """)
        else:
            sig_join_sel = "f.signature" if "signature" in existing_cols else "NULL"
            conn.execute(f"""
                INSERT INTO {_quote_ident(temp_table)} (rowid, id, kind, ts,
                    observer, origin, payload, signature, arrival_ordinal,
                    arrival_seq)
                SELECT f.rowid, f.id, f.kind, f.ts, f.observer, f.origin,
                    f.payload, {sig_join_sel}, s.arrival_ordinal, s.arrival_seq
                FROM {_quote_ident(table)} f
                JOIN _coordinate_staging s ON s.table_name = 'facts' AND s.row_id = f.id
            """)
    else:  # ticks
        conn.execute(f"""CREATE TABLE {_quote_ident(temp_table)} (
            id           TEXT NOT NULL PRIMARY KEY,
            name         TEXT NOT NULL,
            ts           REAL NOT NULL,
            since        REAL,
            origin       TEXT NOT NULL,
            payload      TEXT NOT NULL CHECK (json_valid(payload)),
            prev_hash    TEXT,
            window_start TEXT,
            fact_cursor  TEXT,
            window_hash  TEXT,
            signature    TEXT,
            arrival_ordinal INTEGER NOT NULL,
            arrival_seq     INTEGER NOT NULL,
            UNIQUE (arrival_ordinal, arrival_seq)
        )""")
        existing_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")}
        sig_sel = "signature" if "signature" in existing_cols else "NULL"
        chain_sel = (
            "prev_hash, window_start, fact_cursor, window_hash"
            if "prev_hash" in existing_cols
            else "NULL, NULL, NULL, NULL"
        )
        if mode == "mirrored" or not validate:
            conn.execute(f"""
                INSERT INTO {_quote_ident(temp_table)} (rowid, id, name, ts,
                    since, origin, payload, prev_hash, window_start,
                    fact_cursor, window_hash, signature, arrival_ordinal,
                    arrival_seq)
                SELECT rowid, id, name, ts, since, origin, payload, {chain_sel}, {sig_sel}, rowid, 0
                FROM {_quote_ident(table)}
            """)
        else:
            sig_join_sel = "t.signature" if "signature" in existing_cols else "NULL"
            chain_join_sel = (
                "t.prev_hash, t.window_start, t.fact_cursor, t.window_hash"
                if "prev_hash" in existing_cols
                else "NULL, NULL, NULL, NULL"
            )
            conn.execute(f"""
                INSERT INTO {_quote_ident(temp_table)} (rowid, id, name, ts,
                    since, origin, payload, prev_hash, window_start,
                    fact_cursor, window_hash, signature, arrival_ordinal,
                    arrival_seq)
                SELECT t.rowid, t.id, t.name, t.ts, t.since, t.origin,
                    t.payload, {chain_join_sel}, {sig_join_sel},
                    s.arrival_ordinal, s.arrival_seq
                FROM {_quote_ident(table)} t
                JOIN _coordinate_staging s ON s.table_name = 'ticks' AND s.row_id = t.id
            """)

    # 6. Drop old table and rename new table
    conn.execute(f"DROP TABLE {_quote_ident(table)}")
    conn.execute(f"ALTER TABLE {_quote_ident(temp_table)} RENAME TO {_quote_ident(table)}")

    # 7. Recreate indexes
    for _idx_name, idx_sql in collected_indexes:
        conn.execute(idx_sql)

    if table == "facts":
        conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts)")
    else:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_name ON ticks(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts)")

    # 8. Recreate views in forward dependency order
    for _v_name, v_sql in collected_views_ordered:
        conn.execute(v_sql)

    # 9. Recreate triggers
    for _t_name, _, t_sql in collected_triggers:
        conn.execute(t_sql)
