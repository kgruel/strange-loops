"""Domain-neutral read operations over Loops artifacts.

Provides headless query, statistics, witness pagination, state reconstruction,
and full-text search capabilities across `.vertex`, `.jsonl`, and `.db` stores.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.declaration import load_declaration_status
from engine.preflight import PreflightMode, read_preflight
from engine.store_reader import StoreReader
from engine.vertex_reader import (
    vertex_fact_by_id,
    vertex_facts,
    vertex_query_facts,
    vertex_read,
    vertex_reindex,
    vertex_search,
    vertex_summary,
    vertex_ticks,
)
from engine.witness import resolve_witness_position

from .target import resolve_target
from .types import (
    FactPageResult,
    FoldStateResult,
    ReadSummary,
    SdkError,
    SdkValueError,
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


def _compute_summary_stats(
    reader: StoreReader,
    *,
    include_internal: bool = False,
) -> tuple[int, int, float | None, dict[str, dict[str, Any]], tuple[int, int] | None]:
    """Extract factual totals, tick counts, time bounds, and attestation metrics."""
    raw_summary = reader.summary(include_internal=include_internal)
    fact_total = raw_summary.get("facts", {}).get("total", 0)
    tick_total = raw_summary.get("ticks", {}).get("total", 0)
    kinds_dict = raw_summary.get("facts", {}).get("kinds", {})

    all_latest: list[float] = []
    kinds: dict[str, dict[str, Any]] = {}
    for k, stats in kinds_dict.items():
        earliest_iso = stats.get("earliest")
        latest_iso = stats.get("latest")
        if latest_iso is not None:
            if isinstance(latest_iso, datetime):
                all_latest.append(latest_iso.timestamp())
            elif isinstance(latest_iso, (int, float)):
                all_latest.append(float(latest_iso))
            elif isinstance(latest_iso, str):
                with contextlib.suppress(ValueError, TypeError):
                    all_latest.append(datetime.fromisoformat(latest_iso).timestamp())
        kinds[k] = {
            "count": stats.get("count", 0),
            "earliest": earliest_iso,
            "latest": latest_iso,
        }

    latest_ts = max(all_latest) if all_latest else None
    signed_counts = reader.signed_counts()
    return fact_total, tick_total, latest_ts, kinds, signed_counts


def read_summary(
    target: Path | str,
    *,
    include_internal: bool = False,
) -> ReadSummary:
    """Read domain-neutral statistical inventory of a target artifact.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        include_internal: Whether to include reserved `_decl.*` kinds.

    Returns:
        ReadSummary containing fact/tick totals, kind distribution, and agreement.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, decl_status = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )

        if not is_aggregate and (info.canonical_path is None or not info.canonical_path.exists()):
            return ReadSummary(
                target_type="vertex",
                target_path=str(target_path),
                canonical_mode=info.canonical_mode or "unknown",
                canonical_path=str(info.canonical_path) if info.canonical_path else None,
                index_path=str(info.index_path) if info.index_path else None,
                declaration_status=decl_status or "unknown",
                fact_total=0,
                tick_total=0,
                latest_ts=None,
                kinds={},
                unfolded_kinds=[],
                agreement=True,
                signed_count=0,
                unsigned_count=0,
            )

        if is_aggregate:
            raw_sum = vertex_summary(target_path, include_internal=include_internal)
            fact_total = raw_sum.get("facts", {}).get("total", 0)
            tick_total = raw_sum.get("ticks", {}).get("total", 0)
            kinds_raw = raw_sum.get("facts", {}).get("kinds", {})
            kinds = {
                k: {
                    "count": v.get("count", 0),
                    "earliest": v.get("earliest"),
                    "latest": v.get("latest"),
                }
                for k, v in kinds_raw.items()
            }
            return ReadSummary(
                target_type="vertex",
                target_path=str(target_path),
                canonical_mode=info.canonical_mode or "aggregate",
                canonical_path=str(info.canonical_path) if info.canonical_path else None,
                index_path=str(info.index_path) if info.index_path else None,
                declaration_status=decl_status or "aggregate-head",
                fact_total=fact_total,
                tick_total=tick_total,
                latest_ts=None,
                kinds=kinds,
                unfolded_kinds=[],
                agreement=True,
                signed_count=0,
                unsigned_count=fact_total,
            )

        canonical = info.canonical_path or target_path
        index_path = info.index_path or canonical
        reader, agreed = _ensure_reader(canonical, index_path)
        try:
            fact_total, tick_total, latest_ts, kinds, signed_counts = _compute_summary_stats(
                reader, include_internal=include_internal
            )
            unfolded = [
                k
                for k in kinds
                if decl_ast is not None and k not in decl_ast.loops and not k.startswith("_decl.")
            ]
            # signed_counts is (signed, TOTAL) — unsigned is the difference
            signed_count = signed_counts[0] if signed_counts else 0
            unsigned_count = (signed_counts[1] - signed_counts[0]) if signed_counts else 0

            return ReadSummary(
                target_type="vertex",
                target_path=str(target_path),
                canonical_mode=info.canonical_mode or "unknown",
                canonical_path=str(canonical),
                index_path=str(index_path),
                declaration_status=decl_status or "unknown",
                fact_total=fact_total,
                tick_total=tick_total,
                latest_ts=latest_ts,
                kinds=kinds,
                unfolded_kinds=unfolded,
                agreement=agreed,
                signed_count=signed_count,
                unsigned_count=unsigned_count,
            )
        finally:
            reader.close()

    # Bare store (.jsonl or .db)
    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, agreed = _ensure_reader(canonical, index_path)
    try:
        fact_total, tick_total, latest_ts, kinds, signed_counts = _compute_summary_stats(
            reader, include_internal=include_internal
        )
        # signed_counts is (signed, TOTAL) — unsigned is the difference
        signed_count = signed_counts[0] if signed_counts else 0
        unsigned_count = (signed_counts[1] - signed_counts[0]) if signed_counts else 0

        return ReadSummary(
            target_type=info.target_type,
            target_path=str(target_path),
            canonical_mode=info.canonical_mode or "unknown",
            canonical_path=str(canonical),
            index_path=str(index_path),
            declaration_status=None,
            fact_total=fact_total,
            tick_total=tick_total,
            latest_ts=latest_ts,
            kinds=kinds,
            unfolded_kinds=[],
            agreement=agreed,
            signed_count=signed_count,
            unsigned_count=unsigned_count,
        )
    finally:
        reader.close()


