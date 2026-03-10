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
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .observer import observer_matches
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


def _child_topology_entry(ref_ast: Any, vpath: Path, base_dir: Path) -> dict:
    """Build a topology entry dict for a single child vertex."""
    from lang.ast import FoldBy

    kind_keys: dict[str, str] = {}
    for kind_name, loop_def in ref_ast.loops.items():
        for fold_decl in loop_def.folds:
            if isinstance(fold_decl.op, FoldBy):
                kind_keys[kind_name] = fold_decl.op.key_field
                break

    store_str = ""
    if ref_ast.store is not None:
        sp = ref_ast.store
        if not sp.is_absolute():
            sp = (vpath.parent / sp).resolve()
        store_str = str(sp)

    try:
        rel_path = str(vpath.relative_to(base_dir))
    except ValueError:
        rel_path = str(vpath)

    return {
        "name": ref_ast.name,
        "path": rel_path,
        "store": store_str,
        "kind_keys": kind_keys,
    }


def _collect_topology_info(ast: Any, vertex_path: Path) -> list[dict]:
    """Collect topology info for each child vertex in a discover/combine walk.

    Returns a list of dicts with keys: name, path, store, kind_keys.
    """
    from lang import parse_vertex_file, resolve_vertex

    children: list[dict] = []
    base_dir = vertex_path.parent

    if ast.discover is not None:
        for match in sorted(base_dir.glob(ast.discover)):
            if match.suffix != ".vertex" or match.resolve() == vertex_path.resolve():
                continue
            try:
                ref_ast = parse_vertex_file(match)
            except Exception:
                continue
            children.append(_child_topology_entry(ref_ast, match, base_dir))

    elif ast.combine is not None:
        home = _loops_home()
        for entry in ast.combine:
            vpath = resolve_vertex(entry.name, home)
            if not vpath.is_absolute():
                vpath = (base_dir / vpath).resolve()
            if not vpath.exists():
                continue
            try:
                ref_ast = parse_vertex_file(vpath)
            except Exception:
                continue
            children.append(_child_topology_entry(ref_ast, vpath, base_dir))

    return children


def emit_topology(vertex_path: Path) -> None:
    """Walk discover/combine children and emit _topology facts to the aggregation's store.

    Each discovered child becomes a _topology fact with name, path, store,
    and kind_keys. Uses upsert fold (by name), so re-emission is idempotent.

    Requires the vertex to have a store declaration.
    """
    from lang import parse_vertex_file

    ast = parse_vertex_file(vertex_path)
    if ast.store is None:
        return

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    children = _collect_topology_info(ast, vertex_path)
    if not children:
        return

    from .sqlite_store import SqliteStore

    store = SqliteStore(
        path=store_path,
        serialize=lambda d: d,
        deserialize=lambda d: d,
    )

    try:
        ts = _time.time()
        for child in children:
            store.append({
                "kind": "_topology",
                "ts": ts,
                "observer": ast.name,
                "origin": "",
                "payload": child,
            })
    finally:
        store.close()


class ConflictingFoldSpec(Exception):
    """Two source vertices declare the same kind with different fold specs."""

    def __init__(self, kind: str, source_a: str, source_b: str) -> None:
        self.kind = kind
        super().__init__(
            f"Conflicting fold spec for '{kind}' from '{source_a}' and '{source_b}'. "
            f"Add an explicit '{kind}' declaration to the aggregation vertex to resolve."
        )


def _specs_match(a: Any, b: Any) -> bool:
    """Check if two Specs have equivalent fold declarations.

    Compares fold ops (type + parameters) — the part that determines
    how facts accumulate. Ignores name/about metadata.
    """
    if len(a.folds) != len(b.folds):
        return False
    for fa, fb in zip(a.folds, b.folds):
        if type(fa) is not type(fb):
            return False
        # Compare fold-relevant attributes (key for Upsert, limit for Collect)
        if hasattr(fa, "key") and fa.key != fb.key:
            return False
        if hasattr(fa, "limit") and fa.limit != fb.limit:
            return False
    return True


