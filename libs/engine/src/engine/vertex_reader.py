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
from typing import TYPE_CHECKING, Any

from .declaration import load_declaration, load_declaration_status
from .observer import observer_matches

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .witness import WitnessPosition


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
    from lang import resolve_vertex

    children: list[dict] = []
    base_dir = vertex_path.parent

    if ast.discover is not None:
        for match in sorted(base_dir.glob(ast.discover)):
            if match.suffix != ".vertex" or match.resolve() == vertex_path.resolve():
                continue
            try:
                ref_ast = load_declaration(match)
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
                ref_ast = load_declaration(vpath)
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
    ast = load_declaration(vertex_path)
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
    ast: Any,
    vertex_path: Path,
    *,
    override_kinds: frozenset[str] = frozenset(),
    as_of: float | None = None,
) -> dict:
    """Collect fold specs from all source vertices, erroring on conflicts.

    Union semantics: all source kinds are included. When two sources
    declare the same kind with matching fold specs, it passes through.
    When they conflict (same kind, different fold), raises
    ConflictingFoldSpec — the aggregation vertex must explicitly declare
    an override to resolve.

    Kinds in *override_kinds* are skipped during conflict detection —
    the aggregation vertex's own declaration will take precedence.

    ``as_of`` resolves each MEMBER declaration at the same event-time cutoff
    (equal-cursor semantics, review finding 6): an aggregate without its own
    loops replays ``ts<=T`` member facts, and those must fold under the member
    ontology in force AT T — not head, which could carry a fold-key rename
    introduced after T. (Membership itself stays current — the disclosed
    aggregate-head derogation; only the ontology rides the cutoff.)
    """
    from lang import resolve_vertex

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
                ref_ast = load_declaration(vpath, as_of=as_of)
            except Exception:
                continue
            _merge_from(ref_ast, entry.name)

    elif ast.discover is not None:
        base_dir = vertex_path.parent
        for match in sorted(base_dir.glob(ast.discover)):
            if match.suffix != ".vertex" or match.resolve() == vertex_path.resolve():
                continue
            try:
                ref_ast = load_declaration(match, as_of=as_of)
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
    ast: Any, vertex_path: Path, specs: dict, *, observer: str | None = None,
    return_payloads: bool = False,
    until_ts: float | None = None,
) -> "dict[str, dict[str, Any]] | tuple[dict[str, dict[str, Any]], dict[str, list[dict]]]":
    """Fold state across multiple stores (combinatorial vertex_read).

    Fetches all facts in a single SQL query across attached stores,
    then groups by kind and replays through specs. Single query avoids
    the SQLite cold-start penalty (~10ms) that would hit the first of
    N per-kind queries.

    When ``return_payloads=True``, returns ``(raw_state, kind_payloads)``
    so callers can use the per-kind payload lists for retain_facts /
    source_facts population without re-querying the stores.

    ``until_ts`` (0.8.0 fold-state-``as_of``, A9) caps every member's facts
    to ``ts <= until_ts`` — the event-time projection over an aggregate.
    Membership itself stays CURRENT file state regardless (aggregation
    internal tables are not yet built, the shipped "aggregate-head" honesty
    marker) — only the facts axis is cut by the cursor.
    """
    store_paths = _resolve_stores(ast, vertex_path)
    if not store_paths:
        empty_raw = {kind: spec.initial_state() for kind, spec in specs.items()}
        if return_payloads:
            return empty_raw, {k: [] for k in specs}
        return empty_raw

    conn, aliases = _open_combined(store_paths)
    try:
        # Single query for all facts, fold-replay-ordered by (ts, id) —
        # event order with the ULID as deterministic tie-break, the same
        # total order the engine replay paths use. Store- and merge-order
        # independent, so combined reads re-fold identically regardless of
        # which store a fact lives in.
        ts_clause = " WHERE ts <= ?" if until_ts is not None else ""
        selects = [
            f"SELECT id, kind, ts, observer, origin, payload "
            f"FROM {'[' + a + '].' if a != 'main' else ''}facts{ts_clause}"
            for a in aliases
        ]
        sql = " UNION ALL ".join(selects)
        params = (until_ts,) * len(aliases) if until_ts is not None else ()

        rows = conn.execute(sql, params).fetchall()
        # Sort in Python — avoids SQLite index scan for ORDER BY ts
        # which causes random I/O (~14ms vs ~1ms for unsorted read).
        rows.sort(key=lambda r: (r[2], r[0]))

        # Build kind → spec lookup, including sub-kind (dot-prefix) routing.
        # "thread.foo" → "thread" if "thread" is a spec kind.
        spec_kinds = set(specs)
        kind_payloads: dict[str, list] = {k: [] for k in specs}

        for r in rows:
            kind = r[1]
            if observer and not observer_matches(r[3], observer):
                continue
            # Exact match
            if kind in spec_kinds:
                target = kind
            else:
                # Sub-kind: "foo.bar" → check "foo"
                dot = kind.find(".")
                if dot < 0:
                    continue
                prefix = kind[:dot]
                if prefix not in spec_kinds:
                    continue
                target = prefix
            p = json.loads(r[5])
            p["_id"] = r[0]
            p["_ts"] = r[2]
            p["_observer"] = r[3]
            p["_origin"] = r[4] or ""
            kind_payloads[target].append(p)

        raw = {
            kind: spec.replay(kind_payloads[kind])
            for kind, spec in specs.items()
        }
        if return_payloads:
            return raw, kind_payloads
        return raw
    finally:
        conn.close()


