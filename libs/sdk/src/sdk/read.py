"""Domain-neutral read operations over Loops artifacts.

Provides headless query, statistics, witness pagination, state reconstruction,
and full-text search capabilities across `.vertex`, `.jsonl`, and `.db` stores.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from atoms import Arrival, Ordering, OrderingError
from engine.arrival_contract import (
    Continuation,
    Fact,
    FactRequest,
    ProjectionRequirement,
    SearchRequest,
    SummaryRequest,
    Tick,
    TickRequest,
)
from engine.arrival_registry import BackendRegistry
from engine.compiler import compile_vertex
from engine.declaration import (
    Unhistorized,
    effective_declaration_from_documents,
    load_declaration_status,
    resolve_declaration_documents_from_snapshot,
)
from engine.observer import observer_matches
from engine.preflight import PreflightMode, read_preflight
from engine.store_reader import StoreReader
from engine.vertex_reader import (
    _resolve_stores,
    resolve_ordering,
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
from lang import documents_to_vertex, vertex_to_documents

from .aggregate import has_local_descriptor_aggregate, open_aggregate_read
from .target import (
    _arrival_descriptor,
    _refuse_arrival_aggregate_members,
    resolve_target,
)
from .types import (
    EntityResolutionResult,
    FactLookupResult,
    FactPageResult,
    FoldStateResult,
    ReadSummary,
    SdkError,
    SdkValueError,
    SearchIndexResult,
    SearchResult,
    SearchResultItem,
    StoreDescriptorInfo,
    SyncResult,
    TargetUnsupported,
    TickReadResult,
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
    "sync_search_index",
    "resolve_entity",
    "read_timeline",
    "sync_target",
]


@contextlib.contextmanager
def _open_arrival_read(
    resolved: tuple[Path, Any, Any],
    *,
    registry: BackendRegistry | None,
    continuation: Continuation | None = None,
):
    """Open and close one descriptor-first read without exposing custody."""
    from engine.arrival_consumer import open_read

    _path, ast, descriptor = resolved
    opened = open_read(
        registry if registry is not None else BackendRegistry.with_builtin_backends(),
        descriptor,
        requirement=ProjectionRequirement.CURRENT,
        continuation=continuation,
    )
    try:
        yield ast, descriptor, opened
    finally:
        opened.close()


def _aggregate_aware_arrival_descriptor(
    target: Path,
) -> tuple[Path, Any, Any] | None:
    """Resolve one descriptor root while deferring shape to adopted evidence."""
    return _arrival_descriptor(target, allow_aggregate=True)


def _fact_as_dict(fact: Fact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "kind": fact.kind,
        "ts": fact.ts,
        "observer": fact.observer,
        "origin": fact.origin,
        "payload": dict(fact.payload),
        "arrival_ordinal": fact.arrival_ordinal,
        "arrival_seq": fact.arrival_seq,
    }


def _arrival_tick_as_dict(tick: Tick) -> dict[str, Any]:
    return {
        "id": tick.id,
        "name": tick.name,
        "ts": tick.ts,
        "since": tick.since,
        "origin": tick.origin,
        "payload": dict(tick.payload),
        "arrival_ordinal": tick.arrival_ordinal,
        "arrival_seq": tick.arrival_seq,
    }


def _latest_timestamp(kinds: Mapping[str, Mapping[str, Any]]) -> float | None:
    latest: list[float] = []
    for stats in kinds.values():
        value = stats.get("latest")
        if isinstance(value, datetime):
            latest.append(value.timestamp())
        elif isinstance(value, (int, float)):
            latest.append(float(value))
        elif isinstance(value, str):
            with contextlib.suppress(ValueError, TypeError):
                latest.append(datetime.fromisoformat(value).timestamp())
    return max(latest) if latest else None


def _arrival_generation(
    ast: Any,
    facts: tuple[Fact, ...],
    own_lineage: str,
    declaration_status: str,
) -> dict[str, Any]:
    """Build the established declaration-generation review fields from one snapshot."""
    documents = vertex_to_documents(ast)
    canonical = json.dumps(
        [document.as_json() for document in documents],
        sort_keys=True,
        separators=(",", ":"),
    )
    declaration_head = None
    if declaration_status == "store":
        declaration_head = own_lineage
        for fact in sorted(facts, key=lambda item: (item.arrival_ordinal, item.arrival_seq)):
            if not fact.kind.startswith("_decl."):
                continue
            if fact.id == own_lineage or fact.payload.get("lineage") == own_lineage:
                declaration_head = fact.id
    return {
        "status": declaration_status,
        "lineage": own_lineage,
        "review_fingerprint": "sha256:"
        + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "decl_head": declaration_head,
    }


def _arrival_declaration(
    locator_ast: Any,
    target_path: Path,
    opened: Any,
    *,
    include_user_facts: bool = False,
    allow_aggregate: bool = False,
) -> tuple[Any, str, tuple[Fact, ...], str]:
    """Resolve effective declarations from the same bounded read snapshot."""
    facts = opened.snapshot.facts(
        FactRequest(
            limit=None,
            kind=None if include_user_facts else "_decl",
            include_internal=True,
            order="oldest",
        )
    ).items
    anchor = opened.snapshot.declaration_anchor
    documents = resolve_declaration_documents_from_snapshot(anchor, facts)
    if documents is None:
        raise SdkError(
            "the Arrival snapshot has no adopted declaration; refusing to "
            "substitute the current vertex file as store history"
        )
    status = "unhistorized" if isinstance(documents, Unhistorized) else "store"
    document_rows = documents.documents if isinstance(documents, Unhistorized) else documents
    effective_ast = documents_to_vertex(
        document_rows,
        path=target_path,
        store=locator_ast.store,
        store_backend=locator_ast.store_backend,
        store_location=locator_ast.store_location,
    )
    if not allow_aggregate and (
        effective_ast.combine is not None or effective_ast.discover is not None
    ):
        raise TargetUnsupported(
            "the bounded Arrival declaration is an aggregate; member-basis reads "
            "are not implemented in this single-store stage"
        )
    if anchor.own_lineage is None:
        raise SdkError("resolved declaration has no own lineage anchor")
    return effective_ast, status, facts, anchor.own_lineage


def _arrival_search_spec(locator_ast: Any, target_path: Path, opened: Any):
    """Derive one pin-checked search spec from this exact read snapshot."""
    from engine.arrival_search import derive_search_spec

    facts = opened.snapshot.facts(
        FactRequest(limit=None, kind="_decl", include_internal=True, order="oldest")
    ).items
    documents = resolve_declaration_documents_from_snapshot(
        opened.snapshot.declaration_anchor, facts
    )
    if documents is None:
        raise SdkError(
            "the Arrival snapshot has no adopted declaration; refusing to derive "
            "search fields from the locator file"
        )
    document_rows = documents.documents if isinstance(documents, Unhistorized) else documents
    effective = effective_declaration_from_documents(document_rows, locator_ast)
    if effective.combine is not None or effective.discover is not None:
        raise TargetUnsupported(
            "the bounded Arrival declaration is an aggregate; member-basis search "
            "is not implemented in this single-store stage"
        )
    return derive_search_spec(effective, target_path.parent)


def _refuse_unimplemented_arrival(
    target: Path | str, operation: str
) -> None:
    if _arrival_descriptor(target) is not None:
        raise TargetUnsupported(
            f"{operation} is not yet supported for a descriptor-first Arrival target"
        )
    _refuse_arrival_aggregate_members(target)


def _check_declared_ordering(ordering: Ordering | None, *, single_store: bool) -> None:
    """Validate a declared read ordering against the axis this page path serves.

    ``None`` is the whole of today's behavior: the defaults are already what the
    paged read paths serve, so nothing reroutes. A DECLARED ordering must resolve
    to that same axis — ``Arrival()`` single-store, ``ByKey('ts')`` aggregate,
    with ``Arrival()`` on an aggregate refused by the one engine resolver. Any
    other declared ordering is refused rather than approximated: ordering-aware
    witness pagination is not this cut.

    Raises:
        SdkValueError: The ordering is refused, or names an axis paged reads do
            not serve this cut.
    """
    if ordering is None:
        return
    try:
        resolved = resolve_ordering(ordering, single_store=single_store)
    except OrderingError as exc:
        raise SdkValueError(str(exc)) from exc
    served = resolve_ordering(None, single_store=single_store)
    if resolved != served:
        raise SdkValueError(
            f"ordering {ordering!r} is not supported on a paged read this cut: "
            f"this path serves {served!r}. Declare that, or omit ordering."
        )


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


def _aggregate_summary(
    target_path: Path,
    *,
    include_internal: bool,
    registry: BackendRegistry | None,
) -> ReadSummary:
    """Inventory retained member snapshots without manufacturing a common basis."""
    with open_aggregate_read(target_path, registry=registry) as aggregate:
        return _aggregate_summary_from(aggregate, target_path, include_internal=include_internal)


def _aggregate_summary_from(
    aggregate: Any, target_path: Path, *, include_internal: bool
) -> ReadSummary:
    kinds: dict[str, dict[str, Any]] = {}
    ticks: dict[str, dict[str, Any]] = {}
    fact_total = tick_total = signed_count = unsigned_count = 0
    for member in aggregate.capture.members:
        raw = member.snapshot.summary(SummaryRequest(include_internal=include_internal))
        fact_total += raw.fact_total
        tick_total += raw.tick_total
        signed_count += raw.signed_count
        unsigned_count += raw.unsigned_count
        for name, stats in raw.fact_kinds.items():
            target = kinds.setdefault(name, {"count": 0, "earliest": None, "latest": None})
            target["count"] += stats.get("count", 0)
            for edge, reducer in (("earliest", min), ("latest", max)):
                value = stats.get(edge)
                if value is not None:
                    target[edge] = value if target[edge] is None else reducer(target[edge], value)
        for name, stats in raw.tick_names.items():
            target = ticks.setdefault(name, {"count": 0, "earliest": None, "latest": None})
            target["count"] += stats.get("count", 0)
            for edge, reducer in (("earliest", min), ("latest", max)):
                value = stats.get(edge)
                if value is not None:
                    target[edge] = value if target[edge] is None else reducer(target[edge], value)
    return ReadSummary(
            read_path="arrival-aggregate",
            target_type="vertex",
            target_path=str(target_path),
            fact_total=fact_total,
            tick_total=tick_total,
            latest_ts=_latest_timestamp(kinds),
            kinds=kinds,
            ticks=ticks,
            agreement=None,
            declaration_status="aggregate-captured",
            unfolded_kinds=[
                name
                for name in kinds
                if name not in aggregate.specs() and not name.startswith("_decl.")
            ],
            signed_count=signed_count,
            unsigned_count=unsigned_count,
            aggregate_members=aggregate.member_evidence(),
            aggregate_definitions=aggregate.definition_evidence(),
    )


def _aggregate_state(
    target_path: Path, *, kind: str | None, observer: str | None, registry: BackendRegistry | None
) -> FoldStateResult:
    """Replay frozen selected streams under recursively inherited fold specs."""
    with open_aggregate_read(target_path, registry=registry) as aggregate:
        return _aggregate_state_from(aggregate, target_path, kind=kind, observer=observer)


def _aggregate_state_from(
    aggregate: Any, target_path: Path, *, kind: str | None, observer: str | None
) -> FoldStateResult:
    specs = aggregate.specs()
    sections: dict[str, Any] = {}
    for section_name, spec in specs.items():
        if kind is not None and section_name != kind:
            continue
        payloads: list[dict[str, Any]] = []
        for fact in aggregate.ordered_for_kind(section_name, observer=observer):
            payload = dict(fact.payload)
            payload.update(
                {
                    "_ts": fact.ts,
                    "_observer": fact.observer,
                    "_origin": fact.origin,
                    "_id": fact.id,
                }
            )
            payloads.append(payload)
        sections[section_name] = _serialize_fold_section(spec.replay(payloads))
    return FoldStateResult(
            read_path="arrival-aggregate",
            vertex_name=aggregate.root.effective_declaration.name,
            target_path=str(target_path),
            declaration_status="aggregate-captured",
            generation={"status": "aggregate", "member_count": len(aggregate.capture.members)},
            sections=sections,
            aggregate_members=aggregate.member_evidence(),
            aggregate_definitions=aggregate.definition_evidence(),
    )


def _aggregate_timeline(
    target_path: Path,
    *,
    start_ts: float | None,
    end_ts: float | None,
    limit: int,
    order: str,
    registry: BackendRegistry | None,
) -> TimelineResult:
    """Timestamp lens over retained member snapshots; it does not fold rows."""
    with open_aggregate_read(target_path, registry=registry) as aggregate:
        return _aggregate_timeline_from(
            aggregate,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=limit,
            order=order,
        )


def _aggregate_timeline_from(
    aggregate: Any,
    *,
    start_ts: float | None,
    end_ts: float | None,
    limit: int,
    order: str,
) -> TimelineResult:
    since = start_ts if start_ts is not None else 0.0
    until = end_ts if end_ts is not None else float("inf")
    events = [
            TimelineEvent(
                event_type=event_type,
                id=row.id,
                kind_or_name=row.kind if event_type == "fact" else row.name,
                ts=row.ts,
                observer=row.observer if event_type == "fact" else "",
                origin=row.origin,
                payload=dict(row.payload),
            )
        for event_type, _member, row in aggregate.all_events(start=since, end=until)
    ]
    if order == "newest":
        events.reverse()
    return TimelineResult(
            read_path="arrival-aggregate",
            events=events[:limit],
            start_ts=start_ts,
            end_ts=end_ts,
            total_events=len(events),
            truncated=len(events) > limit,
            order=order,
            aggregate_members=aggregate.member_evidence(),
            aggregate_definitions=aggregate.definition_evidence(),
    )


def read_summary(
    target: Path | str,
    *,
    include_internal: bool = False,
    registry: BackendRegistry | None = None,
) -> ReadSummary:
    """Read domain-neutral statistical inventory of a target artifact.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        include_internal: Whether to include reserved `_decl.*` kinds.

    Returns:
        ReadSummary containing fact/tick totals, kind distribution, and agreement.
    """
    target_path = Path(target).resolve()
    if has_local_descriptor_aggregate(target_path):
        return _aggregate_summary(
            target_path, include_internal=include_internal, registry=registry
        )
    arrival = _aggregate_aware_arrival_descriptor(target_path)
    if arrival is not None:
        with _open_arrival_read(arrival, registry=registry) as (
            locator_ast,
            descriptor,
            opened,
        ):
            raw = opened.snapshot.summary(
                SummaryRequest(include_internal=include_internal)
            )
            effective_ast, declaration_status, _facts, _own_lineage = _arrival_declaration(
                locator_ast, target_path, opened, allow_aggregate=True
            )
            if effective_ast.combine is not None or effective_ast.discover is not None:
                with open_aggregate_read(
                    target_path, registry=registry, opened_root=opened
                ) as aggregate:
                    return _aggregate_summary_from(
                        aggregate, target_path, include_internal=include_internal
                    )
            kinds = {name: dict(stats) for name, stats in raw.fact_kinds.items()}
            return ReadSummary(
                read_path="arrival",
                basis=opened.basis,
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                target_type="vertex",
                target_path=str(target_path),
                fact_total=raw.fact_total,
                tick_total=raw.tick_total,
                latest_ts=_latest_timestamp(raw.fact_kinds),
                kinds=kinds,
                ticks={name: dict(stats) for name, stats in raw.tick_names.items()},
                agreement=None,
                declaration_status=declaration_status,
                unfolded_kinds=[
                    name
                    for name in kinds
                    if name not in effective_ast.loops and not name.startswith("_decl.")
                ],
                signed_count=raw.signed_count,
                unsigned_count=raw.unsigned_count,
            )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)
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
    ordering: Ordering | None = None,
    before: str | Continuation | None = None,
    after: str | Continuation | None = None,
    include_internal: bool = False,
    registry: BackendRegistry | None = None,
) -> FactPageResult:
    """Read a bounded page of facts with stable witness pagination cursors.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        limit: Maximum number of facts to return.
        kind: Optional kind filter.
        observer: Optional observer identity filter.
        order: Sort direction along the ordering axis — 'oldest' ascending,
            'newest' descending.
        ordering: Declared read ordering. ``None`` keeps today's axis: receipt
            order for a single-store vertex, the ``(ts, id)`` read lens for an
            aggregate. Declaring ``Arrival()`` on a multi-store aggregate is
            refused — see :func:`engine.vertex_reader.resolve_ordering`. Only
            the resolved default axis is supported this cut; any other declared
            ordering is refused rather than silently approximated.
        before: Cursor token to fetch rows before (older than) the cursor in newest order.
        after: Cursor token to fetch rows after (newer than) the cursor in oldest order.
        include_internal: Whether to include internal `_decl.*` facts.

    Returns:
        FactPageResult containing deserialized fact items and pagination metadata.
    """
    if order not in ("newest", "oldest"):
        raise SdkValueError(f"invalid order '{order}': expected 'newest' or 'oldest'")

    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is not None:
        if before is not None and after is not None:
            raise SdkValueError("before and after are mutually exclusive")
        token = before if before is not None else after
        if token is not None and not isinstance(token, Continuation):
            raise SdkValueError(
                "descriptor-first reads require the Continuation returned by a prior page"
            )
        if before is not None and order != "newest":
            raise SdkValueError("before continuation requires order='newest'")
        if after is not None and order != "oldest":
            raise SdkValueError("after continuation requires order='oldest'")
        request = FactRequest(
            limit=limit,
            kind=kind,
            observer=observer,
            order=order,
            include_internal=include_internal,
        )
        with _open_arrival_read(
            arrival, registry=registry, continuation=token
        ) as (locator_ast, descriptor, opened):
            if token is None:
                _arrival_declaration(locator_ast, target_path, opened)
            page = opened.snapshot.facts(request)
            next_cursor = opened.continuation(request, page)
            return FactPageResult(
                read_path="arrival",
                basis=opened.basis,
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                items=[_fact_as_dict(fact) for fact in page.items],
                next_cursor=next_cursor,
                prev_cursor=None,
                truncated=page.truncated,
                order=page.order,
            )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)
    if isinstance(before, Continuation) or isinstance(after, Continuation):
        raise SdkValueError(
            "Arrival Continuation values cannot be used on a legacy read path"
        )

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )
        # read_facts keys on DECLARATION SHAPE, not member count: an aggregate's
        # page comes off the (ts, id) lens whatever its member count, so that is
        # the axis a declared ordering is checked against.
        _check_declared_ordering(ordering, single_store=not is_aggregate)

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
        page_prev: Any = getattr(page, "prev", None)
        prev_tok = page_prev.fact_id or f"seq:{page_prev.seq}" if page_prev is not None else None
        return FactPageResult(
            items=page.items,
            next_cursor=next_tok,
            prev_cursor=prev_tok,
            truncated=page.truncated,
            order=order,
        )

    # A bare .db/.jsonl target is one store, so its axis is Arrival().
    _check_declared_ordering(ordering, single_store=True)

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
        page_prev: Any = getattr(page, "prev", None)
        prev_tok = page_prev.fact_id or f"seq:{page_prev.seq}" if page_prev is not None else None

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
    registry: BackendRegistry | None = None,
) -> FoldStateResult:
    """Reconstruct live fold state by replaying facts through declared vertex folds.

    Parameters:
        target: Path to .vertex artifact.
        kind: Optional single-kind filter.
        observer: Optional observer view filter.

    Returns:
        FoldStateResult containing reconstructed state sections and generation info.
    """
    target_path = Path(target).resolve()
    if has_local_descriptor_aggregate(target_path):
        return _aggregate_state(
            target_path, kind=kind, observer=observer, registry=registry
        )
    arrival = _aggregate_aware_arrival_descriptor(target_path)
    if arrival is not None:
        with _open_arrival_read(arrival, registry=registry) as (
            locator_ast,
            descriptor,
            opened,
        ):
            effective_ast, declaration_status, facts, own_lineage = _arrival_declaration(
                locator_ast,
                target_path,
                opened,
                include_user_facts=True,
                allow_aggregate=True,
            )
            if effective_ast.combine is not None or effective_ast.discover is not None:
                with open_aggregate_read(
                    target_path, registry=registry, opened_root=opened
                ) as aggregate:
                    return _aggregate_state_from(
                        aggregate, target_path, kind=kind, observer=observer
                    )
            specs = compile_vertex(effective_ast)
            sections: dict[str, Any] = {}
            for section_name, spec in specs.items():
                if kind is not None and section_name != kind:
                    continue
                selected = [
                    fact
                    for fact in facts
                    if fact.kind == section_name
                    and (observer is None or observer_matches(fact.observer, observer))
                ]
                payloads: list[dict[str, Any]] = []
                for fact in selected:
                    payload = dict(fact.payload)
                    payload.update(
                        {
                            "_ts": fact.ts,
                            "_observer": fact.observer,
                            "_origin": fact.origin,
                            "_id": fact.id,
                        }
                    )
                    payloads.append(payload)
                sections[section_name] = _serialize_fold_section(spec.replay(payloads))

            return FoldStateResult(
                read_path="arrival",
                basis=opened.basis,
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                vertex_name=effective_ast.name,
                target_path=str(target_path),
                declaration_status=declaration_status,
                generation=_arrival_generation(
                    effective_ast, facts, own_lineage, declaration_status
                ),
                sections=sections,
            )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)
    if info.target_type != "vertex":
        raise TargetUnsupported(f"read_state requires a .vertex target, got {info.target_type}")

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

    generation_as_dict = getattr(gen, "as_dict", None)
    return FoldStateResult(
        vertex_name=decl_ast.name if decl_ast else vertex_path.stem,
        target_path=str(vertex_path),
        declaration_status=decl_status or "unknown",
        generation=generation_as_dict() if callable(generation_as_dict) else gen,
        sections=sections,
    )


def read_ticks(
    target: Path | str,
    *,
    name: str | None = None,
    registry: BackendRegistry | None = None,
) -> TickReadResult:
    """Read chronological tick seals and cadence boundaries.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        name: Optional tick mark name filter.

    Returns:
        TickReadResult with chronological records and the read basis when the
        target uses a descriptor-first Arrival store.
    """
    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is not None:
        with _open_arrival_read(arrival, registry=registry) as (
            locator_ast,
            descriptor,
            opened,
        ):
            _arrival_declaration(locator_ast, target_path, opened)
            ticks = opened.snapshot.ticks(TickRequest(name=name))
            return TickReadResult(
                read_path="arrival",
                basis=opened.basis,
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                items=[_arrival_tick_as_dict(tick) for tick in ticks],
            )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )
        if is_aggregate:
            ticks = vertex_ticks(target_path, 0.0, float("inf"), name=name)
            return TickReadResult(items=[_tick_as_dict(t) for t in ticks])

        if info.canonical_path is None or not info.canonical_path.exists():
            return TickReadResult(items=[])

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, _ = _ensure_reader(canonical, index_path)
    try:
        ticks = reader.ticks_between(0.0, float("inf"), name=name)
        return TickReadResult(items=[_tick_as_dict(t) for t in ticks])
    finally:
        reader.close()


def read_fact_by_id(
    target: Path | str,
    fact_id: str,
    *,
    registry: BackendRegistry | None = None,
) -> FactLookupResult:
    """Locate and return a single fact by its ULID identifier.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        fact_id: ULID or ID string of the target fact.

    Returns:
        FactLookupResult retaining the read basis even when no fact matched.
    """
    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is not None:
        request = FactRequest(limit=None, fact_id=fact_id)
        with _open_arrival_read(arrival, registry=registry) as (
            locator_ast,
            descriptor,
            opened,
        ):
            _arrival_declaration(locator_ast, target_path, opened)
            matches = opened.snapshot.facts(request).items
            if len(matches) > 1:
                raise SdkValueError(f"Ambiguous ID prefix: {fact_id!r}")
            return FactLookupResult(
                read_path="arrival",
                basis=opened.basis,
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                fact=None if not matches else _fact_as_dict(matches[0]),
            )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )
        if is_aggregate:
            return FactLookupResult(fact=vertex_fact_by_id(target_path, fact_id))

        if info.canonical_path is None or not info.canonical_path.exists():
            return FactLookupResult(fact=None)

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, _ = _ensure_reader(canonical, index_path)
    try:
        return FactLookupResult(fact=reader.fact_by_id(fact_id))
    finally:
        reader.close()


def search_facts(
    target: Path | str,
    query: str,
    *,
    kind: str | None = None,
    observer: str | None = None,
    since: float | None = None,
    until: float | None = None,
    limit: int = 50,
    registry: BackendRegistry | None = None,
) -> SearchResult:
    """Execute full-text search (FTS5) over fact payloads.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        query: Full-text search expression.
        kind: Optional kind-subtree filter.
        observer: Optional exact observer filter.
        since: Optional inclusive event-time lower bound.
        until: Optional inclusive event-time upper bound.
        limit: Maximum number of matching items.

    Returns:
        SearchResult containing ranked SearchResultItem matches.
    """
    if limit < 1:
        raise SdkValueError("search limit must be >= 1")
    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target_path)
    if arrival is not None:
        from .errors import normalize_exception

        try:
            with _open_arrival_read(arrival, registry=registry) as (
                locator_ast,
                descriptor,
                opened,
            ):
                spec = _arrival_search_spec(locator_ast, target_path, opened)
                page = opened.snapshot.search(
                    SearchRequest(
                        expression=query,
                        expected_fields_hash=spec.fields_hash,
                        kind=kind,
                        observer=observer,
                        since=since,
                        until=until,
                        limit=limit,
                    )
                )
                return SearchResult(
                    read_path="arrival",
                    basis=opened.basis,
                    store=StoreDescriptorInfo.from_descriptor(descriptor),
                    query=query,
                    matches=[
                        SearchResultItem(
                            id=match.fact.id,
                            kind=match.fact.kind,
                            ts=match.fact.ts,
                            observer=match.fact.observer,
                            origin=match.fact.origin,
                            payload=dict(match.fact.payload),
                            rank=match.rank,
                            snippet=match.snippet or "",
                        )
                        for match in page.matches
                    ],
                    total_matches=page.total_matches,
                    truncated=page.truncated,
                    ranking=page.ranking,
                    ranking_through=page.ranking_through,
                    fields_hash=page.fields_hash,
                )
        except BaseException as exc:
            normalized = normalize_exception(exc)
            if normalized is exc:
                raise
            raise normalized from exc

    _refuse_arrival_aggregate_members(target_path)
    if observer is not None or since is not None or until is not None:
        raise SdkValueError(
            "observer and time filters are currently available only for an "
            "explicit Arrival search target"
        )
    info = resolve_target(target)

    matches: list[SearchResultItem] = []
    if info.target_type == "vertex":
        try:
            raw_matches = vertex_search(target_path, query, kind=kind, limit=limit)
            for raw_match in raw_matches:
                m: Any = raw_match
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
        for raw_match in raw_matches:
            m: Any = raw_match
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
    value: Any,
    *,
    registry: BackendRegistry | None = None,
) -> EntityResolutionResult:
    """Resolve an entity key to its latest fact ID.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        kind: Target kind name.
        key: Primary key field name.
        value: Entity key value.
        registry: Optional Arrival backend registry used for descriptor opens.

    Returns:
        A uniform entity-resolution result; ``found`` and ``fact_id`` describe
        the match while ``address`` always preserves the queried top-level key.
    """
    def result(
        fact_id: str | None,
        *,
        store: StoreDescriptorInfo | None,
        basis: Any = None,
        read_path: str = "legacy",
    ) -> EntityResolutionResult:
        return EntityResolutionResult(
            found=fact_id is not None,
            fact_id=fact_id,
            address={"kind": kind, "key": key, "value": value},
            read_path=read_path,
            store=store,
            basis=basis,
        )

    target_path = Path(target).resolve()
    arrival = _arrival_descriptor(target)
    if arrival is not None:
        with _open_arrival_read(arrival, registry=registry) as (
            locator,
            descriptor,
            opened,
        ):
            _arrival_declaration(locator, target_path, opened, include_user_facts=True)
            facts = opened.snapshot.facts(
                FactRequest(kind=kind, limit=None, include_internal=False, order="newest")
            ).items
            matched = next(
                (
                    fact for fact in facts
                    if key in fact.payload
                    and type(fact.payload[key]) is type(value)
                    and fact.payload[key] == value
                ),
                None,
            )
            return result(
                None if matched is None else matched.id,
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                basis=opened.basis, read_path="arrival",
            )
    _refuse_arrival_aggregate_members(target)
    info = resolve_target(target)

    if info.target_type == "vertex":
        decl_ast, _ = load_declaration_status(target_path)
        is_aggregate = decl_ast is not None and (
            decl_ast.combine is not None or decl_ast.discover is not None
        )
        if is_aggregate:
            # Entity resolution must agree with the fold, so it resolves the
            # SAME ordering _combined_read does, off the same member count.
            #
            # Arrival() (ONE member): that member's arrival axis IS the
            # aggregate's, so the fold replays on it and resolution must too —
            # a backdated re-assertion wins the fold, and the lens walk below
            # would hand back the row it superseded.
            #
            # ByKey (TWO OR MORE): no cross-store arrival axis exists, so the
            # combined read is an event-time lens projection and every other
            # combined surface reads through that same lens — the lens walk
            # below is the coherent answer.
            store_paths = _resolve_stores(decl_ast, target_path)
            fold_ordering = resolve_ordering(None, single_store=len(store_paths) == 1)
            if isinstance(fold_ordering, Arrival) and store_paths[0].exists():
                member_reader = StoreReader(store_paths[0])
                try:
                    fact_id = member_reader.resolve_entity_id(kind, key, value)
                    return result(fact_id, store=None)
                finally:
                    member_reader.close()

            all_facts = vertex_facts(target_path, since_ts=0.0, until_ts=float("inf"), kind=kind)
            for f in reversed(all_facts):
                p = f.get("payload", {})
                if str(p.get(key)) == str(value):
                    fact_id = f.get("id")
                    return result(fact_id, store=None)
            return result(None, store=None)

        if info.canonical_path is None or not info.canonical_path.exists():
            return result(None, store=None)

    canonical = info.canonical_path or target_path
    index_path = info.index_path or canonical
    reader, _ = _ensure_reader(canonical, index_path)
    try:
        fact_id = reader.resolve_entity_id(kind, key, value)
        return result(fact_id, store=None)
    finally:
        reader.close()


def read_timeline(
    target: Path | str,
    *,
    start_ts: float | None = None,
    end_ts: float | None = None,
    limit: int = 100,
    order: str = "oldest",
    registry: BackendRegistry | None = None,
) -> TimelineResult:
    """Read an interleaved, chronological stream of both facts and sealed ticks.

    Parameters:
        target: Path to .vertex, .jsonl, or .db artifact.
        start_ts: Optional lower timestamp bound (inclusive).
        end_ts: Optional upper timestamp bound (inclusive).
        limit: Maximum number of events to return.
        order: Sort order ('oldest' for chronological, 'newest' for reverse chronological).
        registry: Optional Arrival backend registry used for root and member opens.

    Ordering is by event time (``ts``) — facts and ticks are interleaved on the
    only axis they share, so the timeline is an event-time read lens, not the
    store's fold order. A backdated fact appears where its ``ts`` puts it here
    and folds last; ``read_facts`` is the receipt-ordered view.

    Returns:
        TimelineResult containing merged events with honest total counts and truncation markers.
    """
    if order not in ("oldest", "newest"):
        raise SdkValueError(f"invalid order '{order}': expected 'oldest' or 'newest'")

    target_path = Path(target).resolve()
    if has_local_descriptor_aggregate(target_path):
        return _aggregate_timeline(
            target_path,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=limit,
            order=order,
            registry=registry,
        )
    arrival = _aggregate_aware_arrival_descriptor(target_path)
    if arrival is not None:
        since = start_ts if start_ts is not None else 0.0
        until = end_ts if end_ts is not None else float("inf")
        with _open_arrival_read(arrival, registry=registry) as (
            locator_ast,
            descriptor,
            opened,
        ):
            effective_ast, _status, _facts, _lineage = _arrival_declaration(
                locator_ast, target_path, opened, allow_aggregate=True
            )
            if effective_ast.combine is not None or effective_ast.discover is not None:
                with open_aggregate_read(
                    target_path, registry=registry, opened_root=opened
                ) as aggregate:
                    return _aggregate_timeline_from(
                        aggregate,
                        start_ts=start_ts,
                        end_ts=end_ts,
                        limit=limit,
                        order=order,
                    )
            facts = opened.snapshot.facts(
                FactRequest(limit=None, include_internal=False, order="oldest")
            ).items
            ticks = opened.snapshot.ticks(TickRequest(since=since, until=until))
            events: list[tuple[TimelineEvent, int, int]] = []
            for fact in facts:
                if since <= fact.ts <= until:
                    events.append(
                        (
                            TimelineEvent(
                                event_type="fact",
                                id=fact.id,
                                kind_or_name=fact.kind,
                                ts=fact.ts,
                                observer=fact.observer,
                                origin=fact.origin,
                                payload=dict(fact.payload),
                            ),
                            fact.arrival_ordinal,
                            fact.arrival_seq,
                        )
                    )
            for tick in ticks:
                events.append(
                    (
                        TimelineEvent(
                            event_type="tick",
                            id=tick.id,
                            kind_or_name=tick.name,
                            ts=tick.ts,
                            origin=tick.origin,
                            payload=dict(tick.payload),
                        ),
                        tick.arrival_ordinal,
                        tick.arrival_seq,
                    )
                )
            events.sort(
                key=lambda item: (item[0].ts, item[1], item[2], item[0].id),
                reverse=(order == "newest"),
            )
            total_events = len(events)
            capped = events[:limit]
            return TimelineResult(
                read_path="arrival",
                basis=opened.basis,
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                events=[event for event, _ordinal, _seq in capped],
                start_ts=start_ts,
                end_ts=end_ts,
                total_events=total_events,
                truncated=total_events > len(capped),
                order=order,
            )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)
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
            for raw_tick in raw_ticks:
                t: Any = raw_tick
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

            # Event-time lens: ts is the only axis facts and ticks share.
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

        for raw_tick in ticks:
            t: Any = raw_tick
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

        # Event-time lens: ts is the only axis facts and ticks share.
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


def _search_coverage_as_dict(coverage: Any | None) -> dict[str, Any] | None:
    if coverage is None:
        return None
    through = getattr(coverage, "through", None)
    if through is None:
        return None
    return {
        "through": {
            "lineage": through.lineage,
            "ordinal": through.ordinal,
            "record_hash": through.record_hash,
        },
        "fields_hash": coverage.fields_hash,
        "schema_version": coverage.schema_version,
    }


def sync_search_index(
    target: Path | str,
    *,
    registry: BackendRegistry | None = None,
) -> SearchIndexResult:
    """Explicitly build exact-prefix Arrival FTS coverage.

    The declaration/spec capture is separate from the serialized adapter build.
    The engine receives the first capture's exact head, so an append or a later
    declaration cannot make the second coordinator open index a different corpus.
    This operation is not projection synchronization and reads never call it.
    """
    from engine.arrival_search import sync_search_index as sync_engine_search_index

    from .errors import normalize_exception

    resolved = _arrival_descriptor(target)
    if resolved is None:
        raise TargetUnsupported(
            "sync_search_index requires an explicit Arrival descriptor"
        )
    try:
        with _open_arrival_read(resolved, registry=registry) as (
            locator_ast,
            descriptor,
            opened,
        ):
            spec = _arrival_search_spec(locator_ast, Path(target).resolve(), opened)
            basis = opened.basis
        result = sync_engine_search_index(
            registry if registry is not None else BackendRegistry.with_builtin_backends(),
            descriptor,
            spec,
            through=basis.captured_head,
        )
        return SearchIndexResult(
            store=StoreDescriptorInfo.from_descriptor(descriptor),
            basis=basis,
            coordinator_captured_head=result.captured_head,
            target=result.target,
            coverage_before=_search_coverage_as_dict(result.coverage_before),
            coverage_after=_search_coverage_as_dict(result.coverage_after),
            changed=result.changed,
        )
    except BaseException as exc:
        normalized = normalize_exception(exc)
        if normalized is exc:
            raise
        raise normalized from exc


def sync_target(
    target: Path | str,
    *,
    registry: BackendRegistry | None = None,
) -> SyncResult:
    """Explicitly synchronize a target's derived query projection.

    Parameters:
        target: Path to target .vertex, .jsonl, or .db artifact.

    Returns:
        A basis-bearing ``SyncResult``. Descriptor-first Arrival targets use
        attested bounded catch-up; legacy targets retain their existing
        reindex/preflight behavior and carry no Arrival heads.
    """
    target_path = Path(target).resolve()
    t0 = time.perf_counter()
    arrival = _arrival_descriptor(target_path)
    if arrival is not None:
        from engine.arrival_maintenance import sync_projection

        from .errors import normalize_exception

        _path, _ast, descriptor = arrival
        try:
            result = sync_projection(
                registry if registry is not None else BackendRegistry.with_builtin_backends(),
                descriptor,
            )
        except BaseException as exc:
            normalized = normalize_exception(exc)
            if normalized is exc:
                raise
            raise normalized from exc
        t1 = time.perf_counter()
        return SyncResult(
            read_path="arrival",
            store=StoreDescriptorInfo.from_descriptor(descriptor),
            target_path=str(target_path),
            status="caught-up" if result.changed else "current",
            captured_head=result.captured_head,
            target=result.target,
            projected_before=result.projected_before,
            projected_after=result.projected_after,
            view_generation=result.view_generation,
            changed=result.changed,
            rebuilt=result.rebuilt,
            indexed_facts=None,
            agreement=result.projected_after.ordinal >= result.target.ordinal,
            duration_ms=(t1 - t0) * 1000.0,
        )

    _refuse_arrival_aggregate_members(target_path)
    info = resolve_target(target)

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
            total_val: Any = reader.fact_total
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
