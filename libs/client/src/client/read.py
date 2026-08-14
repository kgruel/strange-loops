"""Headless read and query operations over Loops targets."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from engine.declaration import declaration_generation, load_declaration_status
from engine.handle import open_vertex
from engine.preflight import PreflightMode, read_preflight
from engine.store_reader import StoreReader
from engine.vertex_reader import (
    _combined_facts,
    _combined_summary,
    _combined_ticks,
    vertex_reindex,
    vertex_search,
)

from .target import resolve_target
from .types import (
    FactPageResult,
    FoldStateResult,
    ReadSummary,
    SearchResult,
    SearchResultItem,
    SyncResult,
    TargetUnsupported,
    TimelineEvent,
    TimelineResult,
)

__all__ = [
    "read_summary",
    "read_facts",
    "read_state",
    "read_ticks",
    "read_fact_by_id",
    "search_facts",
    "resolve_entity",
    "read_timeline",
    "sync_target",
]


def _ensure_reader(canonical_path: Path, index_path: Path) -> tuple[StoreReader, bool]:
    """Ensure the target store index is current and return an open StoreReader.

    Returns (StoreReader, agreement_boolean).
    """
    preflight = read_preflight(canonical_path, mode=PreflightMode.RECOVER_THEN_OPEN)
    if preflight.store is not None:
        preflight.store.close()
    return StoreReader(index_path), preflight.agreed


def read_summary(target: Path | str) -> ReadSummary:
    """Read domain-neutral statistical inventory of a target artifact.

    Accepts .vertex, .jsonl, .db, or .sqlite paths.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )

        if is_aggregate:
            summary_dict = _combined_summary(decl_ast, target_path)
            facts_info = summary_dict.get("facts", {})
            ticks_info = summary_dict.get("ticks", {})
            return ReadSummary(
                target_type="vertex",
                target_path=str(target_path),
                declaration_status=info.declaration_status,
                canonical_mode="aggregate",
                fact_total=facts_info.get("total", 0),
                tick_total=ticks_info.get("total", 0),
                kinds=facts_info.get("kinds", {}),
                ticks=ticks_info.get("names", {}),
                agreement=True,
            )

        if info.canonical_path is None or info.index_path is None or not info.canonical_path.exists():
            # Vertex without a store or store not yet created
            return ReadSummary(
                target_type=info.target_type,
                target_path=str(target_path),
                declaration_status=info.declaration_status,
                canonical_mode=info.canonical_mode,
                canonical_path=str(info.canonical_path) if info.canonical_path else None,
                index_path=str(info.index_path) if info.index_path else None,
            )

        reader, agreed = _ensure_reader(info.canonical_path, info.index_path)
        try:
            kind_stats = reader.fact_kind_stats()
            fact_total = reader.fact_total
            tick_total = reader.tick_total
            signed = reader.signed_counts()

            # Find latest timestamp across kinds
            latest_ts = None
            for s in kind_stats.values():
                ts = s["latest"].timestamp()
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts

            # Compare declared kinds with observed kinds
            declared_kinds = set(decl_ast.loops.keys()) if decl_ast and hasattr(decl_ast, "loops") else set()
            observed_kinds = set(kind_stats.keys())
            unfolded = sorted(observed_kinds - declared_kinds)

            # Format kind stats for summary
            kinds_summary = {
                k: {
                    "count": v["count"],
                    "earliest": v["earliest"].isoformat(),
                    "latest": v["latest"].isoformat(),
                }
                for k, v in kind_stats.items()
            }

            return ReadSummary(
                target_type=info.target_type,
                target_path=str(target_path),
                canonical_mode=info.canonical_mode,
                canonical_path=str(info.canonical_path),
                index_path=str(info.index_path),
                fact_total=fact_total,
                tick_total=tick_total,
                latest_ts=latest_ts,
                kinds=kinds_summary,
                agreement=agreed,
                declaration_status=info.declaration_status,
                unfolded_kinds=unfolded,
                signed_count=signed[0] if signed else None,
                unsigned_count=signed[1] if signed else None,
            )
        finally:
            reader.close()

    # Bare store (.jsonl or .db/.sqlite)
    canonical = info.canonical_path or target_path
    index = info.index_path or target_path
    if not canonical.exists():
        return ReadSummary(
            target_type=info.target_type,
            target_path=str(target_path),
            canonical_mode=info.canonical_mode,
            canonical_path=str(canonical),
            index_path=str(index),
        )

    reader, agreed = _ensure_reader(canonical, index)
    try:
        kind_stats = reader.fact_kind_stats()
        fact_total = reader.fact_total
        tick_total = reader.tick_total
        signed = reader.signed_counts()

        latest_ts = None
        for s in kind_stats.values():
            ts = s["latest"].timestamp()
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts

        kinds_summary = {
            k: {
                "count": v["count"],
                "earliest": v["earliest"].isoformat(),
                "latest": v["latest"].isoformat(),
            }
            for k, v in kind_stats.items()
        }

        return ReadSummary(
            target_type=info.target_type,
            target_path=str(target_path),
            canonical_mode=info.canonical_mode,
            canonical_path=str(canonical),
            index_path=str(index),
            fact_total=fact_total,
            tick_total=tick_total,
            latest_ts=latest_ts,
            kinds=kinds_summary,
            agreement=agreed,
            signed_count=signed[0] if signed else None,
            unsigned_count=signed[1] if signed else None,
        )
    finally:
        reader.close()