def _populate_source_facts(
    specs: dict, payloads_by_kind: dict[str, list[dict]],
    source_facts: dict[str, list[dict]],
) -> None:
    """Bucket per-kind payloads into ``source_facts[kind/key_value]``.

    Mutates ``source_facts`` in place. Handles upsert-fold kinds (which
    declare a key field); skips other fold types — they don't have a
    per-key bucket to attach to. Used by both the simple-store and
    combine branches of ``vertex_fold`` to keep retain_facts working
    consistently across vertex topologies.
    """
    from atoms.fold import Upsert

    for kind, spec in specs.items():
        if not spec.folds:
            continue
        fold_op = spec.folds[0]
        if not isinstance(fold_op, Upsert):
            continue
        for p in payloads_by_kind.get(kind, []):
            fk = f"{kind}/{p.get(fold_op.key, '')}"
            source_facts.setdefault(fk, []).append(p)


def _combined_facts(
    ast: Any,
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    kind: str | None = None,
    *,
    include_internal: bool = False,
) -> list[dict]:
    """Raw facts across multiple stores (combinatorial vertex_facts).

    Excludes the reserved ``_decl.*`` namespace by default (SPEC §9.4), same
    ``GLOB`` rule as the single-store path.
    """
    store_paths = _resolve_stores(ast, vertex_path)
    if not store_paths:
        return []

    conn, aliases = _open_combined(store_paths)
    try:
        internal_clause = "" if include_internal else " AND kind NOT GLOB '_decl.*'"
        # See _combined_read for ts-tie ordering note.
        if kind is not None:
            selects = [
                f"SELECT id, kind, ts, observer, origin, payload "
                f"FROM {'[' + a + '].' if a != 'main' else ''}facts "
                f"WHERE ts >= ? AND ts <= ? AND (kind = ? OR kind LIKE ? || '.%')"
                f"{internal_clause}"
                for a in aliases
            ]
            sql = " UNION ALL ".join(selects) + " ORDER BY ts, id"
            params: list[Any] = []
            for _ in aliases:
                params.extend([since_ts, until_ts, kind, kind])
        else:
            selects = [
                f"SELECT id, kind, ts, observer, origin, payload "
                f"FROM {'[' + a + '].' if a != 'main' else ''}facts "
                f"WHERE ts >= ? AND ts <= ?{internal_clause}"
                for a in aliases
            ]
            sql = " UNION ALL ".join(selects) + " ORDER BY ts, id"
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


def _member_labels(paths: list[Path]) -> dict[Path, str]:
    """Collision-free ``member`` labels for aggregate stores (review finding 3).

    The stem is the friendly default, but ``a/events.db`` and ``b/events.db``
    both stem to ``events`` — indistinguishable, so a consumer could resolve a
    tick's ``fact_cursor`` against the WRONG member store. Colliding stems are
    qualified with their parent directory name; if that still collides (same
    leaf dir under different roots), the whole set falls back to full resolved
    paths. Non-colliding stems stay short.
    """
    from collections import Counter

    stem_counts = Counter(p.stem for p in paths)
    labels: dict[Path, str] = {
        p: (p.stem if stem_counts[p.stem] == 1 else f"{p.parent.name}/{p.stem}")
        for p in paths
    }
    if len(set(labels.values())) < len(set(paths)):
        labels = {p: str(p.resolve()) for p in paths}
    return labels


