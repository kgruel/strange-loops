"""State lens — session orientation view.

The 'where are we' lens for session start and mid-session check-in.
Shows observer, open tasks, active threads, recent decisions — the
working context at a glance. Not exhaustive, not archival — oriented.

Zoom levels:
- MINIMAL: one-liner counts (open tasks, active threads)
- SUMMARY: tasks with priority, thread names, recent decisions
- DETAILED: + decision rationale, thread context
- FULL: + timestamps, observers, all metadata
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

from loops.lenses._helpers import (
    RESOLVED_STATUSES,
    body as _helpers_body,
    label as _helpers_label,
)

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


_STATE_LABEL_FIELDS = ("topic", "name", "title", "summary")
_STATE_BODY_SKIP = frozenset({"status", "priority", "weight"})
_PRIORITY_ORDER = {"now": 0, "next": 1, "after": 2, "later": 3}


def _label(item: FoldItem, key_field: str | None) -> str:
    return _helpers_label(item, key_field, label_fields=_STATE_LABEL_FIELDS)


def _body(item: FoldItem, key_field: str | None = None) -> str:
    return _helpers_body(item, key_field, skip=_STATE_BODY_SKIP,
                         label_fields=_STATE_LABEL_FIELDS)


def fold_view(
    data: FoldState,
    zoom: Zoom,
    width: int | None,
    *,
    vertex_name: str | None = None,
) -> Block:
    """Render working state at the given zoom level."""
    sections = {s.kind: s for s in data.sections if s.items}
    if not sections:
        return Block.text("No data yet.", Style(dim=True), width=width)

    vname = vertex_name or data.vertex or "unknown"

    if zoom == Zoom.MINIMAL:
        return _minimal(sections, vname, width)

    rows: list[Block] = []
    _header(rows, sections, vname, width)

    # Tasks — the actionable items
    if "task" in sections:
        _tasks(rows, sections["task"], zoom, width)

    # Threads — what's being tracked
    if "thread" in sections:
        _threads(rows, sections["thread"], zoom, width)

    # Decisions — recent working positions
    if "decision" in sections:
        _decisions(rows, sections["decision"], zoom, width)

    # Session — latest session state
    if "session" in sections:
        _session(rows, sections["session"], zoom, width)

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# MINIMAL
# ---------------------------------------------------------------------------


def _minimal(
    sections: dict[str, FoldSection],
    vname: str,
    width: int | None,
) -> Block:
    parts = [vname]

    tasks = sections.get("task")
    if tasks:
        open_tasks = [i for i in tasks.items if i.payload.get("status") not in RESOLVED_STATUSES]
        if open_tasks:
            parts.append(f"{len(open_tasks)} tasks")

    threads = sections.get("thread")
    if threads:
        open_threads = [i for i in threads.items if i.payload.get("status") not in RESOLVED_STATUSES]
        if open_threads:
            parts.append(f"{len(open_threads)} threads")

    decisions = sections.get("decision")
    if decisions:
        parts.append(f"{len(decisions.items)} decisions")

    return Block.text(" · ".join(parts), Style(), width=width)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def _header(
    rows: list[Block],
    sections: dict[str, FoldSection],
    vname: str,
    width: int | None,
) -> None:
    # Collect observers across all items
    observers: set[str] = set()
    for s in sections.values():
        for item in s.items:
            if item.observer:
                observers.add(item.observer)

    obs_str = ", ".join(sorted(observers)) if observers else "unknown"
    header = f"{vname} · observers: {obs_str}"
    rows.append(Block.text(header, Style(bold=True), width=width))
    rows.append(Block.text("", Style(), width=width))


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def _tasks(
    rows: list[Block],
    section: FoldSection,
    zoom: Zoom,
    width: int | None,
) -> None:
    open_items = [i for i in section.items if i.payload.get("status") not in RESOLVED_STATUSES]
    resolved = len(section.items) - len(open_items)

    if not open_items:
        rows.append(Block.text(f"Tasks: all {resolved} resolved", Style(dim=True), width=width))
        rows.append(Block.text("", Style(), width=width))
        return

    rows.append(Block.text(
        f"Tasks ({len(open_items)} open, {resolved} resolved):",
        Style(bold=True),
        width=width,
    ))

    # Sort by priority
    def priority_key(item: FoldItem) -> int:
        return _PRIORITY_ORDER.get(item.payload.get("priority", ""), 99)

    for item in sorted(open_items, key=priority_key):
        name = _label(item, section.key_field)
        priority = item.payload.get("priority", "")
        status = item.payload.get("status", "open")
        pri_tag = f" [{priority}]" if priority else ""

        line = f"  {name}{pri_tag}: {status}"
        rows.append(Block.text(line, Style(), width=width))

        if zoom >= Zoom.DETAILED:
            msg = item.payload.get("message", "")
            if msg:
                rows.append(Block.text(f"    {msg}", Style(dim=True), width=width))

        if zoom >= Zoom.FULL and item.ts:
            rows.append(Block.text(f"    updated: {_fmt_ts(item.ts)}", Style(dim=True), width=width))

    rows.append(Block.text("", Style(), width=width))


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


def _threads(
    rows: list[Block],
    section: FoldSection,
    zoom: Zoom,
    width: int | None,
) -> None:
    open_items = [i for i in section.items if i.payload.get("status") not in RESOLVED_STATUSES]
    resolved = len(section.items) - len(open_items)

    if not open_items:
        rows.append(Block.text(f"Threads: all {resolved} resolved", Style(dim=True), width=width))
        rows.append(Block.text("", Style(), width=width))
        return

    rows.append(Block.text(
        f"Threads ({len(open_items)} open, {resolved} resolved):",
        Style(bold=True),
        width=width,
    ))

    if zoom <= Zoom.SUMMARY:
        # Compact: just names
        names = [_label(i, section.key_field) for i in open_items]
        # Wrap into lines that fit width
        line = "  " + ", ".join(names)
        rows.append(Block.text(line, Style(), width=width))
    else:
        # DETAILED+: name + context
        for item in open_items:
            name = _label(item, section.key_field)
            rows.append(Block.text(f"  {name}", Style(), width=width))
            if zoom >= Zoom.DETAILED:
                msg = item.payload.get("message", "")
                if msg:
                    snippet = msg[:120] + "…" if len(msg) > 120 else msg
                    rows.append(Block.text(f"    {snippet}", Style(dim=True), width=width))

    rows.append(Block.text("", Style(), width=width))


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


def _decisions(
    rows: list[Block],
    section: FoldSection,
    zoom: Zoom,
    width: int | None,
    max_shown: int = 5,
) -> None:
    # Most recent first
    sorted_items = sorted(section.items, key=lambda i: i.ts or 0, reverse=True)
    shown = sorted_items[:max_shown]
    remaining = len(sorted_items) - len(shown)

    rows.append(Block.text(
        f"Recent decisions ({len(section.items)} total):",
        Style(bold=True),
        width=width,
    ))

    for item in shown:
        name = _label(item, section.key_field)
        rows.append(Block.text(f"  {name}", Style(), width=width))

        if zoom >= Zoom.DETAILED:
            # Show the body — first non-label field
            body = _body(item, section.key_field)
            if body:
                snippet = body[:120] + "…" if len(body) > 120 else body
                rows.append(Block.text(f"    {snippet}", Style(dim=True), width=width))

        if zoom >= Zoom.FULL and item.ts:
            rows.append(Block.text(f"    {_fmt_ts(item.ts)}", Style(dim=True), width=width))

    if remaining > 0:
        rows.append(Block.text(f"  ({remaining} more)", Style(dim=True), width=width))

    rows.append(Block.text("", Style(), width=width))


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


def _session(
    rows: list[Block],
    section: FoldSection,
    zoom: Zoom,
    width: int | None,
) -> None:
    # Show most recent session
    sorted_items = sorted(section.items, key=lambda i: i.ts or 0, reverse=True)
    if not sorted_items:
        return

    latest = sorted_items[0]
    message = latest.payload.get("message", "")
    label = _label(latest, section.key_field)

    if message:
        rows.append(Block.text(f"Session: {label}", Style(bold=True), width=width))
        rows.append(Block.text(f"  {message}", Style(), width=width))

    if zoom >= Zoom.FULL and latest.ts:
        rows.append(Block.text(f"  {_fmt_ts(latest.ts)}", Style(dim=True), width=width))

    rows.append(Block.text("", Style(), width=width))


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