def read_facts(
    target: Path | str,
    *,
    limit: int = 100,
    before: Any | None = None,
    after: Any | None = None,
    kind: str | None = None,
    observer: str | None = None,
    include_internal: bool = False,
    order: str = "newest",
) -> FactPageResult:
    """Read a bounded page of facts from a target using witness-axis pagination."""
    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        if decl_ast is not None and (decl_ast.combine is not None or decl_ast.discover is not None):
            raw_facts = _combined_facts(
                decl_ast,
                target_path,
                0.0,
                float("inf"),
                kind=kind,
                include_internal=include_internal,
            )
            if observer is not None:
                raw_facts = [f for f in raw_facts if f.get("observer") == observer]
            if order == "newest":
                raw_facts = list(reversed(raw_facts))
            capped = raw_facts[:limit]
            return FactPageResult(
                items=capped,
                next_cursor=None,
                truncated=len(raw_facts) > limit,
                order=order,
            )

    if info.canonical_path is None or info.index_path is None or not info.canonical_path.exists():
        return FactPageResult(items=[], truncated=False, order=order)

    reader, _ = _ensure_reader(info.canonical_path, info.index_path)
    try:
        page = reader.query_facts(
            limit=limit,
            before=before,
            after=after,
            kind=kind,
            observer=observer,
            include_internal=include_internal,
            order=order,
        )
        return FactPageResult(
            items=page.items,
            next_cursor=page.next,
            truncated=page.truncated,
            order=page.order,
        )
    finally:
        reader.close()


def _serialize_fold_item(item: Any) -> dict[str, Any]:
    edges = getattr(item, "edges", ())
    return {
        "payload": dict(item.payload),
        "ts": item.ts,
        "observer": item.observer,
        "origin": item.origin,
        "id": item.id,
        "n": item.n,
        "refs": list(item.refs) if hasattr(item, "refs") else [],
        "edges": [{"predicate": e.predicate, "address": e.address} for e in edges],
    }


def _serialize_fold_section(section: Any) -> dict[str, Any]:
    return {
        "kind": section.kind,
        "fold_type": section.fold_type,
        "key_field": section.key_field,
        "count": section.count,
        "scalars": dict(section.scalars),
        "preview_fields": list(section.preview_fields),
        "items": [_serialize_fold_item(it) for it in section.items],
        "sections": [_serialize_fold_section(sub) for sub in section.sections],
    }


