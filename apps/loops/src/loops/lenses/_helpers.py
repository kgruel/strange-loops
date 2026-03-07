"""Shared lens helpers — label extraction, body extraction, session rendering.

These patterns were duplicated across 4+ custom lenses. Centralized here
with parameterized variations.

Used by: prompt.py, identity_prompt.py, state.py, meta.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection


RESOLVED_STATUSES = frozenset({"resolved", "completed", "done", "closed"})

LABEL_FIELDS = ("topic", "name", "title", "trigger", "summary", "message")


def label(
    item: FoldItem,
    key_field: str | None,
    *,
    label_fields: tuple[str, ...] = LABEL_FIELDS,
) -> str:
    """Extract primary label from a FoldItem.

    Tries key_field first, then label_fields in order, then
    falls back to first non-empty payload field (formatted as "key: value",
    skipping "weight").
    """
    candidates = (key_field,) + label_fields if key_field else label_fields
    for field in candidates:
        if field and item.payload.get(field):
            return str(item.payload[field])
    for k, v in item.payload.items():
        if v and k != "weight":
            return f"{k}: {v}"
    return "?"


def body(
    item: FoldItem,
    key_field: str | None = None,
    *,
    skip: frozenset[str] = frozenset({"weight"}),
    label_fields: tuple[str, ...] = LABEL_FIELDS,
) -> str:
    """Find body text — first non-label, non-skip field value."""
    label_val = label(item, key_field, label_fields=label_fields)
    for k, v in item.payload.items():
        if not v or str(v) == label_val or k in skip:
            continue
        return str(v)
    return ""


def body_from_payload(
    payload: dict,
    used_label: str,
    *,
    skip: frozenset[str] = frozenset({"weight"}),
) -> str:
    """Find first non-label field value from a raw payload dict."""
    for k, v in payload.items():
        if not v or str(v) == used_label or k in skip:
            continue
        return str(v)
    return ""


def render_session(
    section: FoldSection,
    *,
    label_fn=None,
    body_fn=None,
) -> list[str]:
    """Render session items — active sessions with label + status."""
    _label = label_fn or label
    _body = body_fn or body
    lines: list[str] = []
    for item in section.items:
        lbl = _label(item, section.key_field)
        bdy = _body(item)
        lines.append("## SESSION")
        if bdy:
            lines.append(f"  {lbl}: {bdy}")
        else:
            lines.append(f"  {lbl}")
    return lines


def find_item(
    items: tuple[FoldItem, ...],
    name_value: str,
) -> FoldItem | None:
    """Find an item by its name/key field value."""
    for item in items:
        if item.payload.get("name") == name_value:
            return item
    return None
