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

# Metadata fields that aren't part of the payload-as-patch.
_DIFF_SKIP_FIELDS = frozenset({"_ts", "_observer", "_origin", "_id"})

# Long-form fields where "→ new" prefix reads better than "old → new".
_DIFF_LONG_FIELDS = frozenset({"message", "summary"})


def _render_diff(data: dict[str, Any], zoom: Zoom, width: int | None) -> Block:
    """Render the lifecycle as cumulative deltas.

    Each fact shown only as the fields it changed from accumulated prior
    state. Walks ASC; maintains accumulated scalar state and ref-set as
    it goes. See decision:design/trace-diff-cumulative-replay for the
    rendering rules.

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
    accumulated_refs_by_entity: dict[str, set[str]] = {}
    current_date: str | None = None

    # Detect whether --refs/--depth surfaced multiple entities; if so,
    # show the entity label on each fact's header.
    entities_seen = {f.get("_entity") for f in facts if f.get("_entity")}
    show_entity = len(entities_seen) > 1

    for i, fact in enumerate(facts):
        entity = fact.get("_entity") or f"{fact.get('kind', '')}/?"
        accumulated = accumulated_by_entity.setdefault(entity, {})
        accumulated_refs = accumulated_refs_by_entity.setdefault(entity, set())
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
        scalar_deltas: list[tuple[str, Any, Any]] = []
        new_refs: set[str] | None = None
        for key, value in payload.items():
            if key in _DIFF_SKIP_FIELDS:
                continue
            if key == "ref":
                # Refs handled as set diff below
                new_refs = _parse_refs(value)
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

        # Render ref deltas (set diff against prior)
        if new_refs is not None:
            added = new_refs - accumulated_refs
            removed = accumulated_refs - new_refs
            if added:
                rows.append((
                    "    refs: " + ", ".join("+" + r for r in sorted(added)),
                    dim,
                ))
            if removed:
                rows.append((
                    "          " + ", ".join("-" + r for r in sorted(removed)),
                    dim,
                ))
            # Write back to per-entity dict — `accumulated_refs` is the
            # local binding fetched at top of loop; rebinding it doesn't
            # persist across iterations.
            accumulated_refs_by_entity[entity] = new_refs

        # Update accumulated scalar state
        for key, value in payload.items():
            if key in _DIFF_SKIP_FIELDS or key == "ref":
                continue
            accumulated[key] = value

        # No-change fact (re-emit with identical payload) — surface it
        if not scalar_deltas and new_refs is None:
            rows.append(("    (no field changes)", dim))
        elif not scalar_deltas and new_refs is not None and not (new_refs ^ (accumulated_refs if i == 0 else (accumulated_refs | (new_refs - accumulated_refs)))):
            # Edge case: ref field present but no actual delta vs prior — rare
            pass

    return Block.column(rows, width=width) if rows else Block.text("(empty)", dim, width=width or 0)


def _parse_refs(value: Any) -> set[str]:
    """Parse a refs payload field (comma-separated str) into a set."""
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(v).strip() for v in value if str(v).strip()}
    return {r.strip() for r in str(value).split(",") if r.strip()}


def _truncate(s: str, width: int | None) -> str:
    """Truncate string for diff render — wide budget at full-width, snug otherwise."""
    if width is None:
        return s
    budget = max(width - 10, 40)  # leave room for indent + field label
    if len(s) <= budget:
        return s
    return s[: budget - 1] + "…"


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