def read_state(target: Path | str, *, kind: str | None = None) -> FoldStateResult:
    """Read the current declared fold state of a vertex."""
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"read_state requires a .vertex target, got {info.target_type}")

    target_path = Path(target).resolve()
    handle = open_vertex(target_path)
    try:
        snap = handle.snapshot
        status = snap.status
        gen = declaration_generation(target_path)

        sections = {
            s.kind: _serialize_fold_section(s)
            for s in snap.fold.sections
            if kind is None or s.kind == kind
        }

        return FoldStateResult(
            vertex_name=target_path.stem,
            target_path=str(target_path),
            declaration_status=status,
            generation=gen,
            sections=sections,
        )
    finally:
        handle.close()


def read_ticks(target: Path | str, *, name: str | None = None) -> list[dict[str, Any]]:
    """Read ticks from a target store."""
    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        if decl_ast is not None and (decl_ast.combine is not None or decl_ast.discover is not None):
            return _combined_ticks(decl_ast, target_path, name=name)

    if info.canonical_path is None or info.index_path is None or not info.canonical_path.exists():
        return []

    reader, _ = _ensure_reader(info.canonical_path, info.index_path)
    try:
        ticks = reader.ticks_between(0.0, float("inf"), name=name)
        return [t.to_dict() for t in ticks]
    finally:
        reader.close()


def read_fact_by_id(target: Path | str, fact_id: str) -> dict[str, Any] | None:
    """Read a specific fact by full ID or prefix."""
    info = resolve_target(target)
    if info.canonical_path is None or info.index_path is None or not info.canonical_path.exists():
        return None

    reader, _ = _ensure_reader(info.canonical_path, info.index_path)
    try:
        return reader.fact_by_id(fact_id)
    finally:
        reader.close()


