"""Prompt lenses — render fold/stream data for system prompts.

Optimized for LLM consumption: markdown sections, no truncation, no ANSI,
no zoom levels. Always renders the same shape regardless of context.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldState


# ---------------------------------------------------------------------------
# Fold prompt lens
# ---------------------------------------------------------------------------

def prompt_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render fold data as a system prompt fragment.

    Ignores zoom and width — a system prompt is always the same shape.
    Markdown ## headers, indented label: body items, no truncation.
    """
    populated = [s for s in data.sections if s.items]
    if not populated:
        return Block.text("(empty)", Style())

    rows: list[Block] = []
    plain = Style()

    for s in populated:
        if rows:
            rows.append(Block.text("", plain))

        rows.append(Block.text(f"## {s.kind.upper()}", plain))

        for item in s.items:
            label = _find_label(item.payload, s.key_field, s.kind)
            body = _find_body(item.payload, label)
            if body:
                rows.append(Block.text(f"  {label}: {body}", plain))
            else:
                rows.append(Block.text(f"  {label}", plain))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Stream prompt lens
# ---------------------------------------------------------------------------

def stream_prompt_view(data: dict[str, Any] | list[dict[str, Any]], zoom: Zoom, width: int) -> Block:
    """Render stream facts as system prompt content.

    Strips timestamps, date headers, and kind tags. Emits the full message
    of each fact — most recent first. For single-fact use cases (handoff),
    this produces just the message text.
    """
    if isinstance(data, dict):
        facts = data.get("facts", [])
        fold_meta = data.get("fold_meta", {})
    else:
        facts = data
        fold_meta = {}

    if not facts:
        return Block.text("(empty)", Style())

    plain = Style()
    rows: list[Block] = []

    for f in facts:
        payload = f["payload"]
        key_field = fold_meta.get(f["kind"], {}).get("key_field")
        label = _find_stream_label(payload, key_field)
        body = _find_body(payload, label)
        if body:
            rows.append(Block.text(f"{label}: {body}", plain))
        else:
            rows.append(Block.text(label, plain))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_LABEL_FIELDS = ("topic", "name", "title", "summary", "message")


def _find_label(payload: dict, key_field: str | None, kind: str) -> str:
    """Extract primary label from a fold item payload."""
    candidates = (key_field,) if key_field else ()
    candidates += _LABEL_FIELDS
    for field in candidates:
        if field and payload.get(field):
            return str(payload[field])
    for k, v in payload.items():
        if v:
            return f"{k}: {v}"
    return kind


def _find_stream_label(payload: dict, key_field: str | None) -> str:
    """Extract primary label from a stream fact payload."""
    candidates = (key_field,) if key_field else ()
    candidates += _LABEL_FIELDS
    for field in candidates:
        if field and payload.get(field):
            return str(payload[field])
    for k, v in payload.items():
        if v:
            return str(v)
    return ""


def _find_body(payload: dict, used_label: str) -> str | None:
    """Find first non-label field value."""
    for k, v in payload.items():
        if not v:
            continue
        if str(v) == used_label:
            continue
        return str(v)
    return None