def read_facts(
    target: Path | str,
    *,
    limit: int = 50,
    kind: str | None = None,
    observer: str | None = None,
    order: str = "newest",
    before: str | None = None,
    after: str | None = None,
    include_internal: bool = False,
) -> FactPageResult:
    """Read a bounded page of facts with stable witness pagination cursors.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        limit: Maximum number of facts to return.
        kind: Optional kind filter.
        observer: Optional observer identity filter.
        order: Sort order ('newest' for descending rowid, 'oldest' for ascending rowid).
        before: Cursor token to fetch rows before (older than) the cursor in newest order.
        after: Cursor token to fetch rows after (newer than) the cursor in oldest order.
        include_internal: Whether to include internal `_decl.*` facts.

    Returns:
        FactPageResult containing deserialized fact items and pagination metadata.
    """
    if order not in ("newest", "oldest"):
        raise SdkValueError(f"invalid order '{order}': expected 'newest' or 'oldest'")

    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )

        if is_aggregate:
            # Multi-store aggregate vertex
            all_facts = vertex_facts(
                target_path,
                since_ts=0.0,
                until_ts=float("inf"),
                kind=kind,
                observer=observer,
                include_internal=include_internal,
            )
            if order == "newest":
                all_facts = list(reversed(all_facts))

            capped = all_facts[:limit]
            truncated = len(all_facts) > len(capped)
            return FactPageResult(
                items=capped,
                next_cursor=None,
                prev_cursor=None,
                truncated=truncated,
                order=order,
            )

        if info.canonical_path is None or not info.canonical_path.exists():
            return FactPageResult(
                items=[],
                next_cursor=None,
                prev_cursor=None,
                truncated=False,
                order=order,
            )

        # Witness resolution reads the sqlite index, not the (possibly jsonl)
        # canonical log — passing the canonical raised DatabaseError on
        # jsonl-canonical vertices.
        witness_store = info.index_path or info.canonical_path
        before_pos = resolve_witness_position(witness_store, before) if before else None
        after_pos = resolve_witness_position(witness_store, after) if after else None

        page = vertex_query_facts(
            target_path,
            limit=limit,
            before=before_pos,
            after=after_pos,
            kind=kind,
            observer=observer,
            include_internal=include_internal,
            order=order,
        )
        next_tok = page.next.fact_id or f"seq:{page.next.seq}" if page.next is not None else None
        prev_tok = (
            page.prev.fact_id or f"seq:{page.prev.seq}"
            if getattr(page, "prev", None) is not None
            else None
        )
        return FactPageResult(
            items=page.items,
            next_cursor=next_tok,
            prev_cursor=prev_tok,
            truncated=page.truncated,
            order=order,
        )

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical

    reader, _ = _ensure_reader(canonical, index_path)
    try:
        # Same as the vertex branch: witness cursors resolve against the sqlite
        # index — after _ensure_reader, which builds it for bare jsonl targets.
        before_pos = resolve_witness_position(index_path, before) if before else None
        after_pos = resolve_witness_position(index_path, after) if after else None

        page = reader.query_facts(
            limit=limit,
            before=before_pos,
            after=after_pos,
            kind=kind,
            observer=observer,
            include_internal=include_internal,
            order=order,
        )
        next_tok = page.next.fact_id or f"seq:{page.next.seq}" if page.next is not None else None
        prev_tok = (
            page.prev.fact_id or f"seq:{page.prev.seq}"
            if getattr(page, "prev", None) is not None
            else None
        )

        return FactPageResult(
            items=page.items,
            next_cursor=next_tok,
            prev_cursor=prev_tok,
            truncated=page.truncated,
            order=order,
        )
    finally:
        reader.close()


