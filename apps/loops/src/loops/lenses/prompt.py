"""Prompt lenses — render fold/stream data for system prompts.

Optimized for LLM consumption: markdown sections, no truncation, no ANSI,
no zoom levels. Always renders the same shape regardless of context.

Generic schema prompt — renders active items per section. Identity-specific
narrative rendering lives in config/lenses/identity_prompt.py, declared
via lens { fold "identity_prompt" } in identity.vertex.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from painted import Block, Style, Zoom, join_vertical

from loops.lenses._helpers import (
    RESOLVED_STATUSES,
    body as _body,
    body_from_payload as _body_from_payload,
    label as _label,
    render_session as _render_session_lines,
)

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


_HANDOFF_KINDS = {"session", "handoff"}
_ACTIONABLE_KINDS = {"task", "session", "handoff"}
_SKIP_KINDS = {"log", "change"}
_SCHEMA_ITEM_CAP = 10


def prompt_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render fold data as a structured system prompt fragment.

    Filters resolved items, caps large sections, renders what's active.
    """
    populated = [s for s in data.sections if s.items]
    if not populated:
        return Block.text("(empty)", Style())

    return _schema_prompt(populated)


# --- Legacy alias ---
status_view = prompt_view


def _render_session(section: FoldSection) -> list[str]:
    """Render session as handoff content — message and produced artifacts."""
    return _render_session_lines(section)


def _schema_prompt(sections: list[FoldSection]) -> Block:
    """Structured schema prompt — renders active items per section.

    Filters out resolved/completed items — the prompt lens shows what's
    active, not what's done. Exception: session/handoff kinds get custom
    rendering (resolved state IS the handoff content).

    Attention budget: skip log/change, cap large sections to most recent items.
    """
    rows: list[Block] = []
    plain = Style()

    for s in sections:
        # Session/handoff: custom rendering
        if s.kind in _HANDOFF_KINDS:
            for line in _render_session(s):
                rows.append(Block.text(line, plain))
            continue

        # Skip noisy kinds — available via stream if needed
        if s.kind in _SKIP_KINDS:
            continue

        # Other kinds: filter resolved items
        items = [
            item for item in s.items
            if item.payload.get("status") not in RESOLVED_STATUSES
        ]
        if not items:
            continue

        # Split delegated items out
        mine = [i for i in items if not i.payload.get("delegate")]
        delegated = [i for i in items if i.payload.get("delegate")]

        # Cap large sections to most recent items
        remaining = 0
        if len(mine) > _SCHEMA_ITEM_CAP:
            sorted_items = sorted(mine, key=lambda i: i.ts or 0, reverse=True)
            remaining = len(mine) - _SCHEMA_ITEM_CAP
            mine = sorted_items[:_SCHEMA_ITEM_CAP]

        if not mine and not delegated:
            continue

        if rows:
            rows.append(Block.text("", plain))

        rows.append(Block.text(f"## {s.kind.upper()}", plain))

        for item in mine:
            label = _label(item, s.key_field)
            body = _body(item)
            if body:
                rows.append(Block.text(f"  {label}: {body}", plain))
            else:
                rows.append(Block.text(f"  {label}", plain))

        if remaining > 0:
            rows.append(Block.text(f"  ({remaining} more in store)", plain))

        # Delegated items: grouped summary
        if delegated:
            by_kind: dict[str, list[str]] = {}
            for item in delegated:
                d = item.payload["delegate"]
                by_kind.setdefault(d, []).append(_label(item, s.key_field))
            for d_kind, d_names in by_kind.items():
                rows.append(
                    Block.text(f"  *delegate {d_kind}*: {', '.join(d_names)}", plain)
                )

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
        body = _body_from_payload(payload, label)
        if body:
            rows.append(Block.text(f"{label}: {body}", plain))
        else:
            rows.append(Block.text(label, plain))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Stream helpers (not shared — stream data has different shape)
# ---------------------------------------------------------------------------

_LABEL_FIELDS = ("topic", "name", "title", "trigger", "summary", "message")


def _find_stream_label(payload: dict, key_field: str | None) -> str:
    """Extract primary label from a stream fact payload."""
    candidates = (key_field,) + _LABEL_FIELDS if key_field else _LABEL_FIELDS
    for field in candidates:
        if field and payload.get(field):
            return str(payload[field])
    for k, v in payload.items():
        if v:
            return str(v)
    return ""