def _combined_ticks(
    ast: Any,
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    name: str | None = None,
    *,
    with_envelope: bool = False,
) -> "list[Tick] | list[tuple[Tick, dict]]":
    """Ticks across multiple stores (combinatorial vertex_ticks).

    With ``with_envelope=True`` this pass-through carries each member's REAL
    attestation envelope (N4), tagged with ``member`` (a collision-free label
    for the source store — :func:`_member_labels`) — not the blank
    ``chained=False`` placeholder the aggregate returned before.
    A tick's ``fact_cursor`` is a witness handle into ITS OWN member store (A1:
    no shared witness order across the aggregate), so the envelope is resolved
    against that member's own connection and the ``member`` tag tells a consumer
    which store to anchor the cursor against (A9's per-member vector). This path
    opens one :class:`StoreReader` per member (N cold-starts) rather than the
    single ATTACH the fast fold path uses — correctness of per-member cursor
    resolution is worth the ~10ms, and only a ``--ticks`` drill pays it.
    """
    store_paths = _resolve_stores(ast, vertex_path)
    if not store_paths:
        return []

    if with_envelope:
        from .store_reader import StoreReader

        labels = _member_labels(store_paths)
        pairs: list[tuple[Tick, dict]] = []
        for path in store_paths:
            try:
                with StoreReader(path) as reader:
                    member_pairs = reader.ticks_between(
                        since_ts, until_ts, name=name, with_envelope=True
                    )
            except FileNotFoundError:
                continue  # absent member store — skip, not a failure
            for tick, env in member_pairs:
                env["member"] = labels[path]
                pairs.append((tick, env))
        pairs.sort(key=lambda pair: pair[0].ts)
        return pairs

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
        from .tick import Tick  # deferred: not needed on fold path

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


def _combined_summary(
    ast: Any, vertex_path: Path, *, include_internal: bool = False
) -> dict:
    """Merged summary across multiple stores (combinatorial vertex_summary).

    Excludes the reserved ``_decl.*`` namespace by default (SPEC §9.4),
    same rule and same ``GLOB`` (not ``LIKE``) as the single-store path in
    :meth:`StoreReader.fact_kind_stats`.
    """
    store_paths = _resolve_stores(ast, vertex_path)
    if not store_paths:
        return {"facts": {"total": 0, "kinds": {}}, "ticks": {"total": 0, "names": {}}}

    conn, aliases = _open_combined(store_paths)
    try:
        # Aggregate fact counts per kind
        kind_where = "" if include_internal else "WHERE kind NOT GLOB '_decl.*'"
        selects_facts = [
            f"SELECT kind, COUNT(*), MIN(ts), MAX(ts) "
            f"FROM {'[' + a + '].' if a != 'main' else ''}facts {kind_where} GROUP BY kind"
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
    as_of: float | None = None,
) -> list[dict]:
    """Search across combined children by delegating vertex_search to each child.

    ``as_of`` is forwarded to each child (SPEC §9.3). The AGGREGATE's own
    declaration resolves head (its member-set history is not historized — a
    build-plan non-goal), but each child is a single store and MUST honor the
    cursor for its own ``search`` fields — ``as_of`` is a shared wall-clock
    ``ts``, so "as of T" resolves each child's declaration at T.
    """
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
            limit=limit, observer=observer, as_of=as_of,
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
    from .compiler import compile_vertex
    from .store_reader import StoreReader

    ast = load_declaration(vertex_path)
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


def _resolve_full_specs(ast: Any, vertex_path: Path) -> dict:
    """Compile specs for a vertex, merging source specs for combine/discover."""
    from .compiler import compile_vertex

    specs = compile_vertex(ast)
    if ast.combine is not None or ast.discover is not None:
        source_specs = _collect_source_specs(
            ast, vertex_path, override_kinds=frozenset(specs)
        )
        specs = {**source_specs, **specs}
    return specs


