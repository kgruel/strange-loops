"""Store lens — fidelity-based rendering for store inspection.

Four fidelity levels:
- MINIMAL: one-liner count summary with fact time range
- SUMMARY: kind table with sparkline + count + freshness + content gist
- DETAILED: per-kind sections with recent content, counts as metadata
- FULL: bordered card, topline summary, kind sections sorted by recency
"""

from __future__ import annotations

from datetime import datetime, timezone

from painted import Block, Style, Zoom, border, join_vertical, ROUNDED

from ..palette import DEFAULT_PALETTE, LoopsPalette
from .gist import content_gist


def store_view(
    data: dict,
    zoom: Zoom,
    width: int,
    palette: LoopsPalette | None = None,
) -> Block:
    """Render store summary at the given fidelity level."""
    p = palette or DEFAULT_PALETTE
    if zoom == Zoom.MINIMAL:
        return _render_minimal(data, width, p)
    if zoom == Zoom.SUMMARY:
        return _render_summary(data, width, p)
    if zoom == Zoom.DETAILED:
        return _render_detailed(data, width, p)
    return _render_full(data, width, p)


# ---------------------------------------------------------------------------
# MINIMAL — one-liner
# ---------------------------------------------------------------------------


def _render_minimal(data: dict, width: int, p: LoopsPalette) -> Block:
    """One-line: '5 kinds · 69 facts · Feb 28 – Mar 1 · fresh 6h ago'."""
    facts_total = data["facts"]["total"]
    fact_kinds = data["facts"].get("kinds", {})
    kind_count = len(fact_kinds)

    # Format fact count
    facts_str = _format_count(facts_total)

    parts = [f"{kind_count} kinds", f"{facts_str} facts"]

    # Time range from earliest/latest across all kinds
    time_range = _time_range(fact_kinds)
    if time_range:
        parts.append(time_range)

    freshness = data.get("freshness")
    if freshness is not None:
        parts.append(f"fresh {_relative_time(freshness)}")

    text = " · ".join(parts)
    return Block.text(text, p.metadata, width=width)


# ---------------------------------------------------------------------------
# SUMMARY — kind table with content gist
# ---------------------------------------------------------------------------


