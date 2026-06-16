"""Stream lens — zoom-aware rendering of event history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Style, Zoom, join_vertical, pad
from painted.views import record_line


def _block(text: str, style: Style, width: int | None) -> Block:
    """Create a Block, respecting width=None (no truncation)."""
    if width is not None:
        return Block.text(text, style, width=width)
    return Block.text(text, style)


def attest_line(envelope: dict | None) -> str:
    """Render a tick's witness-era envelope as one header line.

    The envelope is the attestation metadata added at append time
    (chain link, signature, fact cursor) — see StoreReader.ticks_between.
    Absent envelope (not read, or range mode) renders nothing. An
    unchained envelope renders explicitly — pre-chain tick or aggregate
    read, neither of which attests.
    """
    if envelope is None:
        return ""
    if not envelope.get("chained"):
        return "  attest: none (no chain envelope)"
    parts = ["chained", "signed" if envelope.get("signed") else "unsigned"]
    line = f"  attest: {' · '.join(parts)}"
    kind = envelope.get("cursor_kind", "")
    if kind:
        preview = envelope.get("cursor_preview", "")
        target = f'{kind}: "{preview}"' if preview else kind
        line += f" · cursor → {target}"
    return line


def stream_view(
    data: dict[str, Any] | list[dict[str, Any]], zoom: Zoom, width: int | None
) -> Block:
    """Render event stream at the given zoom level.

    Accepts either:
    - New format: {"facts": [...], "fold_meta": {...}, "vertex": str}
    - Legacy format: list of fact dicts (backwards compat)

    Uses fold_meta key_field for summary labels when available,
    falls back to heuristic scan. No per-kind if-elif branches.

    Zoom levels:
    - MINIMAL: counts by kind
    - SUMMARY: time + kind + summary (key_field driven)
    - DETAILED: + secondary fields on next line
    - FULL: all payload fields
    """
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

    # MINIMAL: just counts
    if zoom == Zoom.MINIMAL:
        counts: dict[str, int] = {}
        for f in facts:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        parts = [f"{count} {kind}" for kind, count in counts.items()]
        summary = ", ".join(parts) if parts else "0 facts"
        if tick_meta:
            summary = f"tick #{tick_meta['index']}: {summary}"
        return _block(summary, Style(), width)

    blocks: list[Block] = []
    dim_style = Style(dim=True)
    current_date = None

    # Tick drill-down header
    if tick_meta is not None:
        boundary = tick_meta.get("boundary", {})
        trigger = ""
        if boundary:
            bname = boundary.get("name", "")
            bstatus = boundary.get("status", "")
            trigger = f" — {bname} {bstatus}" if bname else ""

        range_end = tick_meta.get("range_end")
        if range_end is not None:
            title = f"Ticks #{tick_meta['index']}:{range_end} of {tick_meta['total']}"
        else:
            title = f"Tick #{tick_meta['index']} of {tick_meta['total']}{trigger}"
        blocks.append(_block(title, Style(bold=True), width))
        if tick_meta.get("since") and tick_meta.get("ts"):
            blocks.append(
                _block(
                    f"  window: {tick_meta['since']} → {tick_meta['ts']}",
                    dim_style,
                    width,
                )
            )
        attest = attest_line(tick_meta.get("envelope"))
        if attest:
            blocks.append(_block(attest, dim_style, width))
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
    rec_width = None if width is None else max(width - 2, 1)

    for f in facts:
        ts = f["ts"]
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts)
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        date_str = dt.strftime("%Y-%m-%d")
        if date_str != current_date:
            if current_date is not None:
                blocks.append(_block("", Style(), width))
            blocks.append(_block(f"{date_str}:", Style(bold=True), width))
            current_date = date_str

        kind_str = f["kind"]
        payload = f["payload"]
        fact_id = f.get("id", "")
        # --id lookup forces full fidelity regardless of zoom.
        rec_zoom = Zoom.FULL if is_id_lookup else zoom

        # The record itself — dissolved onto painted.record_line.
        rec = record_line(
            dt, kind_str, payload, rec_zoom, rec_width, payload_lens=plens
        )
        blocks.append(pad(rec, left=2))

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
            blocks.append(_block(f"    {line}", dim_style, width))

    return join_vertical(*blocks)


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


def _summary_fields(payload: dict, key_field: str | None = None) -> set[str]:
    """Return the set of field names used in the summary line."""
    if key_field and key_field not in _LABEL_FIELDS:
        fields = (key_field,) + _LABEL_FIELDS
    elif key_field:
        fields = (key_field,) + tuple(f for f in _LABEL_FIELDS if f != key_field)
    else:
        fields = _LABEL_FIELDS

    used = set()
    count = 0
    for f in fields:
        if payload.get(f):
            used.add(f)
            count += 1
            if count >= 2:
                break
    return used