def search_facts(
    target: Path | str,
    query: str,
    *,
    kind: str | None = None,
    limit: int = 50,
) -> SearchResult:
    """Perform indexed full-text search against observation payloads.

    Parameters:
        target: Path to target .vertex or store artifact.
        query: FTS5 query string.
        kind: Optional kind filter.
        limit: Maximum results to return (default 50).

    Returns:
        SearchResult containing matches and rankings.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        if decl_ast is None:
            return SearchResult(query=query, matches=[], total_matches=0)

        try:
            raw_matches = vertex_search(target_path, query, kind=kind, limit=limit)
        except Exception:
            return SearchResult(query=query, matches=[], total_matches=0)

        matches = [
            SearchResultItem(
                id=m["id"],
                kind=m["kind"],
                ts=m["ts"],
                observer=m.get("observer", ""),
                origin=m.get("origin", ""),
                payload=dict(m.get("payload", {})),
                rank=float(m.get("rank", 0.0)),
                snippet=m.get("snippet", ""),
            )
            for m in raw_matches
        ]
        return SearchResult(query=query, matches=matches, total_matches=len(matches))

    # Bare store (.jsonl or .db)
    if info.canonical_path is None or info.index_path is None or not info.canonical_path.exists():
        return SearchResult(query=query, matches=[], total_matches=0)

    reader, _ = _ensure_reader(info.canonical_path, info.index_path)
    try:
        try:
            raw_matches = reader.search_facts(query, kind=kind, limit=limit)
        except Exception:
            return SearchResult(query=query, matches=[], total_matches=0)

        matches = [
            SearchResultItem(
                id=m["id"],
                kind=m["kind"],
                ts=m["ts"],
                observer=m.get("observer", ""),
                origin=m.get("origin", ""),
                payload=dict(m.get("payload", {})),
                rank=float(m.get("rank", 0.0)),
                snippet=m.get("snippet", ""),
            )
            for m in raw_matches
        ]
        return SearchResult(query=query, matches=matches, total_matches=len(matches))
    finally:
        reader.close()


def resolve_entity(
    target: Path | str,
    kind: str,
    key: str,
    value: str,
) -> str | None:
    """Resolve a domain business key to its canonical fact ULID.

    Parameters:
        target: Path to target artifact.
        kind: Fact kind name.
        key: Payload key field (e.g. 'task_id').
        value: Entity key value (e.g. 'TASK-100').

    Returns:
        Canonical fact ID string, or None if not resolved.
    """
    info = resolve_target(target)
    if info.canonical_path is None or info.index_path is None or not info.canonical_path.exists():
        return None

    reader, _ = _ensure_reader(info.canonical_path, info.index_path)
    try:
        return reader.resolve_entity_id(kind, key, value)
    finally:
        reader.close()


def read_timeline(
    target: Path | str,
    *,
    start_ts: float | None = None,
    end_ts: float | None = None,
    limit: int = 100,
) -> TimelineResult:
    """Read an interleaved chronological stream of facts and tick seals.

    Parameters:
        target: Path to target artifact.
        start_ts: Optional starting timestamp (inclusive).
        end_ts: Optional ending timestamp (inclusive).
        limit: Maximum total events to return (default 100).

    Returns:
        TimelineResult containing interleaved TimelineEvents.
    """
    info = resolve_target(target)
    if info.canonical_path is None or info.index_path is None or not info.canonical_path.exists():
        return TimelineResult(events=[], start_ts=start_ts, end_ts=end_ts, total_events=0)

    since = start_ts if start_ts is not None else 0.0
    until = end_ts if end_ts is not None else float("inf")

    reader, _ = _ensure_reader(info.canonical_path, info.index_path)
    try:
        facts = reader.facts_between(since, until)
        ticks = reader.ticks_between(since, until)

        events: list[TimelineEvent] = []
        for f in facts:
            events.append(
                TimelineEvent(
                    event_type="fact",
                    id=f["id"],
                    kind_or_name=f["kind"],
                    ts=f["ts"],
                    observer=f.get("observer", ""),
                    origin=f.get("origin", ""),
                    payload=dict(f.get("payload", {})),
                )
            )
        for t in ticks:
            events.append(
                TimelineEvent(
                    event_type="tick",
                    id=t.tick_id if hasattr(t, "tick_id") else "",
                    kind_or_name=t.name if hasattr(t, "name") else "",
                    ts=t.ts if hasattr(t, "ts") else 0.0,
                    observer="",
                    origin="",
                    payload=dict(t.payload) if hasattr(t, "payload") and t.payload else {},
                )
            )

        events.sort(key=lambda e: e.ts)
        capped = events[:limit]

        return TimelineResult(
            events=capped,
            start_ts=start_ts,
            end_ts=end_ts,
            total_events=len(capped),
        )
    finally:
        reader.close()


def sync_target(target: Path | str) -> SyncResult:
    """Synchronize and rebuild derived SQLite index and FTS tables.

    Parameters:
        target: Path to target .vertex, .jsonl, or .db artifact.

    Returns:
        SyncResult containing indexing status and duration.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()
    t0 = time.perf_counter()

    if info.target_type == "vertex":
        res = vertex_reindex(target_path)
        t1 = time.perf_counter()
        return SyncResult(
            target_path=str(target_path),
            status="synced" if res.get("reindexed", True) else "skipped",
            indexed_facts=res.get("facts_indexed", 0),
            agreement=True,
            duration_ms=(t1 - t0) * 1000.0,
        )

    # Bare store (.jsonl / .db)
    canonical = info.canonical_path or target_path
    if not canonical.exists():
        t1 = time.perf_counter()
        return SyncResult(
            target_path=str(target_path),
            status="missing",
            indexed_facts=0,
            agreement=False,
            duration_ms=(t1 - t0) * 1000.0,
        )

    preflight = read_preflight(canonical, mode=PreflightMode.RECOVER_THEN_OPEN)
    if preflight.store is not None:
        preflight.store.close()
    idx_path = info.index_path or canonical
    fact_count = 0
    if idx_path.exists():
        reader = StoreReader(idx_path)
        try:
            fact_count = reader.fact_total
        finally:
            reader.close()
    t1 = time.perf_counter()
    return SyncResult(
        target_path=str(target_path),
        status="synced",
        indexed_facts=fact_count,
        agreement=True,
        duration_ms=(t1 - t0) * 1000.0,
    )
