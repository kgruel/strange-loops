"""Headless read and query operations over Loops targets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.declaration import declaration_generation
from engine.handle import open_vertex
from engine.preflight import PreflightMode, read_preflight
from engine.store_reader import StoreReader
from engine.vertex_reader import vertex_facts, vertex_fold, vertex_summary

from .target import resolve_target
from .types import FactPageResult, FoldStateResult, ReadSummary, TargetUnsupported

__all__ = [
    "read_summary",
    "read_facts",
    "read_state",
    "read_ticks",
    "read_fact_by_id",
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

            # Find latest timestamp across kinds
            latest_ts = None
            for s in kind_stats.values():
                ts = s["latest"].timestamp()
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts

            # Compare declared kinds with observed kinds
            gen = declaration_generation(target_path)
            declared_kinds = set(gen.get("kinds", ()))
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
            next_cursor=page.next.to_dict() if page.next is not None else None,
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
    if info.canonical_path is None or info.index_path is None or not info.canonical_path.exists():
        return []

    reader, _ = _ensure_reader(info.canonical_path, info.index_path)
    try:
        if name is not None:
            ticks = reader.ticks_for_name(name)
        else:
            ticks = reader.ticks()
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