def _collect_source_specs(
    ast: Any, vertex_path: Path, *, override_kinds: frozenset[str] = frozenset()
) -> dict:
    """Collect fold specs from all source vertices, erroring on conflicts.

    Union semantics: all source kinds are included. When two sources
    declare the same kind with matching fold specs, it passes through.
    When they conflict (same kind, different fold), raises
    ConflictingFoldSpec — the aggregation vertex must explicitly declare
    an override to resolve.

    Kinds in *override_kinds* are skipped during conflict detection —
    the aggregation vertex's own declaration will take precedence.
    """
    from lang import parse_vertex_file, resolve_vertex

    from .compiler import compile_vertex

    merged: dict = {}
    # Track which source each kind came from (for error messages)
    source_of: dict[str, str] = {}

    def _merge_from(ref_ast: Any, source_name: str) -> None:
        if not ref_ast.loops:
            return
        source_specs = compile_vertex(ref_ast)
        for kind, spec in source_specs.items():
            if kind in merged:
                if kind in override_kinds:
                    pass  # Aggregation will override — skip conflict check
                elif not _specs_match(merged[kind], spec):
                    raise ConflictingFoldSpec(kind, source_of[kind], source_name)
                # Matching specs or overridden — keep existing
            else:
                merged[kind] = spec
                source_of[kind] = source_name

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
            _merge_from(ref_ast, entry.name)

    elif ast.discover is not None:
        base_dir = vertex_path.parent
        for match in sorted(base_dir.glob(ast.discover)):
            if match.suffix != ".vertex" or match.resolve() == vertex_path.resolve():
                continue
            try:
                ref_ast = parse_vertex_file(match)
            except Exception:
                continue
            _merge_from(ref_ast, match.stem)

    return merged


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
    ast: Any, vertex_path: Path, specs: dict, *, observer: str | None = None
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
                f"SELECT id, kind, ts, observer, origin, payload "
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
                if observer and not observer_matches(r[3], observer):
                    continue
                p = json.loads(r[5])
                p["_id"] = r[0]
                p["_ts"] = r[2]
                p["_observer"] = r[3]
                p["_origin"] = r[4] or ""
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
                f"SELECT id, kind, ts, observer, origin, payload "
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
                f"SELECT id, kind, ts, observer, origin, payload "
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
                "id": r[0],
                "kind": r[1],
                "ts": datetime.fromtimestamp(r[2], tz=timezone.utc),
                "observer": r[3],
                "origin": r[4],
                "payload": json.loads(r[5]),
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


def _combined_search(
    ast: Any,
    vertex_path: Path,
    query: str,
    *,
    kind: str | None = None,
    since: float | None = None,
    until: float | None = None,
    limit: int = 100,
    observer: str | None = None,
) -> list[dict]:
    """Search across combined children by delegating vertex_search to each child."""
    from lang import resolve_vertex

    home = _loops_home()
    all_results: list[dict] = []

    entries = ast.combine or []
    if not entries and ast.discover is not None:
        # discover vertices also resolve through _resolve_stores
        store_paths = _resolve_stores(ast, vertex_path)
        # For discover, we don't have vertex paths — fall back to empty
        # (discover children need their own vertex files for search fields)
        if not store_paths:
            return []
        # Can't recurse without vertex paths; discover is not yet supported for search
        return []

    for entry in entries:
        vpath = resolve_vertex(entry.name, home)
        if not vpath.is_absolute():
            vpath = (vertex_path.parent / vpath).resolve()
        if not vpath.exists():
            continue

        child_results = vertex_search(
            vpath, query, kind=kind, since=since, until=until,
            limit=limit, observer=observer,
        )
        all_results.extend(child_results)

    # Sort by ts descending (newest first), apply limit
    all_results.sort(key=lambda f: f["ts"], reverse=True)
    return all_results[:limit]


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