def _raw_to_fold_state(
    raw: dict[str, dict[str, Any]],
    ast: Any,
    specs: dict,
    *,
    kind: str | None = None,
    unfolded: dict[str, int] | None = None,
    source_facts: dict[str, list[dict]] | None = None,
) -> Any:
    """Convert a raw fold state dict to typed ``FoldState``.

    Shared conversion for both live fold reads (``vertex_fold``) and
    historical snapshots (tick payloads). The raw dict has the same shape
    as ``vertex_read()`` output: ``{kind_name: fold_state_for_kind}``.

    Items from tick payloads won't have ``_ts``/``_observer``/``_id`` metadata
    (those are injected during live reads but not stored in fold snapshots).
    The typed ``FoldItem`` fields will be None/empty in that case — the
    payload content is preserved either way.
    """
    from atoms import FoldSection, FoldState
    from atoms.fold import Collect, Upsert

    # Declaration order from AST, not alphabetical
    if kind:
        ordered_kinds = [kind]
    else:
        declared = list(ast.loops.keys())
        undeclared = [k for k in raw if k not in ast.loops]
        ordered_kinds = declared + undeclared

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
        # Scalar fold targets (Count, Sum) produce int/float — not item data
        if isinstance(items_raw, (int, float, str, bool)):
            raw_items = []
        elif fold_type == "by" and isinstance(items_raw, dict):
            raw_items = [dict(v) for v in items_raw.values()]
        elif isinstance(items_raw, list):
            raw_items = [dict(v) for v in items_raw]
        else:
            raw_items = [dict(items_raw)] if items_raw else []

        loop_def = ast.loops.get(kind_name)
        edge_specs = (
            tuple((e.field, e.target) for e in loop_def.edges)
            if loop_def is not None else ()
        )
        items = tuple(_dict_to_fold_item(d, edge_specs) for d in raw_items)

        # Extract scalar fold targets (count, updated, sum, etc.)
        # — everything in the fold state that isn't the items target
        scalars: dict[str, Any] = {}
        if spec and spec.folds:
            items_target = spec.folds[0].target
            for fold_op in spec.folds[1:]:
                val = state.get(fold_op.target)
                if val is not None:
                    scalars[fold_op.target] = val

        preview_fields = loop_def.preview_fields if loop_def is not None else ()

        sections.append(FoldSection(
            kind=kind_name,
            items=items,
            fold_type=fold_type,
            key_field=key_field,
            scalars=scalars,
            preview_fields=preview_fields,
            edge_fields=edge_specs,
        ))

    return FoldState(
        sections=tuple(sections),
        vertex=ast.name,
        unfolded=unfolded or {},
        source_facts=source_facts or {},
    )


