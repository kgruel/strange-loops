"""Trace lens — lifecycle rendering for one ``kind/key`` entity.

Wraps ``stream_view`` to inherit zoom tiers, date grouping, ID display, and
the painted run_cli pipeline. Adds a title header naming the traced entity
(``trace decision/design/foo``) and operates on the ASC-ordered fact stream
that ``fetch_trace`` produces (oldest first — changelog narrative, not
recency-ranked log).

The data contract is identical to ``stream_view``'s input plus a ``_trace``
key carrying ``{"kind": str, "key": str}``. When ``data["_diff"]`` is set,
the lens renders cumulative deltas instead of full snapshots — each fact
shown only as the fields it changed from accumulated prior state. See
decision:design/trace-diff-cumulative-replay.

Zoom levels (inherited from ``stream_view`` semantics):

- MINIMAL: counts (e.g. ``3 thread``)
- SUMMARY: time + kind + summary per fact
- DETAILED: + secondary payload fields
- FULL: + observer, origin, ULID

Design anchor: decision:design/trace-implementation-plan.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from painted import Block, Style, Zoom, join_vertical

from .stream import stream_view


def trace_view(data: dict[str, Any], zoom: Zoom, width: int | None) -> Block:
    """Render a kind/key entity's lifecycle.

    Adds a one-line header (``trace <kind>/<key>``) above the stream
    rendering. At MINIMAL zoom we render the count inline with the header
    rather than round-tripping through ``stream_view`` — keeps both
    signals on one line.
    """
    trace_meta = data.get("_trace") if isinstance(data, dict) else None
    if not trace_meta:
        return stream_view(data, zoom, width)

    kind = trace_meta.get("kind", "")
    key = trace_meta.get("key", "")
    header_text = f"diff {kind}/{key}"
    facts = data.get("facts", []) if isinstance(data, dict) else []

    if zoom == Zoom.MINIMAL:
        # MINIMAL: header + count on one line. No need to call stream_view —
        # we already know what it would render and we want them composed.
        count = len(facts)
        suffix = "" if count == 1 else "s"
        line = f"{header_text} — {count} fact{suffix}"
        if not facts:
            line = f"{header_text} — no lifecycle found"
        if width is not None:
            return Block.text(line, Style(), width=width)
        return Block.text(line, Style())

    # Empty case: trace has no time window — stream_view's
    # "No facts in the given time range." would mislead users into
    # reaching for --since. Surface what's actually true.
    if not facts:
        msg = f"No lifecycle found for {kind}/{key}."
        if width is not None:
            empty = Block.text(msg, Style(dim=True), width=width)
        else:
            empty = Block.text(msg, Style(dim=True))
        if width is not None:
            header = Block.text(header_text, Style(bold=True), width=width)
            spacer = Block.text("", Style(), width=width)
        else:
            header = Block.text(header_text, Style(bold=True))
            spacer = Block.text("", Style())
        return join_vertical(header, spacer, empty)

    # SUMMARY+: header on its own bold line, blank, then the body.
    if data.get("_diff"):
        body = _render_diff(data, zoom, width)
    else:
        body = stream_view(data, zoom, width)
    if width is not None:
        header = Block.text(header_text, Style(bold=True), width=width)
        spacer = Block.text("", Style(), width=width)
    else:
        header = Block.text(header_text, Style(bold=True))
        spacer = Block.text("", Style())
    return join_vertical(header, spacer, body)


# --- Diff rendering ------------------------------------------------------

def _is_diff_skip(key: str) -> bool:
    """True for keys that should not appear in --diff rendering.

    ``ref`` is raw user input that the fold consumes into ``_refs`` (union-set
    across upserts). Including it in --diff would conflate write-receipt with
    temporal-query — see decision:design/write-receipt-vs-temporal-query and
    the three-site catch 2026-04-29. The canonical view for refs is --refs.

    ``_*`` keys are internal/computed (e.g. ``_refs``, ``_n``) and never appear
    in raw ``fact["payload"]`` — ``_source_payload_to_fact_dict`` (fetch.py)
    peels them before the payload is stored. The ``startswith("_")`` check is
    structurally correct and future-proof; naming individual fields here would
    be dead code.
    """
    return key.startswith("_") or key == "ref"

# Long-form fields where "→ new" prefix reads better than "old → new".
_DIFF_LONG_FIELDS = frozenset({"message", "summary"})


def _render_diff(data: dict[str, Any], zoom: Zoom, width: int | None) -> Block:
    """Render the lifecycle as cumulative deltas.

    Each fact shown only as the scalar fields it changed from accumulated
    prior state. Walks ASC; maintains accumulated scalar state per entity
    as it goes. See decision:design/trace-diff-cumulative-replay for the
    rendering rules.

    Refs are deliberately not rendered here — they accumulate (union under
    fold), they're not state, and --refs surfaces the cumulative graph.
    A fact carrying only new refs renders as "(refs only — see --refs)"
    so the emit still appears in the lifecycle.

    Under --refs (or --depth > 0), facts carry ``_entity`` markers
    identifying which ``kind/key`` each belongs to. The accumulator is
    PARTITIONED by entity — each entity's facts diff against ITS OWN prior,
    not against the merged stream. Without partitioning, the diff would
    surface spurious "transitions" between unrelated entities.
    """
    facts = data.get("facts", [])
    if not facts:
        msg = "(no facts)"
        if width is not None:
            return Block.text(msg, Style(dim=True), width=width)
        return Block.text(msg, Style(dim=True))

    rows: list[tuple[str, Style]] = []
    dim = Style(dim=True)
    plain = Style()

    # Per-entity accumulators — each entity's state evolves independently.
    accumulated_by_entity: dict[str, dict[str, Any]] = {}
    current_date: str | None = None

    # Detect whether --refs/--depth surfaced multiple entities; if so,
    # show the entity label on each fact's header.
    entities_seen = {f.get("_entity") for f in facts if f.get("_entity")}
    show_entity = len(entities_seen) > 1

    for fact in facts:
        entity = fact.get("_entity") or f"{fact.get('kind', '')}/?"
        accumulated = accumulated_by_entity.setdefault(entity, {})
        # Date grouping (matches stream_view)
        dt = _to_datetime(fact["ts"])
        date_str = dt.strftime("%Y-%m-%d") if dt else ""
        if date_str and date_str != current_date:
            if current_date is not None:
                rows.append(("", plain))
            rows.append((f"{date_str}:", Style(bold=True)))
            current_date = date_str

        time_str = dt.strftime("%H:%M") if dt else ""
        kind = fact.get("kind", "")
        fact_id = fact.get("id") or ""
        id_suffix = f"  {fact_id[:8]}" if fact_id and zoom >= Zoom.DETAILED else ""
        # When --refs surfaced multiple entities, label each fact's header
        # with the entity it belongs to. Otherwise the kind+key from
        # _entity would be redundant with the trace target.
        if show_entity:
            header = f"  {time_str} [{kind}] {entity}{id_suffix}"
        else:
            header = f"  {time_str} [{kind}]{id_suffix}"
        rows.append((header, plain))

        payload = fact.get("payload", {})

        # Compute scalar deltas: payload fields whose value differs from
        # accumulated prior (or absent from prior). Fields absent from
        # this payload are "didn't touch" under fold-merge — no delta.
        # `ref` and `_*` fields are excluded — see _is_diff_skip.
        scalar_deltas: list[tuple[str, Any, Any]] = []
        has_refs = "ref" in payload
        for key, value in payload.items():
            if _is_diff_skip(key):
                continue
            prior = accumulated.get(key)
            if prior != value:
                scalar_deltas.append((key, prior, value))

        # Render scalar deltas
        for key, prior, value in scalar_deltas:
            if key in _DIFF_LONG_FIELDS:
                # message/summary: always shown with → prefix
                line = f"    {key}: → {_truncate(str(value), width)}"
            elif prior is None:
                line = f"    {key}: . → {value}"
            else:
                line = f"    {key}: {prior} → {value}"
            rows.append((line, dim))

        # Update accumulated scalar state
        for key, value in payload.items():
            if _is_diff_skip(key):
                continue
            accumulated[key] = value

        # No-scalar-change fact — distinguish ref-only emit from
        # pure no-op. Ref-only emits did change the graph; pointer
        # users to --refs where that change is visible.
        if not scalar_deltas:
            if has_refs:
                rows.append(("    (refs only — see --refs)", dim))
            else:
                rows.append(("    (no field changes)", dim))

    return Block.column(rows, width=width) if rows else Block.text("(empty)", dim, width=width or 0)


def _truncate(s: str, width: int | None) -> str:
    """Diff-render clip — wide budget at full-width, snug otherwise."""
    if width is None:
        return s
    from ._helpers import elide
    # leave room for indent + field label
    return elide(s, max(width - 10, 40))


def _to_datetime(ts: Any) -> datetime | None:
    """Coerce a fact ts (str ISO, float epoch, or datetime) to a datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
    if isinstance(ts, (int, float)):
        from datetime import timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None
