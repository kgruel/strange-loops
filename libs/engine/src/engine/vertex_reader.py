"""Vertex reader — query-time fold materialization and search.

The sole read interface for store data. Compiles the vertex declaration,
replays facts through declared folds, returns fold state.

StoreReader is an internal detail — callers use vertex_read(),
vertex_facts(), vertex_ticks(), vertex_summary(), and vertex_search() instead.

Combinatorial vertices (those with a ``combine`` block) virtualize reads
across multiple stores using SQLite ATTACH DATABASE — no data is copied.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tick import Tick


# ---------------------------------------------------------------------------
# Combinatorial vertex helpers
# ---------------------------------------------------------------------------


def _loops_home() -> Path:
    """Resolve the loops config directory (same convention as CLI)."""
    if env := os.environ.get("LOOPS_HOME"):
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "loops"


def _resolve_combine_stores(ast: Any, vertex_path: Path) -> list[Path]:
    """Resolve combine entries to a list of existing store paths.

    For each CombineEntry, resolves the vertex name to a .vertex file,
    parses it, and extracts its store path. Skips entries whose store
    doesn't exist (graceful degradation).
    """
    from lang import parse_vertex_file, resolve_vertex

    home = _loops_home()
    store_paths: list[Path] = []

    for entry in ast.combine:
        vpath = resolve_vertex(entry.name, home)
        if not vpath.is_absolute():
            vpath = (vertex_path.parent / vpath).resolve()
        if not vpath.exists():
            continue

        ref_ast = parse_vertex_file(vpath)
        if ref_ast.store is None:
            continue

        sp = ref_ast.store
        if not sp.is_absolute():
            sp = (vpath.parent / sp).resolve()
        if sp.exists():
            store_paths.append(sp)

    return store_paths


def _resolve_discover_stores(ast: Any, vertex_path: Path) -> list[Path]:
    """Resolve discover glob to existing store paths from discovered instances."""
    from lang import parse_vertex_file

    if ast.discover is None:
        return []

    base_dir = vertex_path.parent
    store_paths: list[Path] = []
    for match in sorted(base_dir.glob(ast.discover)):
        if match.suffix != ".vertex":
            continue
        # Skip self
        if match.resolve() == vertex_path.resolve():
            continue
        try:
            ref_ast = parse_vertex_file(match)
        except Exception:
            continue
        if ref_ast.store is None:
            continue
        sp = ref_ast.store
        if not sp.is_absolute():
            sp = (match.parent / sp).resolve()
        if sp.exists():
            store_paths.append(sp)
    return store_paths


def _resolve_stores(ast: Any, vertex_path: Path) -> list[Path]:
    """Resolve store paths from combine or discover."""
    if ast.combine is not None:
        return _resolve_combine_stores(ast, vertex_path)
    if ast.discover is not None:
        return _resolve_discover_stores(ast, vertex_path)
    return []


def _infer_specs(ast: Any, vertex_path: Path) -> dict:
    """Get fold specs from the first referenced vertex when aggregation has none.

    Works for both combine (explicit vertex refs) and discover (glob pattern).
    """
    from lang import parse_vertex_file, resolve_vertex

    from .compiler import compile_vertex

    # Try combine entries first
    if ast.combine is not None:
        home = _loops_home()
        for entry in ast.combine:
            vpath = resolve_vertex(entry.name, home)
            if not vpath.is_absolute():
                vpath = (vertex_path.parent / vpath).resolve()
            if not vpath.exists():
                continue
            try:
                ref_ast = parse_vertex_file(vpath)
            except Exception:
                continue
            if ref_ast.loops:
                return compile_vertex(ref_ast)
        return {}

    # Try discover pattern
    if ast.discover is not None:
        base_dir = vertex_path.parent
        for match in sorted(base_dir.glob(ast.discover)):
            if match.suffix != ".vertex" or match.resolve() == vertex_path.resolve():
                continue
            try:
                ref_ast = parse_vertex_file(match)
            except Exception:
                continue
            if ref_ast.store is not None:
                return compile_vertex(ref_ast)

    return {}


def _open_combined(store_paths: list[Path]) -> tuple[sqlite3.Connection, list[str]]:
    """Open the first store and ATTACH the rest. Returns (conn, aliases).

    All databases are opened read-only via URI mode.
    """
    conn = sqlite3.connect(f"file:{store_paths[0]}?mode=ro", uri=True)
    aliases = ["main"]
    for i, path in enumerate(store_paths[1:], 1):
        alias = f"s{i}"
        assert alias.isidentifier() and alias.isascii(), f"Unsafe alias: {alias}"
        conn.execute(f"ATTACH DATABASE ? AS [{alias}]", (f"file:{path}?mode=ro",))
        aliases.append(alias)
    return conn, aliases


def _combined_read(
    ast: Any, vertex_path: Path, specs: dict
) -> dict[str, dict[str, Any]]:
    """Fold state across multiple stores (combinatorial vertex_read)."""
    store_paths = _resolve_stores(ast, vertex_path)
    if not store_paths:
        return {kind: spec.initial_state() for kind, spec in specs.items()}

    conn, aliases = _open_combined(store_paths)
    try:
        result: dict[str, dict[str, Any]] = {}
        for kind, spec in specs.items():
            # UNION ALL facts of this kind from all attached stores, ordered by ts.
            # NOTE: ORDER BY ts has undefined row order at timestamp ties across
            # stores — there is no global ordering column. For idempotent folds
            # (Upsert, Latest, Max, Min) this is harmless. For order-sensitive
            # folds (Collect, Window) ties may produce non-deterministic ordering.
            selects = [
                f"SELECT kind, ts, observer, origin, payload "
                f"FROM {'[' + a + '].' if a != 'main' else ''}facts "
                f"WHERE kind = ? OR kind LIKE ? || '.%'"
                for a in aliases
            ]
            sql = " UNION ALL ".join(selects) + " ORDER BY ts"
            params: list[Any] = []
            for _ in aliases:
                params.extend([kind, kind])

            rows = conn.execute(sql, params).fetchall()
            payloads = []
            for r in rows:
                p = json.loads(r[4])
                p["_ts"] = r[1]
                p["_observer"] = r[2]
                p["_origin"] = r[3] or ""
                payloads.append(p)
            result[kind] = spec.replay(payloads)
        return result
    finally:
        conn.close()


def _combined_facts(
    ast: Any,
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    kind: str | None = None,
) -> list[dict]:
    """Raw facts across multiple stores (combinatorial vertex_facts)."""
    store_paths = _resolve_stores(ast, vertex_path)
    if not store_paths:
        return []

    conn, aliases = _open_combined(store_paths)
    try:
        # See _combined_read for ts-tie ordering note.
        if kind is not None:
            selects = [
                f"SELECT kind, ts, observer, origin, payload "
                f"FROM {'[' + a + '].' if a != 'main' else ''}facts "
                f"WHERE ts >= ? AND ts <= ? AND (kind = ? OR kind LIKE ? || '.%')"
                for a in aliases
            ]
            sql = " UNION ALL ".join(selects) + " ORDER BY ts"
            params: list[Any] = []
            for _ in aliases:
                params.extend([since_ts, until_ts, kind, kind])
        else:
            selects = [
                f"SELECT kind, ts, observer, origin, payload "
                f"FROM {'[' + a + '].' if a != 'main' else ''}facts "
                f"WHERE ts >= ? AND ts <= ?"
                for a in aliases
            ]
            sql = " UNION ALL ".join(selects) + " ORDER BY ts"
            params = []
            for _ in aliases:
                params.extend([since_ts, until_ts])

        rows = conn.execute(sql, params).fetchall()
        return [
            {
                "kind": r[0],
                "ts": datetime.fromtimestamp(r[1], tz=timezone.utc),
                "observer": r[2],
                "origin": r[3],
                "payload": json.loads(r[4]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _combined_ticks(
    ast: Any,
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    name: str | None = None,
) -> list[Tick]:
    """Ticks across multiple stores (combinatorial vertex_ticks)."""
    store_paths = _resolve_stores(ast, vertex_path)
    if not store_paths:
        return []

    conn, aliases = _open_combined(store_paths)
    try:
        # See _combined_read for ts-tie ordering note.
        if name is not None:
            selects = [
                f"SELECT name, ts, since, origin, payload "
                f"FROM {'[' + a + '].' if a != 'main' else ''}ticks "
                f"WHERE ts >= ? AND ts <= ? AND name = ?"
                for a in aliases
            ]
            sql = " UNION ALL ".join(selects) + " ORDER BY ts"
            params: list[Any] = []
            for _ in aliases:
                params.extend([since_ts, until_ts, name])
        else:
            selects = [
                f"SELECT name, ts, since, origin, payload "
                f"FROM {'[' + a + '].' if a != 'main' else ''}ticks "
                f"WHERE ts >= ? AND ts <= ?"
                for a in aliases
            ]
            sql = " UNION ALL ".join(selects) + " ORDER BY ts"
            params = []
            for _ in aliases:
                params.extend([since_ts, until_ts])

        rows = conn.execute(sql, params).fetchall()
        return [
            Tick.from_dict({
                "name": r[0],
                "ts": r[1],
                "since": r[2],
                "origin": r[3],
                "payload": json.loads(r[4]),
            })
            for r in rows
        ]
    finally:
        conn.close()


def _combined_summary(ast: Any, vertex_path: Path) -> dict:
    """Merged summary across multiple stores (combinatorial vertex_summary)."""
    store_paths = _resolve_stores(ast, vertex_path)
    if not store_paths:
        return {"facts": {"total": 0, "kinds": {}}, "ticks": {"total": 0, "names": {}}}

    conn, aliases = _open_combined(store_paths)
    try:
        # Aggregate fact counts per kind
        selects_facts = [
            f"SELECT kind, COUNT(*), MIN(ts), MAX(ts) "
            f"FROM {'[' + a + '].' if a != 'main' else ''}facts GROUP BY kind"
            for a in aliases
        ]
        sql_facts = " UNION ALL ".join(selects_facts)
        rows = conn.execute(sql_facts).fetchall()

        # Merge per-kind stats (counts add, times take min/max)
        kind_stats: dict[str, dict] = {}
        total_facts = 0
        for kind, count, min_ts, max_ts in rows:
            total_facts += count
            if kind in kind_stats:
                existing = kind_stats[kind]
                existing["count"] += count
                existing["earliest"] = min(existing["earliest"], datetime.fromtimestamp(min_ts, tz=timezone.utc))
                existing["latest"] = max(existing["latest"], datetime.fromtimestamp(max_ts, tz=timezone.utc))
            else:
                kind_stats[kind] = {
                    "count": count,
                    "earliest": datetime.fromtimestamp(min_ts, tz=timezone.utc),
                    "latest": datetime.fromtimestamp(max_ts, tz=timezone.utc),
                }

        # Aggregate tick counts per name
        selects_ticks = [
            f"SELECT name, COUNT(*), MIN(ts), MAX(ts) "
            f"FROM {'[' + a + '].' if a != 'main' else ''}ticks GROUP BY name"
            for a in aliases
        ]
        sql_ticks = " UNION ALL ".join(selects_ticks)
        tick_rows = conn.execute(sql_ticks).fetchall()

        name_stats: dict[str, dict] = {}
        total_ticks = 0
        for tick_name, count, min_ts, max_ts in tick_rows:
            total_ticks += count
            if tick_name in name_stats:
                existing = name_stats[tick_name]
                existing["count"] += count
                existing["earliest"] = min(existing["earliest"], datetime.fromtimestamp(min_ts, tz=timezone.utc))
                existing["latest"] = max(existing["latest"], datetime.fromtimestamp(max_ts, tz=timezone.utc))
            else:
                name_stats[tick_name] = {
                    "count": count,
                    "earliest": datetime.fromtimestamp(min_ts, tz=timezone.utc),
                    "latest": datetime.fromtimestamp(max_ts, tz=timezone.utc),
                }

        return {
            "facts": {"total": total_facts, "kinds": kind_stats},
            "ticks": {"total": total_ticks, "names": name_stats},
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


def vertex_read(vertex_path: Path) -> dict[str, dict[str, Any]]:
    """Read fold state from a vertex's store.

    Parses the vertex file, compiles fold declarations to Specs,
    reads raw facts from the store, and replays through folds.

    Returns {kind: fold_state} where fold_state is the accumulated
    result of all facts of that kind replayed through the declared folds.

    If the vertex has no store or the store doesn't exist yet, returns
    initial (empty) fold state for each declared kind.

    Combinatorial vertices (with a ``combine`` block) virtualize reads
    across multiple stores using SQLite ATTACH DATABASE.
    """
    from lang import parse_vertex_file

    from .compiler import compile_vertex
    from .store_reader import StoreReader

    ast = parse_vertex_file(vertex_path)
    specs = compile_vertex(ast)

    # Combinatorial or aggregation vertex: read across multiple stores
    if ast.combine is not None or (ast.store is None and ast.discover is not None):
        if not specs:
            specs = _infer_specs(ast, vertex_path)
        return _combined_read(ast, vertex_path, specs)

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
                p["_origin"] = fact.get("origin", "")
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

    if ast.combine is not None or (ast.store is None and ast.discover is not None):
        return _combined_facts(ast, vertex_path, since_ts, until_ts, kind)

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

    if ast.combine is not None or (ast.store is None and ast.discover is not None):
        return _combined_ticks(ast, vertex_path, since_ts, until_ts, name)

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

    if ast.combine is not None or (ast.store is None and ast.discover is not None):
        return _combined_summary(ast, vertex_path)

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