def vertex_fold(
    vertex_path: Path,
    *,
    observer: str | None = None,
    kind: str | None = None,
    retain_facts: bool = False,
    at: WitnessPosition | None = None,
    as_of: float | None = None,
) -> Any:
    """Read fold state as a typed ``FoldState``.

    This is the primary read interface for fold state — returns a typed
    contract (``FoldState`` from atoms) instead of raw dicts.

    Parses the vertex declaration for fold metadata (fold_type, key_field,
    declaration order), replays facts through specs, and produces typed
    ``FoldItem``/``FoldSection`` objects with metadata separated from payload.

    When *observer* is provided, only that observer's facts are folded.
    When *kind* is provided, only that kind is included.

    Two mutually-exclusive historical selectors (A8) — passing both raises
    ``ValueError``:

    - ``at`` (a :class:`~engine.witness.WitnessPosition`, 0.8.0
      fold-state-as-of) reconstructs the fold at a witness position: the
      prefix ``rowid <= at.rowid`` is selected, ontology is resolved **from
      the same prefix** (equal cursors ⇒ one position for selection and
      ontology), and facts are replayed in ``(ts, id)`` order — a full
      reconstruction, never incremental application of an interval (a
      backdated arrival inserts early in replay). Returns a
      :class:`~engine.witness.WitnessFold` envelope (fold + resolved position
      + ``mode='witness'`` + honesty status) instead of a bare ``FoldState``,
      so the answering mode is machine-readable (A11). Per-store only:
      refused on aggregates (witness order is per-member, A1/A9).
    - ``as_of`` (event-time ``ts <= as_of`` projection, the explicit
      analytical mode — never the cursor default) selects facts by timestamp
      cutoff and resolves ontology via the existing ``load_declaration``
      ``as_of`` seam (equal ts cursors both axes). Allowed on aggregates
      (uniform event-time is well-posed — current membership, each member's
      facts cut by the same cutoff, matching the shipped facts-route
      behavior). Returns a bare ``FoldState`` — the caller pairs it with
      ``load_declaration_status(as_of=...)`` for the honesty status, as the
      existing stream/ticks fetches already do.

    ``None`` for both = head, returning a bare ``FoldState`` exactly as before.
    """
    from .compiler import compile_vertex

    if as_of is not None and at is not None:
        raise ValueError("vertex_fold: as_of and at are mutually exclusive (A8)")

    ast = load_declaration(vertex_path, as_of=as_of, at=at)
    if at is not None and (ast.combine is not None or ast.discover is not None):
        from .witness import WitnessAggregateUnsupported

        raise WitnessAggregateUnsupported(
            "vertex_fold: a witness position is per-store and cannot reconstruct "
            "a combine/discover aggregate fold — witness order is per-member "
            "(A1/A9). Fold a member store at its own position instead."
        )
    specs = compile_vertex(ast)

    # Resolve full specs (merge source specs for combine/discover).
    # When the main vertex declares its own loops, those ARE the fold
    # contracts — skip the child-spec walk (~2-3ms of parse+compile).
    # Only collect from children when the main vertex has no loops block,
    # meaning it relies entirely on child specs (union semantics).
    full_specs = dict(specs)
    if (ast.combine is not None or ast.discover is not None) and not specs:
        # as_of resolves member ontology at the cutoff (finding 6); at= is
        # already refused on aggregates above, so only as_of can reach here.
        source_specs = _collect_source_specs(
            ast, vertex_path, override_kinds=frozenset(specs), as_of=as_of
        )
        full_specs = {**source_specs, **specs}

    # Inline vertex_read logic — avoids redundant parse/compile
    unfolded: dict[str, int] = {}
    source_facts: dict[str, list[dict]] = {}
    if ast.combine is not None or ast.discover is not None:
        if retain_facts:
            raw, child_payloads = _combined_read(
                ast, vertex_path, full_specs,
                observer=observer, return_payloads=True, until_ts=as_of,
            )
            _populate_source_facts(full_specs, child_payloads, source_facts)
        else:
            raw = _combined_read(
                ast, vertex_path, full_specs, observer=observer, until_ts=as_of,
            )

        # Aggregation with own store: overlay self-knowledge
        if ast.store is not None:
            own_store = ast.store
            if not own_store.is_absolute():
                own_store = (vertex_path.parent / own_store).resolve()
            if own_store.exists():
                from .store_reader import StoreReader  # deferred: not needed for combine-only

                with StoreReader(own_store) as reader:
                    own_payloads_by_kind: dict[str, list[dict]] = {}
                    for k, spec in specs.items():
                        facts = reader.facts_by_kind(k, until_ts=as_of)
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
                        own_payloads_by_kind[k] = payloads
                        raw[k] = spec.replay(payloads)
                    if retain_facts:
                        _populate_source_facts(specs, own_payloads_by_kind, source_facts)
    elif ast.store is None:
        raw = {k: spec.initial_state() for k, spec in full_specs.items()}
    else:
        store_path = ast.store
        if not store_path.is_absolute():
            store_path = (vertex_path.parent / store_path).resolve()

        # A10: a witness position's rowid indexes THIS store's append order only.
        # Verify it was resolved against this store (or shares its lineage)
        # BEFORE applying at.rowid, so a position from another store can never
        # silently select an unrelated prefix here (review finding 1).
        if at is not None:
            from .witness import verify_position_for_store

            verify_position_for_store(at, store_path)

        if not store_path.exists():
            raw = {k: spec.initial_state() for k, spec in full_specs.items()}
        else:
            from .store_reader import StoreReader  # deferred: not needed for combine-only
            from atoms.fold import Upsert

            at_rowid = at.rowid if at is not None else None
            with StoreReader(store_path) as reader:
                raw = {}
                for k, spec in full_specs.items():
                    facts = reader.facts_by_kind(k, at_rowid=at_rowid, until_ts=as_of)
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

                    # Retain source facts grouped by fold position
                    if retain_facts and spec.folds:
                        fold_op = spec.folds[0]
                        if isinstance(fold_op, Upsert):
                            for p in payloads:
                                fk = f"{k}/{p.get(fold_op.key, '')}"
                                source_facts.setdefault(fk, []).append(p)

                    raw[k] = spec.replay(payloads)

                # Detect unfolded kinds — in store but not declared. Excludes
                # the reserved `_decl.*` namespace by default (SPEC §9.4 —
                # every read surface excludes it ambiently); an explicit
                # `--kind` request below is the escape hatch, not this footer.
                # Suppressed under a witness cursor OR an as_of projection: the
                # store-kind stats are head-scoped (no rowid/ts cutoff on the
                # GROUP BY), so showing them at a historical position would
                # leak head counts the prefix/cutoff never saw. The folded
                # sections themselves ARE prefix/cutoff-correct.
                if at is not None or as_of is not None:
                    unfolded = {}
                else:
                    store_kinds = reader.fact_kind_stats()
                    unfolded = {
                        k: v["count"]
                        for k, v in store_kinds.items()
                        if k not in full_specs
                    }

                # Explicit --kind for a kind no vertex declares a loop for:
                # fetch its raw facts directly rather than silently rendering
                # an empty section. General fallback, not `_decl.*`-specific —
                # mirrors `loops ls --kind NAME`'s existing declaration-bypass
                # behavior (fetch_kind_stat queries the store directly for any
                # kind string). This is how `--kind _decl.<x>` surfaces a
                # reserved-namespace kind on demand: an explicit ask overrides
                # the ambient default everywhere else in this module too.
                if kind is not None and kind not in full_specs:
                    facts = reader.facts_by_kind(kind, at_rowid=at_rowid, until_ts=as_of)
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
                    raw[kind] = payloads

    fold_state = _raw_to_fold_state(
        raw, ast, full_specs, kind=kind, unfolded=unfolded,
        source_facts=source_facts if retain_facts else None,
    )
    if at is None:
        return fold_state
    # Witness-mode read: wrap the fold in the machine-readable envelope so the
    # answering mode/status is a field, not only rendered text (A11). Status
    # comes from the ontology seam (file-pre-genesis on the dominant live
    # corpus — N3 — never a silent retro-claim).
    from .witness import WitnessFold

    _ast, status = load_declaration_status(vertex_path, at=at)
    return WitnessFold(fold=fold_state, position=at, mode="witness", status=status)