def _tick_as_dict(t: Any) -> dict[str, Any]:
    """Serialize a tick record: engine's Tick exposes to_dict(), not as_dict().

    The old ``dict(t)`` fallback raised TypeError on every real fired Tick.
    """
    if hasattr(t, "as_dict"):
        return t.as_dict()
    if hasattr(t, "to_dict"):
        return t.to_dict()
    return dict(t)


def _serialize_fold_item(item: Any) -> Any:
    """Serialize fold state item values cleanly."""
    if hasattr(item, "predicate") and hasattr(item, "address"):
        return {"predicate": item.predicate, "address": item.address}
    if hasattr(item, "as_dict"):
        return item.as_dict()
    if isinstance(item, Mapping):
        return {str(k): _serialize_fold_item(v) for k, v in item.items()}
    if hasattr(item, "__dict__"):
        return {str(k): _serialize_fold_item(v) for k, v in vars(item).items()}
    if isinstance(item, (list, tuple)):
        return [_serialize_fold_item(x) for x in item]
    return item


def _serialize_fold_section(section: Any) -> dict[str, Any]:
    """Serialize a single kind fold state section."""
    if hasattr(section, "as_dict"):
        raw = section.as_dict()
    elif isinstance(section, Mapping):
        raw = dict(section)
    elif hasattr(section, "__dict__"):
        raw = vars(section)
    else:
        raw = {"value": section}

    serialized: dict[str, Any] = {}
    for k, v in raw.items():
        serialized[str(k)] = _serialize_fold_item(v)
    return serialized


def read_state(
    target: Path | str,
    *,
    kind: str | None = None,
    observer: str | None = None,
) -> FoldStateResult:
    """Reconstruct live fold state by replaying facts through declared vertex folds.

    Parameters:
        target: Path to .vertex artifact.
        kind: Optional single-kind filter.
        observer: Optional observer view filter.

    Returns:
        FoldStateResult containing reconstructed state sections and generation info.
    """
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"read_state requires a .vertex target, got {info.target_type}")

    target_path = Path(target).resolve()
    decl_ast, decl_status = load_declaration_status(target_path)
    vertex_path = target_path

    if info.canonical_path is None or not info.canonical_path.exists():
        return FoldStateResult(
            vertex_name=decl_ast.name if decl_ast else vertex_path.stem,
            target_path=str(vertex_path),
            declaration_status=decl_status or "unknown",
            generation={},
            sections={},
        )

    state_dict = vertex_read(vertex_path, observer=observer)
    if not isinstance(state_dict, dict):
        state_dict = {}

    sections: dict[str, Any] = {}
    for sec_name, sec_val in state_dict.items():
        if kind is not None and sec_name != kind:
            continue
        sections[sec_name] = _serialize_fold_section(sec_val)

    gen = getattr(decl_ast, "generation", {}) if decl_ast else {}

    return FoldStateResult(
        vertex_name=decl_ast.name if decl_ast else vertex_path.stem,
        target_path=str(vertex_path),
        declaration_status=decl_status or "unknown",
        generation=gen.as_dict() if hasattr(gen, "as_dict") else gen,
        sections=sections,
    )


