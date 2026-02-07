"""Store lens — zoom-based rendering for store inspection."""
from __future__ import annotations

from datetime import datetime, timezone

from cells import Block, Style, Zoom, join_vertical
from cells.lens import shape_lens


def store_view(data: dict, zoom: Zoom, width: int) -> Block:
    """Render store summary at the given zoom level.

    Zoom levels:
    - MINIMAL: one-line summary
    - SUMMARY: per-kind table with counts and freshness
    - DETAILED: per-tick section with latest payload at zoom 1
    - FULL: tick payloads at zoom 2 + recent fact payloads
    """
    if zoom == Zoom.MINIMAL:
        return _render_minimal(data, width)
    if zoom == Zoom.SUMMARY:
        return _render_summary(data, width)
    if zoom == Zoom.DETAILED:
        return _render_detailed(data, width)
    return _render_full(data, width)


def _render_minimal(data: dict, width: int) -> Block:
    """One-line: '5 kinds, 6.4k facts, 15 ticks | fresh 2h ago'."""
    facts_total = data["facts"]["total"]
    ticks_total = data["ticks"]["total"]
    kinds = len(data["facts"].get("kinds", {}))

    # Format fact count
    if facts_total >= 1000:
        facts_str = f"{facts_total / 1000:.1f}k"
    else:
        facts_str = str(facts_total)

    parts = [f"{kinds} kinds, {facts_str} facts, {ticks_total} ticks"]

    freshness = data.get("freshness")
    if freshness is not None:
        parts.append(f"fresh {_relative_time(freshness)}")

    text = " | ".join(parts)
    return Block.text(text, Style(), width=width)


def _render_summary(data: dict, width: int) -> Block:
    """Per-kind table grouped into Facts + Ticks sections."""
    rows: list[Block] = []
    header_style = Style(bold=True)
    dim_style = Style(dim=True)

    # Facts section
    fact_kinds = data["facts"].get("kinds", {})
    if fact_kinds:
        rows.append(Block.text("Facts", header_style, width=width))
        rows.append(_kind_table(fact_kinds, width, show_sample=True))
        rows.append(Block.empty(width, 1))

    # Ticks section
    tick_names = data["ticks"].get("names", {})
    if tick_names:
        rows.append(Block.text("Ticks", header_style, width=width))
        rows.append(_kind_table(tick_names, width, show_sample=False))

    if not rows:
        return Block.text("(empty store)", dim_style, width=width)

    return join_vertical(*rows)


def _render_detailed(data: dict, width: int) -> Block:
    """Per-tick section with header + latest payload via shape_lens at zoom 1."""
    rows: list[Block] = []
    header_style = Style(bold=True)
    dim_style = Style(dim=True)

    # Tick sections
    tick_names = data["ticks"].get("names", {})
    for name, info in tick_names.items():
        count = info["count"]
        fresh = _relative_time(info["latest"]) if "latest" in info else "?"
        rows.append(Block.text(
            f"[{name}] {count} ticks, fresh {fresh}",
            header_style, width=width,
        ))

        payload = info.get("latest_payload")
        if payload:
            body = shape_lens(payload, zoom=1, width=width - 2)
            rows.append(body)
        rows.append(Block.empty(width, 1))

    # Fact summary
    fact_kinds = data["facts"].get("kinds", {})
    if fact_kinds:
        rows.append(Block.text("Facts", header_style, width=width))
        rows.append(_kind_table(fact_kinds, width, show_sample=True))

    if not rows:
        return Block.text("(empty store)", dim_style, width=width)

    # Remove trailing empty
    while rows and rows[-1].height == 1:
        text = "".join(c.char for c in rows[-1].row(0)).strip()
        if text == "":
            rows.pop()
        else:
            break

    return join_vertical(*rows)


def _render_full(data: dict, width: int) -> Block:
    """Tick payloads at zoom 2 + recent fact payloads per kind."""
    rows: list[Block] = []
    header_style = Style(bold=True)
    dim_style = Style(dim=True)

    # Tick sections with full payloads
    tick_names = data["ticks"].get("names", {})
    for name, info in tick_names.items():
        count = info["count"]
        fresh = _relative_time(info["latest"]) if "latest" in info else "?"
        rows.append(Block.text(
            f"[{name}] {count} ticks, fresh {fresh}",
            header_style, width=width,
        ))

        payload = info.get("latest_payload")
        if payload:
            body = shape_lens(payload, zoom=2, width=width - 2)
            rows.append(body)
        rows.append(Block.empty(width, 1))

    # Fact sections with recent payloads
    fact_kinds = data["facts"].get("kinds", {})
    for kind, info in fact_kinds.items():
        count = info["count"]
        fresh = _relative_time(info["latest"]) if "latest" in info else "?"
        rows.append(Block.text(
            f"[{kind}] {count} facts, fresh {fresh}",
            header_style, width=width,
        ))

        recent = info.get("recent", [])
        if recent:
            for payload in recent[:3]:
                body = shape_lens(payload, zoom=1, width=width - 2)
                rows.append(body)
        rows.append(Block.empty(width, 1))

    if not rows:
        return Block.text("(empty store)", dim_style, width=width)

    # Remove trailing empty
    while rows and rows[-1].height == 1:
        text = "".join(c.char for c in rows[-1].row(0)).strip()
        if text == "":
            rows.pop()
        else:
            break

    return join_vertical(*rows)


def _kind_table(kinds: dict, width: int, *, show_sample: bool) -> Block:
    """Render a kind -> stats table."""
    if not kinds:
        return Block.empty(width, 1)

    rows: list[Block] = []
    dim_style = Style(dim=True)

    # Calculate column widths
    max_name = max(len(str(k)) for k in kinds)
    name_col = min(max_name + 2, width // 3)

    for name, info in kinds.items():
        count = info["count"]
        fresh = _relative_time(info["latest"]) if "latest" in info else ""

        # Build line: name  count  freshness  [sample gist]
        name_text = str(name).ljust(name_col)[:name_col]
        stats = f"{count:>6}  {fresh:>8}"

        line = name_text + stats

        # Append sample payload gist if available
        if show_sample and "sample_payload" in info:
            sample = info["sample_payload"]
            remaining = width - len(line) - 2
            if remaining > 10 and isinstance(sample, dict):
                gist_keys = ", ".join(list(sample.keys())[:4])
                if len(gist_keys) > remaining:
                    gist_keys = gist_keys[:remaining - 1] + "\u2026"
                line += "  " + gist_keys

        line = line[:width]
        rows.append(Block.text(line, dim_style, width=width))

    return join_vertical(*rows)


def _relative_time(dt: datetime) -> str:
    """Human-friendly relative timestamp."""
    if not isinstance(dt, datetime):
        return "?"
    now = datetime.now(timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"