def vertex_tick_fold(
    vertex_path: Path,
    tick: "Tick",
    *,
    kind: str | None = None,
) -> Any:
    """Convert a tick's payload to typed ``FoldState``.

    The tick payload is a fold snapshot — the accumulated state at the
    boundary that produced this tick. This function converts it to the
    same typed contract that ``vertex_fold()`` returns, so existing lenses
    can render it.

    Items won't have ``_ts``/``_observer``/``_id`` metadata (not stored
    in fold snapshots). Content fields are preserved.

    SPEC §9.3 / Q5: the snapshot is authoritative and is NEVER re-folded — but
    it is *interpreted* (specs, key fields, edge declarations used to type and
    render it) under the ontology in force at the tick's own boundary,
    ``as_of = tick.ts``, not at head. A tick that fired before a fold-key
    rename renders under the old key. This is the one surface where "as of" is
    a property of the datum, not of the query.
    """
    tick_ts = tick.ts.timestamp() if hasattr(tick.ts, "timestamp") else float(tick.ts)
    ast = load_declaration(vertex_path, as_of=tick_ts)
    payload = tick.payload if isinstance(tick.payload, dict) else {}

    # Filter out tick-internal keys (e.g. _boundary)
    raw = {k: v for k, v in payload.items() if not k.startswith("_")}

    specs = _resolve_full_specs(ast, vertex_path)
    return _raw_to_fold_state(raw, ast, specs, kind=kind)


def _normalize_edge_address(value: str, target_kind: str) -> str:
    """Normalize a raw edge-field address to canonical ``kind:key`` form.

    A value already carrying a ``:`` is kind-qualified — kept verbatim. A bare
    value (``acme``, or a slashed key ``design/foo``) is qualified with the
    declared target kind (``person:acme``) so it walks and matches inbound the
    same way an explicit ``kind:key`` ref does. Empty parts are dropped.
    """
    v = value.strip()
    if not v:
        return ""
    if ":" in v:
        return v
    return f"{target_kind}:{v}"


def _lift_edges(payload: dict, edge_specs: tuple[tuple[str, str], ...]) -> tuple:
    """Lift declared edge fields from a folded payload into typed ``Edge``s.

    ``edge_specs`` are ``(field, target_kind)`` pairs from the kind's
    declaration. For each declared field present in the payload, the raw
    ADDRESS value (not the ``{field}_ref`` ULID pin) is comma-split and each
    part normalized to ``kind:key``. Predicate = field name. This is the
    read-time projection: overlay edges are the latest folded field value, so
    they are retroactive (historical facts light up on declaration) and
    emission-correctable (re-emit changes the value → the edge set changes).
    """
    from atoms import Edge

    edges: list = []
    for field_name, target_kind in edge_specs:
        raw = payload.get(field_name)
        if not isinstance(raw, str) or not raw.strip():
            continue
        for part in raw.split(","):
            addr = _normalize_edge_address(part, target_kind)
            if addr:
                edges.append(Edge(predicate=field_name, address=addr))
    return tuple(edges)


def _dict_to_fold_item(d: dict, edge_specs: tuple[tuple[str, str], ...] = ()) -> Any:
    """Convert a raw fold output dict to a typed FoldItem.

    Separates metadata (_ts, _observer, _origin, _id, _n, _refs) from payload.
    ``edge_specs`` (the kind's declared ``(field, target_kind)`` edges) lift
    declared payload fields into ``FoldItem.edges`` — a READ-TIME projection,
    computed AFTER metadata separation so it reads the folded content payload.
    """
    from atoms import FoldItem

    ts = d.pop("_ts", None)
    observer = d.pop("_observer", "")
    origin = d.pop("_origin", "")
    fact_id = d.pop("_id", None)
    n = d.pop("_n", 1)
    refs = tuple(d.pop("_refs", ()))
    edges = _lift_edges(d, edge_specs) if edge_specs else ()
    return FoldItem(
        payload=d, ts=ts, observer=observer, origin=origin,
        id=fact_id, n=n, refs=refs, edges=edges,
    )