def read_ticks(
    target: Path | str,
    *,
    name: str | None = None,
) -> list[dict[str, Any]]:
    """Read chronological tick seals and cadence boundaries.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        name: Optional tick mark name filter.

    Returns:
        List of deserialized tick records in chronological order.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )
        if is_aggregate:
            ticks = vertex_ticks(target_path, 0.0, float("inf"), name=name)
            return [_tick_as_dict(t) for t in ticks]

        if info.canonical_path is None or not info.canonical_path.exists():
            return []

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, _ = _ensure_reader(canonical, index_path)
    try:
        ticks = reader.ticks_between(0.0, float("inf"), name=name)
        return [_tick_as_dict(t) for t in ticks]
    finally:
        reader.close()


def read_fact_by_id(
    target: Path | str,
    fact_id: str,
) -> dict[str, Any] | None:
    """Locate and return a single fact by its ULID identifier.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        fact_id: ULID or ID string of the target fact.

    Returns:
        Deserialized fact dictionary, or None if not found.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )
        if is_aggregate:
            return vertex_fact_by_id(target_path, fact_id)

        if info.canonical_path is None or not info.canonical_path.exists():
            return None

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, _ = _ensure_reader(canonical, index_path)
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
    """Execute full-text search (FTS5) over fact payloads.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        query: Full-text search expression.
        kind: Optional kind filter.
        limit: Maximum number of matching items.

    Returns:
        SearchResult containing ranked SearchResultItem matches.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()

    matches: list[SearchResultItem] = []
    if info.target_type == "vertex":
        try:
            raw_matches = vertex_search(target_path, query, kind=kind, limit=limit)
            for m in raw_matches:
                payload = m.payload if hasattr(m, "payload") else m.get("payload", {})
                if isinstance(payload, str):
                    import contextlib
                    import json

                    with contextlib.suppress(Exception):
                        payload = json.loads(payload)
                m_ts = m.ts if hasattr(m, "ts") else m.get("ts", 0.0)
                m_ts_val = m_ts.timestamp() if hasattr(m_ts, "timestamp") else float(m_ts or 0.0)
                m_obs = str(m.observer if hasattr(m, "observer") else m.get("observer", ""))
                m_orig = str(m.origin if hasattr(m, "origin") else m.get("origin", ""))
                m_rank = float(m.rank if hasattr(m, "rank") else m.get("rank", 0.0))
                m_snip = str(m.snippet if hasattr(m, "snippet") else m.get("snippet", ""))
                matches.append(
                    SearchResultItem(
                        id=str(m.id if hasattr(m, "id") else m.get("id", "")),
                        kind=str(m.kind if hasattr(m, "kind") else m.get("kind", "")),
                        ts=m_ts_val,
                        observer=m_obs,
                        origin=m_orig,
                        payload=dict(payload) if isinstance(payload, Mapping) else {},
                        rank=m_rank,
                        snippet=m_snip,
                    )
                )
            return SearchResult(
                query=query,
                matches=matches,
                total_matches=len(matches),
            )
        except Exception as exc:
            raise SdkError(f"full-text search failed on {target_path}: {exc}") from exc

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, _ = _ensure_reader(canonical, index_path)
    try:
        if reader.fts_generation() is None:
            return SearchResult(
                query=query,
                matches=[],
                total_matches=0,
            )

        raw_matches = reader.search_facts(query, kind=kind, limit=limit)
        for m in raw_matches:
            payload = m.payload if hasattr(m, "payload") else m.get("payload", {})
            if isinstance(payload, str):
                with contextlib.suppress(Exception):
                    payload = json.loads(payload)
            m_ts = m.ts if hasattr(m, "ts") else m.get("ts", 0.0)
            m_ts_val = m_ts.timestamp() if hasattr(m_ts, "timestamp") else float(m_ts or 0.0)
            m_obs = str(m.observer if hasattr(m, "observer") else m.get("observer", ""))
            m_orig = str(m.origin if hasattr(m, "origin") else m.get("origin", ""))
            m_rank = float(m.rank if hasattr(m, "rank") else m.get("rank", 0.0))
            m_snip = str(m.snippet if hasattr(m, "snippet") else m.get("snippet", ""))
            matches.append(
                SearchResultItem(
                    id=str(m.id if hasattr(m, "id") else m.get("id", "")),
                    kind=str(m.kind if hasattr(m, "kind") else m.get("kind", "")),
                    ts=m_ts_val,
                    observer=m_obs,
                    origin=m_orig,
                    payload=dict(payload) if isinstance(payload, Mapping) else {},
                    rank=m_rank,
                    snippet=m_snip,
                )
            )
        return SearchResult(
            query=query,
            matches=matches,
            total_matches=len(matches),
        )
    except Exception as exc:
        raise SdkError(f"full-text search failed on {target_path}: {exc}") from exc
    finally:
        reader.close()


def resolve_entity(
    target: Path | str,
    kind: str,
    key: str,
    value: str,
) -> str | None:
    """Resolve an entity key to its latest fact ID.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        kind: Target kind name.
        key: Primary key field name.
        value: Entity key value.

    Returns:
        Fact ID string if resolved, or None.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )
        if is_aggregate:
            # Aggregate entity resolution over all combined member stores
            all_facts = vertex_facts(target_path, since_ts=0.0, until_ts=float("inf"), kind=kind)
            for f in reversed(all_facts):
                p = f.get("payload", {})
                if str(p.get(key)) == str(value):
                    return f.get("id")
            return None

        if info.canonical_path is None or not info.canonical_path.exists():
            return None

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, _ = _ensure_reader(canonical, index_path)
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
    order: str = "oldest",
) -> TimelineResult:
    """Read an interleaved, chronological stream of both facts and sealed ticks.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        start_ts: Optional lower timestamp bound (inclusive).
        end_ts: Optional upper timestamp bound (inclusive).
        limit: Maximum number of events to return.
        order: Sort order ('oldest' for chronological, 'newest' for reverse chronological).

    Returns:
        TimelineResult containing merged events with honest total counts and truncation markers.
    """
    if order not in ("oldest", "newest"):
        raise SdkValueError(f"invalid order '{order}': expected 'oldest' or 'newest'")

    info = resolve_target(target)
    target_path = Path(target).resolve()
    events: list[TimelineEvent] = []

    since = start_ts if start_ts is not None else 0.0
    until = end_ts if end_ts is not None else float("inf")

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )

        if is_aggregate or (info.canonical_path is not None and info.canonical_path.exists()):
            raw_facts = vertex_facts(target_path, since_ts=since, until_ts=until)
            for f in raw_facts:
                f_ts = (
                    f["ts"].timestamp()
                    if hasattr(f.get("ts"), "timestamp")
                    else float(f.get("ts", 0.0))
                )
                events.append(
                    TimelineEvent(
                        event_type="fact",
                        id=f.get("id", ""),
                        kind_or_name=f.get("kind", ""),
                        ts=f_ts,
                        observer=f.get("observer", ""),
                        origin=f.get("origin", ""),
                        payload=dict(f.get("payload", {})),
                    )
                )

            raw_ticks = vertex_ticks(target_path, since, until)
            for t in raw_ticks:
                t_ts = (
                    t.ts.timestamp()
                    if hasattr(t, "ts") and hasattr(t.ts, "timestamp")
                    else float(getattr(t, "ts", 0.0) if hasattr(t, "ts") else t.get("ts", 0.0))
                )
                t_id = getattr(t, "tick_id", getattr(t, "id", ""))
                t_name = getattr(t, "name", "")
                events.append(
                    TimelineEvent(
                        event_type="tick",
                        id=t_id,
                        kind_or_name=t_name,
                        ts=t_ts,
                        observer="",
                        origin="",
                        payload=dict(t.payload)
                        if hasattr(t, "payload") and t.payload
                        else dict(t.get("payload", {})),
                    )
                )

            events.sort(key=lambda e: e.ts, reverse=(order == "newest"))
            total_events = len(events)
            capped = events[:limit]
            truncated = total_events > len(capped)

            return TimelineResult(
                events=capped,
                start_ts=start_ts,
                end_ts=end_ts,
                total_events=total_events,
                truncated=truncated,
                order=order,
            )

        return TimelineResult(
            events=[],
            start_ts=start_ts,
            end_ts=end_ts,
            total_events=0,
            truncated=False,
            order=order,
        )

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, _ = _ensure_reader(canonical, index_path)
    try:
        raw_facts = reader.facts_between(since_ts=since, until_ts=until)
        ticks = reader.ticks_between(since, until)

        for f in raw_facts:
            f_ts = (
                f["ts"].timestamp()
                if hasattr(f.get("ts"), "timestamp")
                else float(f.get("ts", 0.0))
            )
            events.append(
                TimelineEvent(
                    event_type="fact",
                    id=f.get("id", ""),
                    kind_or_name=f.get("kind", ""),
                    ts=f_ts,
                    observer=f.get("observer", ""),
                    origin=f.get("origin", ""),
                    payload=dict(f.get("payload", {})),
                )
            )

        for t in ticks:
            t_ts = (
                t.ts.timestamp()
                if hasattr(t, "ts") and hasattr(t.ts, "timestamp")
                else float(getattr(t, "ts", 0.0) if hasattr(t, "ts") else t.get("ts", 0.0))
            )
            t_id = getattr(t, "tick_id", getattr(t, "id", ""))
            t_name = getattr(t, "name", "")
            events.append(
                TimelineEvent(
                    event_type="tick",
                    id=t_id,
                    kind_or_name=t_name,
                    ts=t_ts,
                    observer="",
                    origin="",
                    payload=dict(t.payload)
                    if hasattr(t, "payload") and t.payload
                    else dict(t.get("payload", {})),
                )
            )

        events.sort(key=lambda e: e.ts, reverse=(order == "newest"))
        total_events = len(events)
        capped = events[:limit]
        truncated = total_events > len(capped)

        return TimelineResult(
            events=capped,
            start_ts=start_ts,
            end_ts=end_ts,
            total_events=total_events,
            truncated=truncated,
            order=order,
        )
    finally:
        reader.close()


