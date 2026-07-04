"""Stream lens — zoom-aware rendering of event history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Style, Zoom, join_horizontal, join_vertical
from painted.views import record_line

from ._grammar import (
    DateGrouper,
    card,
    card_width,
    coerce_dt,
    date_key,
    rail_glyph,
    recency,
    rollup_line,
    tick_drill_rows,
)
from ._grammar import block as _block
from ._statview import palette_of


def stream_view(
    data: dict[str, Any] | list[dict[str, Any]], zoom: Zoom, width: int | None,
    *, piped: bool | None = None, vertex_name: str | None = None,
) -> Block:
    """Render event stream at the given zoom level.

    Accepts either:
    - New format: {"facts": [...], "fold_meta": {...}, "vertex": str}
    - Legacy format: list of fact dicts (backwards compat)

    Uses fold_meta key_field for summary labels when available,
    falls back to heuristic scan. No per-kind if-elif branches.

    ``piped`` keys the presentation register on the channel (not width) —
    accepted now so callers key the register explicitly; the registers
    diverge structurally in the Surface-staging slice (G4).

    Zoom levels:
    - MINIMAL: counts by kind
    - SUMMARY: time + kind + summary (key_field driven)
    - DETAILED: + secondary fields on next line
    - FULL: all payload fields
    """
    # Piped register is information-faithful: force width=None so an
    # inherited COLUMNS never clips the agent channel (observation
    # rendering/piped-faithfulness-forces-width-none).
    is_piped = bool(piped or (piped is None and width is None))
    if is_piped:
        width = None

    p = palette_of(None)

    # Normalize input format
    if isinstance(data, dict):
        facts = data.get("facts", [])
        fold_meta = data.get("fold_meta", {})
    else:
        facts = data
        fold_meta = {}

    # Tick drill-down metadata
    tick_meta = data.get("_tick") if isinstance(data, dict) else None
    tick_error = data.get("_tick_error") if isinstance(data, dict) else None

    if tick_error:
        return _block(tick_error, Style(dim=True), width)

    if not facts and tick_meta is None:
        return _block("No facts in the given time range.", Style(dim=True), width)

    # MINIMAL: counts on the spine grammar (vertex · N kind · …). A tick
    # drill has no vertex to lead with — its ``tick #N`` label takes the slot.
    if zoom == Zoom.MINIMAL:
        counts: dict[str, int] = {}
        for f in facts:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        parts = [f"{count} {kind}" for kind, count in counts.items()] or ["0 facts"]
        if tick_meta:
            lead = f"tick #{tick_meta['index']}"
        else:
            lead = vertex_name or (data.get("vertex", "") if isinstance(data, dict) else "")
        return _block(rollup_line(lead, parts), Style(), width)

    blocks: list[Block] = []
    dim_style = Style(dim=True)
    grouper = DateGrouper()

    # Tick drill-down header — shared grammar rows + this view's fact count.
    if tick_meta is not None:
        for text, style in tick_drill_rows(tick_meta):
            blocks.append(_block(text, style, width))
        blocks.append(_block(f"  {len(facts)} facts", dim_style, width))
        blocks.append(_block("", Style(), width))

    if not facts:
        return (
            join_vertical(*blocks)
            if blocks
            else _block("No facts.", Style(dim=True), width)
        )

    # Detect single-fact lookup (--id mode) — show full detail
    is_id_lookup = isinstance(data, dict) and "_id_lookup" in data

    # Per-kind summary lens: painted's record_line renders ts+kind+payload; the
    # one loops-domain bit it can't know is the fold-declared key_field, so we
    # wrap _stream_summary as the PayloadLens. Metadata not in the payload
    # (fact id, observer, origin) is grafted as continuation lines below —
    # record_line owns the record, loops owns the fact-envelope context.
    plens = _stream_payload_lens(fold_meta)
    # Leading slot = the rail gutter (TTY: glyph+space) or the TIER column
    # (piped: tier word). Either way it costs the same 2 (TTY) / column (piped)
    # the record is inset by, so the record body budget stays aligned.
    rec_width = None if width is None else max(width - 2, 1)

    for f in facts:
        dt = coerce_dt(f["ts"]) or datetime.fromtimestamp(0, tz=timezone.utc)

        for text, style in grouper.header_rows(dt):
            blocks.append(_block(text, style, width))

        kind_str = f["kind"]
        payload = f["payload"]
        fact_id = f.get("id", "")
        # --id lookup forces full fidelity regardless of zoom.
        rec_zoom = Zoom.FULL if is_id_lookup else zoom

        # The record itself — dissolved onto painted.record_line.
        rec = record_line(
            dt, kind_str, payload, rec_zoom, rec_width, payload_lens=plens
        )
        # Rail inheritance (G4): the fact's tier came from the entity Surface
        # (fetch_stream → tier_map). TTY renders the rail glyph in the gutter;
        # the piped ledger carries the tier as a WORD (a pipe consumer can't
        # reconstruct the vertex-population quantile a glyph encodes).
        tier = f.get("tier", "")
        if is_piped:
            label = tier or "untiered"
            blocks.append(join_horizontal(
                _block(f"{label:<8}  ", Style(), None), rec,
            ))
        else:
            glyph = rail_glyph(tier)
            blocks.append(join_horizontal(
                Block.text(f"{glyph} ", p.rail_style(tier)), rec
            ))

        # Fact-envelope graft: id (DETAILED+), observer/origin (FULL/--id).
        # These are not payload fields, so record_line never renders them.
        graft: list[str] = []
        if fact_id:
            if is_id_lookup or zoom >= Zoom.FULL:
                graft.append(f"id: {fact_id}")
            elif zoom >= Zoom.DETAILED:
                graft.append(f"id: {fact_id[:8]}")
        if is_id_lookup or zoom >= Zoom.FULL:
            if f.get("observer"):
                graft.append(f"observer: {f['observer']}")
            if f.get("origin"):
                graft.append(f"origin: {f['origin']}")
        for line in graft:
            # Observer identity hue (TTY-only chrome) — the same stable
            # hash-pool colour confluence rows carry, so `stream -v` and the
            # observer cut agree on an observer's face. Piped is byte-identical
            # (style never reaches the agent channel); text is unchanged.
            gstyle = dim_style
            if not is_piped and line.startswith("observer: ") and f.get("observer"):
                gstyle = p.observer_style(f["observer"])
            blocks.append(_block(f"    {line}", gstyle, width))

    body = join_vertical(*blocks)

    # Header card — TTY letterhead (spine G5, fidelity policy B). SUMMARY+
    # only; the tick drill-down carries its own header, and the piped ledger
    # never wears chrome. Card sublines are the fact count + the span, which
    # the piped channel already carries as per-row date-group headers, so no
    # piped parity addition is owed.
    if (
        not is_piped
        and zoom >= Zoom.SUMMARY
        and tick_meta is None
        and not is_id_lookup
        and isinstance(data, dict)
        and facts
    ):
        name = vertex_name or data.get("vertex", "")
        if name:
            head = _stream_card(name, facts, body, width)
            return join_vertical(head, body)

    return body


def _stream_card(
    name: str, facts: list[dict[str, Any]], body: Block, width: int | None
) -> Block:
    """The TTY header card for a stream read — ``<vertex> · stream`` + span."""
    stamps = [dt for f in facts if (dt := coerce_dt(f.get("ts"))) is not None]
    n = len(facts)
    sublines = [f"{n} fact{'s' if n != 1 else ''}"]
    if stamps:
        lo, hi = min(stamps), max(stamps)
        span = date_key(lo) if lo == hi else f"{date_key(lo)} → {date_key(hi)}"
        sublines.append(f"{span} · updated {recency(hi)}")
    title = f"{name} · stream"
    p = palette_of(None)
    card_w = card_width(body, title, sublines, width)
    return card(title, sublines, card_w, p=p)


def _stream_payload_lens(fold_meta: dict):
    """Build a PayloadLens that honors fold-declared key_fields.

    painted.record_line knows the common kinds (decision→topic:msg,
    thread→name [status]) but not loops' per-vertex ``key_field`` declarations.
    This closure routes the summary through ``_stream_summary`` so a kind whose
    key_field is not a well-known label (e.g. metric keyed on ``custom_id``)
    still labels correctly.
    """

    def _lens(kind: str, payload: dict, zoom: Zoom) -> str:
        key_field = fold_meta.get(kind, {}).get("key_field")
        return _stream_summary(payload, key_field)

    return _lens


# --- Heuristic label fields (same priority as fold lens) ---
_LABEL_FIELDS = ("topic", "name", "title", "summary", "message")


def _stream_summary(payload: dict, key_field: str | None = None) -> str:
    """Build a one-line summary from a fact payload.

    Uses key_field from fold declaration when available, then heuristic
    scan of common label fields. Joins the primary label with the first
    secondary value for context (e.g. "topic: message").
    """
    # Build priority order
    if key_field and key_field not in _LABEL_FIELDS:
        fields = (key_field,) + _LABEL_FIELDS
    elif key_field:
        fields = (key_field,) + tuple(f for f in _LABEL_FIELDS if f != key_field)
    else:
        fields = _LABEL_FIELDS

    primary = None
    secondary = None
    for f in fields:
        val = payload.get(f, "")
        if val:
            if primary is None:
                primary = str(val)
            elif secondary is None:
                secondary = str(val)
                break

    if primary and secondary:
        return f"{primary}: {secondary}"
    if primary:
        return primary

    # _LABEL_FIELDS covers all of (topic, name, summary, message), so if
    # primary is None here none of those fields are truthy — fall through.
    return str(payload)
