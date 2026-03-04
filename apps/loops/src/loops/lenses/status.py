"""Status lens — zoom-aware rendering for session status."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom, join_vertical

from ..commands.session import _format_date


def status_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render status data at the given zoom level.

    Uses ``data["sections"]`` (list of ``{kind, items, fold_type}``) when
    available, falling back to legacy keys for backwards compatibility.

    Zoom levels:
    - MINIMAL: one-liner counts per kind
    - SUMMARY: item labels with dates
    - DETAILED: + message bodies / secondary fields
    - FULL: + ISO timestamps instead of short dates
    """
    sections: list[dict] = data.get("sections", [])

    # Fallback: build sections from legacy keys if caller hasn't migrated
    if not sections:
        for key, kind, ft in [
            ("decisions", "decision", "by"), ("threads", "thread", "by"),
            ("tasks", "task", "by"), ("changes", "change", "collect"),
        ]:
            if data.get(key):
                sections.append({"kind": kind, "items": data[key], "fold_type": ft})

    populated = [s for s in sections if s["items"]]
    if not populated:
        return Block.text("No session data yet.", Style(dim=True), width=width)

    # MINIMAL: one-liner
    if zoom == Zoom.MINIMAL:
        parts = [f"{len(s['items'])} {s['kind']}s" for s in populated]
        return Block.text(", ".join(parts), Style(), width=width)

    rows: list[Block] = []
    header_style = Style(bold=True)
    dim_style = Style(dim=True)
    fmt = _format_ts_full if zoom == Zoom.FULL else _format_date

    for s in populated:
        if rows:
            rows.append(Block.text("", Style(), width=width))

        kind = s["kind"]
        items = s["items"]
        header = _section_header(kind, len(items))
        rows.append(Block.text(header, header_style, width=width))

        # Known kinds get field-specific rendering
        if kind == "decision":
            _render_decisions(rows, items, zoom, fmt, dim_style, width)
        elif kind == "thread":
            _render_threads(rows, items, fmt, width)
        elif kind == "task":
            _render_tasks(rows, items, zoom, fmt, dim_style, width)
        elif kind == "change":
            _render_changes(rows, items, zoom, fmt, dim_style, width)
        else:
            _render_generic(rows, items, kind, zoom, fmt, dim_style, width)

    return join_vertical(*rows)


_KNOWN_HEADERS: dict[str, str] = {
    "decision": "Decisions",
    "thread": "Open Threads",
    "task": "Active Tasks",
    "change": "Recent Changes",
}


def _section_header(kind: str, count: int) -> str:
    label = _KNOWN_HEADERS.get(kind, kind.title() + ("s" if kind[-1] != "s" else ""))
    return f"{label} ({count}):"


# --- known-kind renderers (preserve existing output) ----------------------


def _render_decisions(
    rows: list[Block], items: list, zoom: Zoom, fmt, dim_style: Style, width: int,
) -> None:
    for d in items:
        date = fmt(d["ts"])
        rows.append(Block.text(f"  {d['topic']} ({date})", Style(), width=width))
        if zoom >= Zoom.DETAILED and d.get("message"):
            rows.append(Block.text(f"    {d['message']}", dim_style, width=width))


def _render_threads(
    rows: list[Block], items: list, fmt, width: int,
) -> None:
    for t in items:
        date = fmt(t["ts"])
        status = t.get("status", "")
        line = f"  {t['name']}: {status} ({date})" if status else f"  {t['name']} ({date})"
        rows.append(Block.text(line, Style(), width=width))


def _render_tasks(
    rows: list[Block], items: list, zoom: Zoom, fmt, dim_style: Style, width: int,
) -> None:
    for t in items:
        date = fmt(t["ts"])
        rows.append(Block.text(f"  {t['name']}: {t['status']} ({date})", Style(), width=width))
        if zoom >= Zoom.DETAILED and t.get("summary"):
            rows.append(Block.text(f"    {t['summary']}", dim_style, width=width))


def _render_changes(
    rows: list[Block], items: list, zoom: Zoom, fmt, dim_style: Style, width: int,
) -> None:
    for c in items:
        date = fmt(c["ts"])
        rows.append(Block.text(f"  {c['summary']} ({date})", Style(), width=width))
        if zoom >= Zoom.DETAILED and c.get("files"):
            rows.append(Block.text(f"    files: {c['files']}", dim_style, width=width))


# --- generic renderer for declaration-driven kinds ------------------------


def _render_generic(
    rows: list[Block], items: list, kind: str, zoom: Zoom,
    fmt, dim_style: Style, width: int,
) -> None:
    """Render a kind we don't have specific formatting for.

    Uses the fold's grouping key (first non-underscore key) as the label.
    At DETAILED+, shows secondary fields.
    """
    for item in items:
        # Find label: use the fold's by-key, or first meaningful key
        label_keys = ("topic", "name", "title", "summary", "message")
        label = ""
        for lk in label_keys:
            if item.get(lk):
                label = str(item[lk])
                break
        if not label:
            # Fall back to first non-underscore key
            for k, v in item.items():
                if not k.startswith("_") and v:
                    label = f"{k}: {v}"
                    break
        if not label:
            label = kind

        ts = item.get("_ts", item.get("ts", ""))
        date = fmt(ts) if ts else ""
        line = f"  {label} ({date})" if date else f"  {label}"
        rows.append(Block.text(line, Style(), width=width))

        if zoom >= Zoom.DETAILED:
            for k, v in item.items():
                if k.startswith("_") or k in label_keys or not v:
                    continue
                rows.append(Block.text(f"    {k}: {v}", dim_style, width=width))


def _format_ts_full(ts) -> str:
    """ISO timestamp for FULL zoom."""
    from datetime import datetime, timezone

    if isinstance(ts, str):
        return ts
    if isinstance(ts, datetime):
        return ts.isoformat(timespec="seconds")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
    return "?"