def _render_summary(data: dict, width: int, p: LoopsPalette) -> Block:
    """Kind table: name + sparkline + count + freshness + latest content gist."""
    fact_kinds = data["facts"].get("kinds", {})

    if not fact_kinds:
        return Block.text("(empty store)", p.metadata, width=width)

    rows: list[Block] = []

    # Compute column widths
    max_name = max(len(str(k)) for k in fact_kinds) if fact_kinds else 10
    name_col = min(max_name + 2, width // 3)

    # Sparkline data lives in ticks, but we render facts-first
    # Get sparklines from ticks if available, keyed by name
    tick_names = data["ticks"].get("names", {})
    tick_sparklines = {name: info.get("sparkline", "") for name, info in tick_names.items()}

    for kind, info in fact_kinds.items():
        count = info["count"]
        freshness_dt = info.get("latest")
        fresh_str = _relative_time(freshness_dt) if freshness_dt else ""
        sparkline = tick_sparklines.get(kind, "")

        # Kind name — colored
        kind_style = p.kind_style(kind)
        name_text = str(kind).ljust(name_col)[:name_col]

        # Stats — metadata styled
        count_str = _format_count(count)
        stats = f" {sparkline}  {count_str:>5}  {fresh_str:>8}"

        # Content gist from latest payload
        gist = ""
        sample = info.get("sample_payload")
        if isinstance(sample, dict):
            used = len(name_text) + len(stats) + 2
            remaining = width - used
            if remaining > 15:
                gist = content_gist(kind, sample, remaining)

        # Build composite line with styled segments
        # For now: kind name in kind color, rest in metadata
        line = name_text + stats
        if gist:
            line += "  " + gist
        line = line[:width]

        # Apply kind color to the name portion only via a full-line block
        # (Block.text is single-style; for multi-style we'd need Span/Line)
        # Pragmatic: use kind_style for the whole row — the gist is the content
        rows.append(Block.text(line, kind_style, width=width))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# DETAILED — per-kind sections with recent content
# ---------------------------------------------------------------------------


def _render_detailed(data: dict, width: int, p: LoopsPalette) -> Block:
    """Per-kind sections with last 3 items, counts as header metadata."""
    fact_kinds = data["facts"].get("kinds", {})

    if not fact_kinds:
        return Block.text("(empty store)", p.metadata, width=width)

    rows: list[Block] = []

    for kind, info in fact_kinds.items():
        count = info["count"]
        freshness_dt = info.get("latest")
        fresh_str = _relative_time(freshness_dt) if freshness_dt else ""
        count_str = _format_count(count)

        # Section header: kind name + count + freshness
        header = f"{kind} ({count_str})  {fresh_str}"
        kind_style = p.kind_style(kind)
        rows.append(Block.text(header, Style(bold=True, fg=kind_style.fg), width=width))

        # Recent items as content gists
        recent = info.get("recent", [])
        if recent:
            for payload in recent[:3]:
                if isinstance(payload, dict):
                    gist = content_gist(kind, payload, width - 4)
                    rows.append(Block.text(f"  {gist}", p.content, width=width))
        elif info.get("sample_payload"):
            gist = content_gist(kind, info["sample_payload"], width - 4)
            rows.append(Block.text(f"  {gist}", p.content, width=width))

        rows.append(Block.empty(width, 1))

    # Remove trailing empty
    _strip_trailing_empty(rows)

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# FULL — bordered card with topline and kind sections
# ---------------------------------------------------------------------------


def _render_full(data: dict, width: int, p: LoopsPalette) -> Block:
    """Bordered card: topline summary, kind sections sorted by recency."""
    fact_kinds = data["facts"].get("kinds", {})

    if not fact_kinds:
        return Block.text("(empty store)", p.metadata, width=width)

    # Inner width (border takes 2 chars)
    inner_w = width - 2

    rows: list[Block] = []

    # Sort kinds by latest activity (most recent first)
    _epoch_min = datetime.min.replace(tzinfo=timezone.utc)
    sorted_kinds = sorted(
        fact_kinds.items(),
        key=lambda kv: _ensure_utc(kv[1]["latest"]) if isinstance(kv[1].get("latest"), datetime) else _epoch_min,
        reverse=True,
    )

    for i, (kind, info) in enumerate(sorted_kinds):
        count = info["count"]
        freshness_dt = info.get("latest")
        fresh_str = _relative_time(freshness_dt) if freshness_dt else "never"
        count_str = _format_count(count)
        kind_style = p.kind_style(kind)

        # Kind header: name left, count + freshness right
        right = f"{count_str} · {fresh_str}"
        left = kind
        # Fill with dots between left and right
        fill_len = inner_w - len(left) - len(right) - 2
        if fill_len > 2:
            fill = " " + "·" * fill_len + " "
        else:
            fill = "  "
        header_line = left + fill + right
        rows.append(Block.text(
            header_line,
            Style(bold=True, fg=kind_style.fg),
            width=inner_w,
        ))

        # Content: latest items
        recent = info.get("recent", [])
        if recent:
            for payload in recent[:3]:
                if isinstance(payload, dict):
                    gist = content_gist(kind, payload, inner_w - 2)
                    rows.append(Block.text(f"  {gist}", p.content, width=inner_w))
        elif info.get("sample_payload"):
            gist = content_gist(kind, info["sample_payload"], inner_w - 2)
            rows.append(Block.text(f"  {gist}", p.content, width=inner_w))
        else:
            rows.append(Block.text("  (no data yet)", p.metadata, width=inner_w))

        # Separator between kinds (not after last)
        if i < len(sorted_kinds) - 1:
            rows.append(Block.empty(inner_w, 1))

    inner = join_vertical(*rows)

    # Topline summary as border title
    facts_total = data["facts"]["total"]
    kind_count = len(fact_kinds)
    freshness = data.get("freshness")
    title_parts = [f"{kind_count} kinds", f"{_format_count(facts_total)} facts"]
    if freshness is not None:
        title_parts.append(f"fresh {_relative_time(freshness)}")
    title = " · ".join(title_parts)

    return border(inner, ROUNDED, p.chrome, title=title, title_style=p.header)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_count(n: int) -> str:
    """Human-friendly count: 1703 -> '1.7k', 42 -> '42'."""
    if n >= 10_000:
        return f"{n // 1000}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize to UTC — assume naive datetimes are UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _relative_time(dt: datetime) -> str:
    """Human-friendly relative timestamp."""
    if not isinstance(dt, datetime):
        return "?"
    now = datetime.now(timezone.utc)
    delta = now - _ensure_utc(dt)
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


def _time_range(kinds: dict) -> str:
    """Format time range across all kinds: 'Feb 28 – Mar 1'."""
    earliest = None
    latest = None
    for info in kinds.values():
        e = info.get("earliest")
        l = info.get("latest")
        if isinstance(e, datetime):
            e = _ensure_utc(e)
            if earliest is None or e < earliest:
                earliest = e
        if isinstance(l, datetime):
            l = _ensure_utc(l)
            if latest is None or l > latest:
                latest = l

    if earliest is None or latest is None:
        return ""

    start = earliest.strftime("%b %d")
    end = latest.strftime("%b %d")
    if start == end:
        return start
    return f"{start} – {end}"


def _strip_trailing_empty(rows: list[Block]) -> None:
    """Remove trailing empty/whitespace-only rows in place."""
    while rows and rows[-1].height == 1:
        text = "".join(c.char for c in rows[-1].row(0)).strip()
        if text == "":
            rows.pop()
        else:
            break
