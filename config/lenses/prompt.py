"""Prompt lenses — render fold/stream data for system prompts.

Optimized for LLM consumption: markdown sections, no truncation, no ANSI,
no zoom levels. Always renders the same shape regardless of context.

Attention budget drives rendering per kind:
- decisions: names only (reference material, drill down for body)
- threads: grouped by status (open vs parked = orientation)
- tasks: name + body (working context, actionable)
- sessions: active only, compact (presence signal)
- log/change: skipped (noise)

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
)

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


_SKIP_KINDS = {"log", "change", "message", "self", "principle", "observation", "intention"}
_NAMES_ONLY_KINDS = {"decision", "dissolution", "vision"}
_STATUS_GROUPED_KINDS = {"thread"}
_COMPACT_KINDS = {"session"}
_SCHEMA_ITEM_CAP = 10


def prompt_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render fold data as a structured system prompt fragment.

    Filters resolved items, caps large sections, renders what's active.
    """
    populated = [s for s in data.sections if s.items]
    if not populated:
        return Block.text("(empty)", Style())

    return _schema_prompt(populated)


def _schema_prompt(sections: list[FoldSection]) -> Block:
    """Structured schema prompt — ordered by attention priority.

    Rendering order reflects actionability:
    1. Working context (tasks) — what you're doing
    2. Orientation (threads) — what's being tracked
    3. Presence (sessions) — who's active
    4. Reference (decisions, dissolutions, visions) — background, names only

    Each kind gets a rendering strategy matched to its role.
    Skips log/change. Unknown kinds use default (name + body).
    """
    section_map = {s.kind: s for s in sections}
    all_lines: list[str] = []

    # --- Tier 1: Working context (default renderer — name + body) ---
    for kind in ("task",):
        if kind in section_map:
            lines = _render_default(section_map[kind])
            if lines:
                all_lines.extend(lines)

    # --- Tier 2: Orientation (status-grouped) ---
    for kind in _STATUS_GROUPED_KINDS:
        if kind in section_map:
            lines = _render_status_grouped(section_map[kind])
            if lines:
                if all_lines:
                    all_lines.append("")
                all_lines.extend(lines)

    # --- Tier 3: Presence (compact) ---
    for kind in _COMPACT_KINDS:
        if kind in section_map:
            lines = _render_compact_session(section_map[kind])
            if lines:
                if all_lines:
                    all_lines.append("")
                all_lines.extend(lines)

    # --- Tier 4: Reference (names only) ---
    for kind in ("decision", "dissolution", "vision"):
        if kind in section_map:
            lines = _render_names_only(section_map[kind])
            if lines:
                if all_lines:
                    all_lines.append("")
                all_lines.extend(lines)

    # --- Remaining: anything not handled above (default renderer) ---
    handled = _SKIP_KINDS | _NAMES_ONLY_KINDS | _STATUS_GROUPED_KINDS | _COMPACT_KINDS | {"task"}
    for s in sections:
        if s.kind in handled:
            continue
        lines = _render_default(s)
        if lines:
            if all_lines:
                all_lines.append("")
            all_lines.extend(lines)

    plain = Style()
    rows = [Block.text(line, plain) for line in all_lines]
    return join_vertical(*rows) if rows else Block.text("(empty)", plain)


# ---------------------------------------------------------------------------
# Rendering strategies
# ---------------------------------------------------------------------------

def _render_names_only(section: FoldSection) -> list[str]:
    """Names only — reference material. Recent first, no body.

    For decisions, dissolutions, visions: the topic name is the signal.
    Body is available via drill-down (loops read <vertex> --kind <kind>).
    """
    items = list(section.items)
    # Sort by recency
    sorted_items = sorted(items, key=lambda i: i.ts or 0, reverse=True)

    shown = sorted_items[:_SCHEMA_ITEM_CAP]
    remaining = len(sorted_items) - len(shown)

    lines = [f"## {section.kind.upper()}"]
    for item in shown:
        lines.append(f"  {_label(item, section.key_field)}")

    if remaining > 0:
        lines.append(f"  ({remaining} more in store)")

    return lines


def _render_status_grouped(section: FoldSection) -> list[str]:
    """Grouped by status — orientation signal.

    For threads: open vs parked tells the agent what's active vs noted.
    Delegated items rendered separately.
    """
    active = [
        i for i in section.items
        if i.payload.get("status") not in RESOLVED_STATUSES
    ]
    if not active:
        return []

    mine = [i for i in active if not i.payload.get("delegate")]
    delegated = [i for i in active if i.payload.get("delegate")]

    open_items = [i for i in mine if i.payload.get("status") not in {"parked"}]
    parked_items = [i for i in mine if i.payload.get("status") == "parked"]

    lines = [f"## {section.kind.upper()}"]

    if open_items:
        names = [_label(i, section.key_field) for i in open_items]
        lines.append(f"  open: {', '.join(names)}")

    if parked_items:
        names = [_label(i, section.key_field) for i in parked_items]
        lines.append(f"  parked: {', '.join(names)}")

    if delegated:
        by_delegate: dict[str, list[str]] = {}
        for item in delegated:
            d = item.payload["delegate"]
            by_delegate.setdefault(d, []).append(_label(item, section.key_field))
        for d_kind, d_names in by_delegate.items():
            lines.append(f"  *delegate {d_kind}*: {', '.join(d_names)}")

    return lines


def _render_compact_session(section: FoldSection) -> list[str]:
    """Compact presence signal — active sessions only.

    Filters to non-resolved/non-closed. One line listing who's online.
    """
    active = [
        i for i in section.items
        if i.payload.get("status") not in RESOLVED_STATUSES
    ]
    if not active:
        return []

    names = [_label(i, section.key_field) for i in active]
    return [f"## SESSION", f"  online: {', '.join(names)}"]


def _render_default(section: FoldSection) -> list[str]:
    """Name + body — working context. Actionable items.

    For tasks and any other kinds: show what's active with enough
    context to orient. Cap to most recent items.
    """
    items = [
        item for item in section.items
        if item.payload.get("status") not in RESOLVED_STATUSES
    ]
    if not items:
        return []

    mine = [i for i in items if not i.payload.get("delegate")]
    delegated = [i for i in items if i.payload.get("delegate")]

    remaining = 0
    if len(mine) > _SCHEMA_ITEM_CAP:
        sorted_items = sorted(mine, key=lambda i: i.ts or 0, reverse=True)
        remaining = len(mine) - _SCHEMA_ITEM_CAP
        mine = sorted_items[:_SCHEMA_ITEM_CAP]

    if not mine and not delegated:
        return []

    lines = [f"## {section.kind.upper()}"]

    for item in mine:
        label = _label(item, section.key_field)
        body = _body(item)
        if body:
            lines.append(f"  {label}: {body}")
        else:
            lines.append(f"  {label}")

    if remaining > 0:
        lines.append(f"  ({remaining} more in store)")

    if delegated:
        by_kind: dict[str, list[str]] = {}
        for item in delegated:
            d = item.payload["delegate"]
            by_kind.setdefault(d, []).append(_label(item, section.key_field))
        for d_kind, d_names in by_kind.items():
            lines.append(f"  *delegate {d_kind}*: {', '.join(d_names)}")

    return lines


# ---------------------------------------------------------------------------
# Stream prompt lens
# ---------------------------------------------------------------------------

def stream_prompt_view(data: dict[str, Any] | list[dict[str, Any]], zoom: Zoom, width: int) -> Block:
    """Render stream facts as system prompt content.

    Strips timestamps, date headers, and kind tags. Emits the full message
    of each fact — most recent first.
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
