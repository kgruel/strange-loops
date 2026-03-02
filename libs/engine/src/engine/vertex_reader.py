"""Vertex reader — query-time fold materialization and search.

The sole read interface for store data. Compiles the vertex declaration,
replays facts through declared folds, returns fold state.

StoreReader is an internal detail — callers use vertex_read(),
vertex_facts(), vertex_ticks(), vertex_summary(), and vertex_search() instead.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def vertex_read(vertex_path: Path) -> dict[str, dict[str, Any]]:
    """Read fold state from a vertex's store.

    Parses the vertex file, compiles fold declarations to Specs,
    reads raw facts from the store, and replays through folds.

    Returns {kind: fold_state} where fold_state is the accumulated
    result of all facts of that kind replayed through the declared folds.

    If the vertex has no store or the store doesn't exist yet, returns
    initial (empty) fold state for each declared kind.
    """
    from lang import parse_vertex_file

    from .compiler import compile_vertex
    from .store_reader import StoreReader

    ast = parse_vertex_file(vertex_path)
    specs = compile_vertex(ast)

    # Resolve store path relative to vertex file
    if ast.store is None:
        return {kind: spec.initial_state() for kind, spec in specs.items()}

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    if not store_path.exists():
        return {kind: spec.initial_state() for kind, spec in specs.items()}

    with StoreReader(store_path) as reader:
        result = {}
        for kind, spec in specs.items():
            facts = reader.facts_by_kind(kind)
            # Inject fact metadata into payloads for folds that need it
            # (_ts for Latest fold, _observer for potential future use)
            payloads = []
            for fact in facts:
                p = dict(fact["payload"])
                p["_ts"] = fact["ts"]
                p["_observer"] = fact["observer"]
                payloads.append(p)
            result[kind] = spec.replay(payloads)
        return result


def vertex_facts(
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    kind: str | None = None,
) -> list[dict]:
    """Read raw facts from a vertex's store within a time range.

    For queries that need raw facts (e.g. log), not fold state.
    Still goes through the vertex — the vertex knows where its store is.
    """
    from lang import parse_vertex_file

    from .store_reader import StoreReader

    ast = parse_vertex_file(vertex_path)
    if ast.store is None:
        return []

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    if not store_path.exists():
        return []

    with StoreReader(store_path) as reader:
        return reader.facts_between(since_ts, until_ts, kind=kind)


def vertex_ticks(
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    name: str | None = None,
) -> list:
    """Read ticks from a vertex's store within a time range.

    Parallels vertex_facts for tick access through the vertex.
    Returns Tick objects (from StoreReader.ticks_between).
    """
    from lang import parse_vertex_file

    from .store_reader import StoreReader

    ast = parse_vertex_file(vertex_path)
    if ast.store is None:
        return []

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    if not store_path.exists():
        return []

    with StoreReader(store_path) as reader:
        return reader.ticks_between(since_ts, until_ts, name=name)


def vertex_summary(vertex_path: Path) -> dict:
    """Read store summary from a vertex — fact/tick counts and per-kind stats.

    Returns the same shape as StoreReader.summary():
        {"facts": {"total": N, "kinds": {...}}, "ticks": {"total": N, "names": {...}}}

    Returns zeroed summary if the vertex has no store or store doesn't exist.
    """
    from lang import parse_vertex_file

    from .store_reader import StoreReader

    ast = parse_vertex_file(vertex_path)
    if ast.store is None:
        return {"facts": {"total": 0, "kinds": {}}, "ticks": {"total": 0, "names": {}}}

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    if not store_path.exists():
        return {"facts": {"total": 0, "kinds": {}}, "ticks": {"total": 0, "names": {}}}

    with StoreReader(store_path) as reader:
        return reader.summary()


def _resolve_store(vertex_path: Path) -> tuple[Any, Path | None]:
    """Parse vertex and resolve store path. Returns (ast, store_path)."""
    from lang import parse_vertex_file

    ast = parse_vertex_file(vertex_path)
    if ast.store is None:
        return ast, None

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    if not store_path.exists():
        return ast, None

    return ast, store_path


def _ensure_fts(
    store_path: Path, search_fields: dict[str, tuple[str, ...]]
) -> None:
    """Create/update FTS5 index from spec-declared search fields. Idempotent.

    Opens the database with write access to create/populate the FTS table,
    then closes. The actual search runs read-only through StoreReader.
    """
    conn = sqlite3.connect(str(store_path))
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                text_content,
                fact_rowid UNINDEXED,
                kind UNINDEXED,
                observer UNINDEXED
            );
            CREATE TABLE IF NOT EXISTS fts_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )

        row = conn.execute(
            "SELECT value FROM fts_state WHERE key='last_rowid'"
        ).fetchone()
        last_rowid = int(row[0]) if row else 0

        rows = conn.execute(
            "SELECT rowid, kind, observer, payload FROM facts "
            "WHERE rowid > ? ORDER BY rowid",
            (last_rowid,),
        ).fetchall()

        max_rowid = last_rowid
        for rowid, kind, observer, payload_json in rows:
            fields = search_fields.get(kind)
            if not fields:
                continue  # Kind has no search declaration — skip
            payload = json.loads(payload_json)
            text = " ".join(str(payload.get(f, "")) for f in fields)
            if text.strip():
                conn.execute(
                    "INSERT INTO facts_fts(text_content, fact_rowid, kind, observer) "
                    "VALUES (?, ?, ?, ?)",
                    (text, rowid, kind, observer),
                )
            max_rowid = rowid

        if max_rowid > last_rowid:
            conn.execute(
                "INSERT OR REPLACE INTO fts_state(key, value) VALUES ('last_rowid', ?)",
                (str(max_rowid),),
            )
            conn.commit()
    finally:
        conn.close()


def vertex_search(
    vertex_path: Path,
    query: str,
    *,
    kind: str | None = None,
    since: float | None = None,
    until: float | None = None,
    limit: int = 100,
) -> list[dict]:
    """Search fact payloads in a vertex's store via FTS5.

    Uses spec-declared search fields — only kinds with a ``search``
    declaration in the vertex file are indexed. Empty query returns nothing.

    Args:
        vertex_path: Path to the .vertex file.
        query: FTS5 query string (words, phrases, prefix, boolean).
        kind: Filter by fact kind (exact match on FTS metadata).
        since: Only facts with ts >= since.
        until: Only facts with ts <= until.
        limit: Maximum results (default 100).

    Returns:
        Matching facts, newest first. Same shape as vertex_facts.
    """
    if not query or not query.strip():
        return []

    from .compiler import collect_search_fields
    from .store_reader import StoreReader

    ast, store_path = _resolve_store(vertex_path)
    if store_path is None:
        return []

    base_dir = vertex_path.parent
    search_fields = collect_search_fields(ast, base_dir)
    if not search_fields:
        return []

    _ensure_fts(store_path, search_fields)

    with StoreReader(store_path) as reader:
        return reader.search_facts(
            query, kind=kind, since=since, until=until, limit=limit
        )
