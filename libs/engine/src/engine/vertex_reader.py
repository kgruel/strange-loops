"""Vertex reader — query-time fold materialization.

The sole read interface for store data. Compiles the vertex declaration,
replays facts through declared folds, returns fold state.

StoreReader is an internal detail — callers use vertex_read(),
vertex_facts(), vertex_ticks(), and vertex_summary() instead.
"""

from __future__ import annotations

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