def vertex_fact_by_id(
    vertex_path: Path,
    id_prefix: str,
    *,
    include_internal: bool = False,
    kind: str | None = None,
) -> dict | None:
    """Look up a single fact by ID or ID prefix from a vertex's store.

    For combinatorial vertices, searches across all combined stores.
    Returns None if not found. Raises ValueError on ambiguous prefix.
    ``include_internal`` is the explicit ``_decl.*`` defeat (SPEC §9.4) —
    reached from the CLI via ``--kind _decl.* --id ...``.
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
                    result = reader.fact_by_id(
                        id_prefix, include_internal=include_internal, kind=kind
                    )
                    if result is not None:
                        matches.append(result)
            except FileNotFoundError:
                continue  # absent member store — skip, not ambiguity
            # A ValueError is WITHIN-STORE prefix ambiguity — propagate;
            # swallowing it presented ambiguous data as absent
            # (branch-review round 3).
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
        # An explicit --kind SCOPES the lookup in SQL — including prefix
        # ambiguity resolution (branch-review round 2 #2).
        return reader.fact_by_id(
            id_prefix, include_internal=include_internal, kind=kind
        )


def vertex_facts(
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    kind: str | None = None,
    observer: str | None = None,
    *,
    include_internal: bool = False,
    as_of: float | None = None,
    at: WitnessPosition | None = None,
) -> list[dict]:
    """Read raw facts from a vertex's store within a time range.

    When *observer* is provided, only facts from that observer are returned.

    For queries that need raw facts (e.g. log), not fold state.
    Still goes through the vertex — the vertex knows where its store is.

    Excludes the reserved ``_decl.*`` namespace by default (SPEC §9.4);
    ``include_internal=True`` is the explicit escape hatch — callers
    threading a user-requested ``kind`` that targets the reserved namespace
    should set this, else the ambient exclusion filters out the very kind
    being asked for.

    Two mutually-exclusive historical selectors (A8):

    - ``as_of`` (SPEC §9.3, ontology-as-of) resolves the declaration at a
      historical ``ts`` cutoff — equal-cursors default ``as_of = until_ts``.
      Only store-resolution and the reserved-namespace exclusion ride it; the
      fact window stays ``since_ts..until_ts``.
    - ``at`` (a :class:`~engine.witness.WitnessPosition`, 0.8.0 cursor) caps the
      result to the witness prefix ``rowid <= at.rowid`` AND resolves ontology
      from that prefix — the facts the store had *received* at the position,
      inside the time window. Per-store only: refused on aggregates
      (:class:`~engine.witness.WitnessAggregateUnsupported`) — witness order is
      per-member (A1/A9).

    ``None`` for both = head (identical to pre-S5 behavior).
    """
    from .store_reader import StoreReader

    if as_of is not None and at is not None:
        raise ValueError(
            "vertex_facts: as_of and at are mutually exclusive (A8)"
        )

    ast = load_declaration(vertex_path, as_of=as_of, at=at)

    if ast.combine is not None or ast.discover is not None:
        if at is not None:
            from .witness import WitnessAggregateUnsupported

            raise WitnessAggregateUnsupported(
                "vertex_facts: a witness position is per-store and cannot select "
                "over a combine/discover aggregate — address a member store, or "
                "use as_of for a uniform event-time projection"
            )
        facts = _combined_facts(
            ast, vertex_path, since_ts, until_ts, kind,
            include_internal=include_internal,
        )
    elif ast.store is None:
        facts = []
    else:
        store_path = ast.store
        if not store_path.is_absolute():
            store_path = (vertex_path.parent / store_path).resolve()

        # A10: refuse a position from a different store before applying its
        # rowid here (review finding 1) — same guard as vertex_fold.
        if at is not None:
            from .witness import verify_position_for_store

            verify_position_for_store(at, store_path)

        if not store_path.exists():
            facts = []
        else:
            with StoreReader(store_path) as reader:
                facts = reader.facts_between(
                    since_ts, until_ts, kind=kind,
                    include_internal=include_internal,
                    at_rowid=at.rowid if at is not None else None,
                )

    if observer:
        facts = [f for f in facts if observer_matches(f["observer"], observer)]
    return facts


def vertex_ticks(
    vertex_path: Path,
    since_ts: float,
    until_ts: float,
    name: str | None = None,
    *,
    with_envelope: bool = False,
    as_of: float | None = None,
) -> list:
    """Read ticks from a vertex's store within a time range.

    Parallels vertex_facts for tick access through the vertex.
    Returns Tick objects (from StoreReader.ticks_between), or
    ``(Tick, envelope)`` pairs when ``with_envelope=True``.

    Combined/aggregation vertices carry each member's REAL envelope tagged with
    its source ``member`` (0.8.0, N4): the aggregate does not itself attest, but
    a member tick's chain/signature/cursor are per-store facts and are passed
    through honestly rather than blanked. The ``fact_cursor`` is a witness handle
    into that ``member`` store only — no shared aggregate witness order exists
    (A1) — so a consumer resolves it against the named member (A9's per-member
    vector).

    ``as_of`` (SPEC §9.3) resolves the declaration at a historical ``ts``
    cutoff — equal-cursors default is ``as_of = until_ts``. ``None`` = head.
    """
    from .store_reader import StoreReader

    ast = load_declaration(vertex_path, as_of=as_of)

    if ast.combine is not None or ast.discover is not None:
        if not with_envelope:
            return _combined_ticks(ast, vertex_path, since_ts, until_ts, name)
        return _combined_ticks(
            ast, vertex_path, since_ts, until_ts, name, with_envelope=True
        )

    if ast.store is None:
        return []

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    if not store_path.exists():
        return []

    with StoreReader(store_path) as reader:
        return reader.ticks_between(
            since_ts, until_ts, name=name, with_envelope=with_envelope
        )


def vertex_summary(vertex_path: Path, *, include_internal: bool = False) -> dict:
    """Read store summary from a vertex — fact/tick counts and per-kind stats.

    Returns the same shape as StoreReader.summary():
        {"facts": {"total": N, "kinds": {...}}, "ticks": {"total": N, "names": {...}}}

    Returns zeroed summary if the vertex has no store or store doesn't exist.

    Excludes the reserved ``_decl.*`` namespace from ``facts.kinds`` by
    default (SPEC §9.4); ``include_internal=True`` is the explicit escape
    hatch.
    """
    from .store_reader import StoreReader

    ast = load_declaration(vertex_path)

    if ast.combine is not None or ast.discover is not None:
        return _combined_summary(ast, vertex_path, include_internal=include_internal)

    if ast.store is None:
        return {"facts": {"total": 0, "kinds": {}}, "ticks": {"total": 0, "names": {}}}

    store_path = ast.store
    if not store_path.is_absolute():
        store_path = (vertex_path.parent / store_path).resolve()

    if not store_path.exists():
        return {"facts": {"total": 0, "kinds": {}}, "ticks": {"total": 0, "names": {}}}

    with StoreReader(store_path) as reader:
        return reader.summary(include_internal=include_internal)


def _resolve_store(vertex_path: Path) -> tuple[Any, Path | None]:
    """Resolve declaration and store path. Returns (ast, store_path).

    Routes through :func:`load_declaration` (not a plain parse) because callers
    consult the returned ast's declaration attributes (``combine``/``discover``)
    to branch, not only the ``store`` locator.
    """
    ast = load_declaration(vertex_path)
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
            # Advance the watermark for EVERY scanned row (rows are ORDER BY
            # rowid). A kind with no search declaration is still consumed — else
            # trailing non-searchable rows (e.g. the reserved `_decl.*`
            # declaration events an S4 re-absorb appends) sit above last_rowid
            # and get rescanned on every single search.
            max_rowid = rowid
            fields = search_fields.get(kind)
            if not fields:
                continue  # No search declaration — nothing to index for this kind.
            payload = json.loads(payload_json)
            text = " ".join(_extract_field(payload, f) for f in fields)
            if text.strip():
                conn.execute(
                    "INSERT INTO facts_fts(text_content, fact_rowid, kind, observer) "
                    "VALUES (?, ?, ?, ?)",
                    (text, rowid, kind, observer),
                )

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
    as_of: float | None = None,
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
        as_of: SPEC §9.3 ontology-as-of ``ts`` cutoff for declaration
            resolution — which ``search`` fields are indexed is the as-of
            ontology's. ``None`` = head. CAVEAT (Q2): the FTS index itself is
            built at head; ``until`` post-hoc window-filters the result set, so
            a historical search is honest about *which facts* fall in the
            window but the *index* it queries is the head kind set. A fully
            rewound index is 0.8.0 work.

    Returns:
        Matching facts, newest first. Same shape as vertex_facts.
    """
    if not query or not query.strip():
        return []

    from .compiler import collect_search_fields
    from .store_reader import StoreReader

    ast = load_declaration(vertex_path, as_of=as_of)

    if ast.combine is not None or ast.discover is not None:
        return _combined_search(
            ast, vertex_path, query,
            kind=kind, since=since, until=until, limit=limit, observer=observer,
            as_of=as_of,
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