def sync_target(target: Path | str) -> SyncResult:
    """Synchronize and rebuild derived SQLite index and FTS tables.

    Parameters:
        target: Path to target .vertex, .jsonl, or .db artifact.

    Returns:
        SyncResult containing indexing status, fact count, and verified agreement.
    """
    info = resolve_target(target)
    target_path = Path(target).resolve()
    t0 = time.perf_counter()

    if info.target_type == "vertex":
        res = vertex_reindex(target_path)
        # Same agreement check as the bare-store branch below — the old
        # hardcoded agreement=True silently hid canonical/index drift.
        # Aggregates carry no canonical/index pair, so there the claim is
        # vacuously true.
        agreed = True
        if info.canonical_path is not None and info.canonical_path.exists():
            preflight = read_preflight(info.canonical_path, mode=PreflightMode.RECOVER_THEN_OPEN)
            if preflight.store is not None:
                preflight.store.close()
            agreed = preflight.agreed
        t1 = time.perf_counter()
        return SyncResult(
            target_path=str(target_path),
            status="synced" if res.get("reindexed", False) else "unindexed",
            indexed_facts=res.get("facts_indexed", 0),
            agreement=agreed,
            duration_ms=(t1 - t0) * 1000.0,
        )

    # Bare store (.jsonl or .db)
    canonical = info.canonical_path or target_path
    preflight = read_preflight(canonical, mode=PreflightMode.RECOVER_THEN_OPEN)
    if preflight.store is not None:
        preflight.store.close()

    idx_path = info.index_path or canonical
    fact_count = 0
    if idx_path.exists():
        reader = StoreReader(idx_path)
        try:
            total_val = reader.fact_total
            fact_count = total_val() if callable(total_val) else total_val
        finally:
            reader.close()

    t1 = time.perf_counter()
    return SyncResult(
        target_path=str(target_path),
        status="synced",
        indexed_facts=fact_count,
        agreement=preflight.agreed,
        duration_ms=(t1 - t0) * 1000.0,
    )
