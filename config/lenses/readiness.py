"""Readiness lens -- what's next, what's open, what needs resolution?

Classifies threads and tasks from a project vertex into four categories:
  READY:      design done, implementation is next
  RESOLUTION: open questions before building
  DESIGN:     open threads, not yet converged
  PARKED:     valid but not now

Dissolved/resolved/completed items are excluded entirely.

Zoom levels:
- MINIMAL: counts per category ("3 ready . 2 resolution . 5 design . 4 parked")
- SUMMARY: category headers + item names + one-line summary
- DETAILED: + thread/task body text
- FULL: + timestamps, observers, related decisions
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

from loops.lenses._helpers import (
    RESOLVED_STATUSES,
    label as _helpers_label,
    body as _helpers_body,
)

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_CLOSED = frozenset(RESOLVED_STATUSES | {"dissolved", "shipped"})

_PARKED_KEYWORDS = ("parked", "deferred", "later", "not now", "not blocking")

_READY_KEYWORDS = (
    "design complete", "implementation plan", "approved",
    "ready to build", "ready for implementation",
)

_RESOLUTION_KEYWORDS = (
    "needs resolution", "needs-resolution", "open question",
    "before building", "blocker", "blocked",
)

_LABEL_FIELDS = ("topic", "name", "title", "summary")
_BODY_SKIP = frozenset({"status", "priority", "weight"})


def _label(item: FoldItem, key_field: str | None) -> str:
    return _helpers_label(item, key_field, label_fields=_LABEL_FIELDS)


def _body(item: FoldItem, key_field: str | None = None) -> str:
    return _helpers_body(item, key_field, skip=_BODY_SKIP,
                         label_fields=_LABEL_FIELDS)


def _text_blob(item: FoldItem) -> str:
    """Concatenate all string payload values for keyword matching."""
    parts = []
    for v in item.payload.values():
        if isinstance(v, str):
            parts.append(v.lower())
    return " ".join(parts)


def _classify(item: FoldItem) -> str | None:
    """Classify a single item. Returns None for closed items."""
    status = str(item.payload.get("status", "")).lower()
    if status in _CLOSED:
        return None

    blob = _text_blob(item)

    # Check parked first — explicit park overrides other signals
    if status == "parked" or any(kw in blob for kw in _PARKED_KEYWORDS):
        return "parked"

    # Ready — design done signals
    if any(kw in blob for kw in _READY_KEYWORDS):
        return "ready"

    # Needs resolution — questions/blockers
    if any(kw in blob for kw in _RESOLUTION_KEYWORDS):
        return "resolution"
    # Question marks in message/body text (not in label) suggest open questions
    msg = item.payload.get("message", "") or item.payload.get("text", "")
    if isinstance(msg, str) and "?" in msg and "needs" in blob:
        return "resolution"

    # Everything else open = design
    return "design"


# ---------------------------------------------------------------------------
# Category metadata
# ---------------------------------------------------------------------------

_CATEGORIES = (
    ("ready", "Ready to build", "design done, implementation is next"),
    ("resolution", "Needs resolution", "open questions before building"),
    ("design", "Design", "open threads, not yet converged"),
    ("parked", "Parked", "valid but not now"),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fold_view(
    data: FoldState,
    zoom: Zoom,
    width: int | None,
    **kwargs,
) -> Block:
    """Render readiness-classified tree at the given zoom level."""
    # Collect thread + task items
    items_by_cat: dict[str, list[tuple[FoldItem, str | None]]] = {
        cat: [] for cat, _, _ in _CATEGORIES
    }

    for section in data.sections:
        if section.kind not in ("thread", "task"):
            continue
        for item in section.items:
            cat = _classify(item)
            if cat is None:
                continue
            items_by_cat[cat].append((item, section.key_field))

    total = sum(len(v) for v in items_by_cat.values())
    if total == 0:
        return Block.text("(nothing tracked)", Style(dim=True), width=width)

    if zoom <= Zoom.MINIMAL:
        return _minimal(items_by_cat, width)

    return _tree(items_by_cat, data, zoom, width)


# ---------------------------------------------------------------------------
# MINIMAL
# ---------------------------------------------------------------------------

def _minimal(
    items_by_cat: dict[str, list[tuple[FoldItem, str | None]]],
    width: int | None,
) -> Block:
    parts = []
    for cat, label, _ in _CATEGORIES:
        n = len(items_by_cat[cat])
        if n > 0:
            parts.append(f"{n} {label.lower()}")
    return Block.text(" · ".join(parts), Style(), width=width)


# ---------------------------------------------------------------------------
# SUMMARY / DETAILED / FULL tree
# ---------------------------------------------------------------------------

def _tree(
    items_by_cat: dict[str, list[tuple[FoldItem, str | None]]],
    data: FoldState,
    zoom: Zoom,
    width: int | None,
) -> Block:
    rows: list[Block] = []
    plain = Style()
    dim = Style(dim=True)
    bold = Style(bold=True)

    # Decisions for context at FULL zoom
    decisions: list[FoldItem] = []
    if zoom >= Zoom.FULL:
        for section in data.sections:
            if section.kind == "decision":
                decisions.extend(section.items)

    for cat, cat_label, cat_desc in _CATEGORIES:
        items = items_by_cat[cat]
        if not items:
            continue

        if rows:
            rows.append(Block.text("", plain, width=width))

        header = f"{cat_label} ({len(items)})"
        if zoom >= Zoom.DETAILED:
            header += f" — {cat_desc}"
        rows.append(Block.text(header, bold, width=width))

        for item, key_field in items:
            name = _label(item, key_field)
            status = item.payload.get("status", "")
            status_tag = f" [{status}]" if status else ""

            # SUMMARY: name + one-line summary
            body_text = _body(item, key_field)
            if body_text and zoom >= Zoom.SUMMARY:
                snippet = body_text[:120] + "..." if len(body_text) > 120 else body_text
                rows.append(Block.text(f"  {name}{status_tag}: {snippet}", plain, width=width))
            else:
                rows.append(Block.text(f"  {name}{status_tag}", plain, width=width))

            # DETAILED: full body
            if zoom >= Zoom.DETAILED and body_text and len(body_text) > 120:
                rows.append(Block.text(f"    {body_text}", dim, width=width))

            # FULL: timestamps, observer
            if zoom >= Zoom.FULL:
                meta_parts = []
                if item.ts:
                    meta_parts.append(f"updated: {_fmt_ts(item.ts)}")
                if item.observer:
                    meta_parts.append(f"observer: {item.observer}")
                if meta_parts:
                    rows.append(Block.text(f"    {', '.join(meta_parts)}", dim, width=width))

    # FULL: append recent decisions as context
    if zoom >= Zoom.FULL and decisions:
        rows.append(Block.text("", plain, width=width))
        rows.append(Block.text(f"Recent decisions ({len(decisions)}):", bold, width=width))
        sorted_decisions = sorted(decisions, key=lambda i: i.ts or 0, reverse=True)
        for item in sorted_decisions[:5]:
            topic = item.payload.get("topic", "?")
            rows.append(Block.text(f"  {topic}", plain, width=width))
            if item.ts:
                rows.append(Block.text(f"    {_fmt_ts(item.ts)}", dim, width=width))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ts(ts) -> str:
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(ts, str):
        return ts
    return "?"