def vertex_read(
    vertex_path: Path, *, observer: str | None = None
) -> dict[str, dict[str, Any]]:
    """Read fold state from a vertex's store.

    Parses the vertex file, compiles fold declarations to Specs,
    reads raw facts from the store, and replays through folds.

    When *observer* is provided, only facts from that observer are
    included in the fold replay — each observer gets their own view
    of accumulated state.

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

    # Combinatorial or aggregation vertex: read across multiple stores.
    # Auto-inherit: source specs are the base, aggregation specs override.
    if ast.combine is not None or ast.discover is not None:
        source_specs = _collect_source_specs(
            ast, vertex_path, override_kinds=frozenset(specs)
        )
        # Source specs as base, aggregation specs override
        merged = {**source_specs, **specs}
        result = _combined_read(ast, vertex_path, merged, observer=observer)

        # Aggregation with own store: overlay self-knowledge from own store
        if ast.store is not None:
            own_store = ast.store
            if not own_store.is_absolute():
                own_store = (vertex_path.parent / own_store).resolve()
            if own_store.exists():
                with StoreReader(own_store) as reader:
                    for kind, spec in specs.items():
                        facts = reader.facts_by_kind(kind)
                        if observer:
                            facts = [f for f in facts if observer_matches(f["observer"], observer)]
                        payloads = []
                        for fact in facts:
                            p = dict(fact["payload"])
                            p["_ts"] = fact["ts"]
                            p["_observer"] = fact["observer"]
                            p["_origin"] = fact.get("origin", "")
                            p["_id"] = fact.get("id")
                            payloads.append(p)
                        result[kind] = spec.replay(payloads)

        return result

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
            if observer:
                facts = [f for f in facts if observer_matches(f["observer"], observer)]
            # Inject fact metadata into payloads for folds that need it
            # (_ts for Latest fold, _observer for potential future use)
            payloads = []
            for fact in facts:
                p = dict(fact["payload"])
                p["_ts"] = fact["ts"]
                p["_observer"] = fact["observer"]
                p["_origin"] = fact.get("origin", "")
                p["_id"] = fact.get("id")
                payloads.append(p)
            result[kind] = spec.replay(payloads)
        return result


def vertex_fold(
    vertex_path: Path,
    *,
    observer: str | None = None,
    kind: str | None = None,
) -> Any:
    """Read fold state as a typed ``FoldState``.

    This is the primary read interface for fold state — returns a typed
    contract (``FoldState`` from atoms) instead of raw dicts.

    Parses the vertex declaration for fold metadata (fold_type, key_field,
    declaration order), replays facts through specs, and produces typed
    ``FoldItem``/``FoldSection`` objects with metadata separated from payload.

    When *observer* is provided, only that observer's facts are folded.
    When *kind* is provided, only that kind is included.
    """
    from atoms import FoldItem, FoldSection, FoldState
    from atoms.fold import Collect, Upsert
    from lang import parse_vertex_file

    ast = parse_vertex_file(vertex_path)
    raw = vertex_read(vertex_path, observer=observer)

    # Declaration order from AST, not alphabetical
    if kind:
        ordered_kinds = [kind]
    else:
        declared = list(ast.loops.keys())
        undeclared = [k for k in raw if k not in ast.loops]
        ordered_kinds = declared + undeclared

    from .compiler import compile_vertex

    specs = compile_vertex(ast)
    # For combine/discover vertices, merge source specs so fold metadata
    # (fold_type, key_field) is available for inherited kinds too.
    if ast.combine is not None or ast.discover is not None:
        source_specs = _collect_source_specs(
            ast, vertex_path, override_kinds=frozenset(specs)
        )
        specs = {**source_specs, **specs}

    sections: list[FoldSection] = []
    for kind_name in ordered_kinds:
        state = raw.get(kind_name, {})

        # Extract fold metadata from compiled spec
        fold_type = "collect"
        key_field = None
        spec = specs.get(kind_name)
        if spec and spec.folds:
            fold_op = spec.folds[0]
            if isinstance(fold_op, Upsert):
                fold_type = "by"
                key_field = fold_op.key
            elif isinstance(fold_op, Collect):
                fold_type = "collect"

        # Extract items from fold state using the spec's target name
        # (not hardcoded "items" — any target name works)
        if spec and spec.folds:
            items_raw = state.get(spec.folds[0].target, state)
        else:
            items_raw = state

        # Normalize items to list[dict], then convert to typed FoldItems
        if fold_type == "by" and isinstance(items_raw, dict):
            raw_items = [dict(v) for v in items_raw.values()]
        elif isinstance(items_raw, list):
            raw_items = [dict(v) for v in items_raw]
        else:
            raw_items = [dict(items_raw)] if items_raw else []

        items = tuple(_dict_to_fold_item(d) for d in raw_items)

        # Extract scalar fold targets (count, updated, sum, etc.)
        # — everything in the fold state that isn't the items target
        scalars: dict[str, Any] = {}
        if spec and spec.folds:
            items_target = spec.folds[0].target
            for fold_op in spec.folds[1:]:
                val = state.get(fold_op.target)
                if val is not None:
                    scalars[fold_op.target] = val

        sections.append(FoldSection(
            kind=kind_name,
            items=items,
            fold_type=fold_type,
            key_field=key_field,
            scalars=scalars,
        ))

    return FoldState(sections=tuple(sections), vertex=ast.name)


def _dict_to_fold_item(d: dict) -> Any:
    """Convert a raw fold output dict to a typed FoldItem.

    Separates metadata (_ts, _observer, _origin, _id) from payload fields.
    """
    from atoms import FoldItem

    ts = d.pop("_ts", None)
    observer = d.pop("_observer", "")
    origin = d.pop("_origin", "")
    fact_id = d.pop("_id", None)
    return FoldItem(payload=d, ts=ts, observer=observer, origin=origin, id=fact_id)


def vertex_fact_by_id(
    vertex_path: Path,
    id_prefix: str,
) -> dict | None:
    """Look up a single fact by ID or ID prefix from a vertex's store.

    For combinatorial vertices, searches across all combined stores.
    Returns None if not found. Raises ValueError on ambiguous prefix.
    """
    from .store_reader import StoreReader

    ast, store_path = _resolve_store(vertex_path)

    # Combinatorial/aggregation vertex: search across stores
    if ast.combine is not None or ast.discover is not None:
        store_paths = _resolve_stores(ast, vertex_path)
        matches: list[dict] = []
        for sp in store_paths:
            try:
                with StoreReader(sp) as reader:
                    result = reader.fact_by_id(id_prefix)
                    if result is not None:
                        matches.append(result)
            except (FileNotFoundError, ValueError):
                continue
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous ID prefix '{id_prefix}' — matches across multiple stores"
            )
        return matches[0]

    if store_path is None:
        return None

    with StoreReader(store_path) as reader:
        return reader.fact_by_id(id_prefix)


def vertex_facts(
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    kind: str | None = None,
    observer: str | None = None,
) -> list[dict]:
    """Read raw facts from a vertex's store within a time range.

    When *observer* is provided, only facts from that observer are returned.

    For queries that need raw facts (e.g. log), not fold state.
    Still goes through the vertex — the vertex knows where its store is.
    """
    from lang import parse_vertex_file

    from .store_reader import StoreReader

    ast = parse_vertex_file(vertex_path)

    if ast.combine is not None or ast.discover is not None:
        facts = _combined_facts(ast, vertex_path, since_ts, until_ts, kind)
    elif ast.store is None:
        facts = []
    else:
        store_path = ast.store
        if not store_path.is_absolute():
            store_path = (vertex_path.parent / store_path).resolve()

        if not store_path.exists():
            facts = []
        else:
            with StoreReader(store_path) as reader:
                facts = reader.facts_between(since_ts, until_ts, kind=kind)

    if observer:
        facts = [f for f in facts if observer_matches(f["observer"], observer)]
    return facts


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

    if ast.combine is not None or ast.discover is not None:
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

    if ast.combine is not None or ast.discover is not None:
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


def _extract_field(payload: dict, field: str) -> str:
    """Extract a search field value from a payload, handling nested paths and polymorphic values.

    Supports:
    - Flat fields: ``"prompt"`` → ``payload["prompt"]``
    - Dot paths: ``"message.content"`` → ``payload["message"]["content"]``
    - String values: returned directly
    - List of dicts: extracts ``"text"`` from each element, concatenates
    - List of strings: concatenated
    - Dict values: JSON-serialized (fallback)
    - Missing fields: empty string
    """
    # Traverse dot path
    value: Any = payload
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return ""
        if value is None:
            return ""

    # Resolve polymorphic value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return " ".join(parts)
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


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
            text = " ".join(_extract_field(payload, f) for f in fields)
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
    observer: str | None = None,
) -> list[dict]:
    """Search fact payloads in a vertex's store via FTS5.

    Uses spec-declared search fields — only kinds with a ``search``
    declaration in the vertex file are indexed. Empty query returns nothing.

    When *observer* is provided, only facts from that observer are returned.

    Args:
        vertex_path: Path to the .vertex file.
        query: FTS5 query string (words, phrases, prefix, boolean).
        kind: Filter by fact kind (exact match on FTS metadata).
        since: Only facts with ts >= since.
        until: Only facts with ts <= until.
        limit: Maximum results (default 100).
        observer: Filter to facts from this observer.

    Returns:
        Matching facts, newest first. Same shape as vertex_facts.
    """
    if not query or not query.strip():
        return []

    from lang import parse_vertex_file

    from .compiler import collect_search_fields
    from .store_reader import StoreReader

    ast = parse_vertex_file(vertex_path)

    if ast.combine is not None or ast.discover is not None:
        return _combined_search(
            ast, vertex_path, query,
            kind=kind, since=since, until=until, limit=limit, observer=observer,
        )

    if ast.store is None:
        return []

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    if not store_path.exists():
        return []

    base_dir = vertex_path.parent
    search_fields = collect_search_fields(ast, base_dir)
    if not search_fields:
        return []

    _ensure_fts(store_path, search_fields)

    with StoreReader(store_path) as reader:
        facts = reader.search_facts(
            query, kind=kind, since=since, until=until, limit=limit
        )
        if observer:
            facts = [f for f in facts if observer_matches(f["observer"], observer)]
        return facts
