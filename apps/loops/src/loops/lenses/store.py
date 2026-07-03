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
from ._grammar import block as _line
from ._grammar import ensure_utc, recency, stamp
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
        parts.append(f"fresh {recency(freshness)}")

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
        fresh_str = recency(freshness_dt) if freshness_dt else ""
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
        fresh_str = recency(freshness_dt) if freshness_dt else ""
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
        key=lambda kv: ensure_utc(kv[1]["latest"]) if isinstance(kv[1].get("latest"), datetime) else _epoch_min,
        reverse=True,
    )

    for i, (kind, info) in enumerate(sorted_kinds):
        count = info["count"]
        freshness_dt = info.get("latest")
        fresh_str = recency(freshness_dt) if freshness_dt else "never"
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
        title_parts.append(f"fresh {recency(freshness)}")
    title = " · ".join(title_parts)

    return border(inner, ROUNDED, p.chrome, title=title, title_style=p.header)


# ---------------------------------------------------------------------------
# Tick chain — attestation read surface (store ticks [--chain])
# ---------------------------------------------------------------------------


def tick_chain_view(
    data: dict,
    zoom: Zoom,
    width: int | None,
    palette: LoopsPalette | None = None,
    *,
    piped: bool | None = None,
) -> Block:
    """Render a store's tick series, newest-first.

    ``piped=True`` forces width=None — the agent channel never clips.

    Default projection (plain ``store ticks``) is density — items, facts,
    and per-window delta. ``--chain`` switches to the attestation
    projection — chain linkage, signature presence, and the window cursor
    per tick. The chain projection is a READ of the stored envelope, not a
    re-verification: ``store verify`` walks the chain in append order and
    checks integrity; this lists what each tick's stored attestation flags
    say (signed is per-TICK; per-fact signatures are verify's job).

    ``data`` shape: ``{vertex, chain_mode: bool, chain: {ticks, chained,
    signed, legacy}, since: str | None, windows: [TickWindow-as-dict, ...]}``.
    """
    if piped:
        width = None  # piped register never clips (information-faithful)

    p = palette or DEFAULT_PALETTE
    vertex = data.get("vertex", "")
    windows = data.get("windows", [])
    chain = data.get("chain", {})
    attest = bool(data.get("chain_mode"))

    if not windows:
        # Distinguish an empty --since window from a genuinely empty store —
        # "No ticks in this store" on a populated store is a false negative.
        since = data.get("since")
        msg = (
            f"No ticks in the last {since}."
            if since
            else "No ticks in this store."
        )
        return _line(msg, p.metadata, width)

    rollup = f"{vertex} · {len(windows)} ticks"
    if attest:
        rollup += (
            f" · {chain.get('chained', 0)} chained"
            f" · {chain.get('signed', 0)} signed"
            f" · {chain.get('legacy', 0)} legacy"
        )
    if zoom == Zoom.MINIMAL:
        return _line(rollup, p.metadata, width)

    dim = Style(dim=True)
    rows: list[Block] = [_line(rollup, p.header, width)]
    for w in windows:
        time_str = stamp(w["ts"])
        idx = f"#{w.get('index', 0)}"
        name = w.get("name", "")
        if attest:
            link = "linked" if w.get("chained") else "legacy"
            sig = "signed" if w.get("signed") else "unsigned"
            rows.append(_line(f"  {time_str} {idx} {name} · {link} · {sig}", Style(), width))
            if zoom >= Zoom.DETAILED and w.get("fact_cursor"):
                ckind = w.get("cursor_kind") or "?"
                preview = w.get("cursor_preview") or ""
                cursor = f'{ckind}: "{preview}"' if preview else ckind
                rows.append(_line(f"        cursor → {cursor}", dim, width))
        else:
            trigger = w.get("boundary_trigger") or name
            rows.append(_line(f"  {time_str} {idx} {trigger}", Style(), width))
            if zoom >= Zoom.DETAILED:
                delta = ""
                if w.get("delta_added") or w.get("delta_updated"):
                    delta = f" · +{w.get('delta_added', 0)} ~{w.get('delta_updated', 0)}"
                rows.append(_line(
                    f"        fold: {w.get('total_items', 0)} items · "
                    f"{w.get('total_facts', 0)} facts{delta}",
                    dim, width,
                ))
        if zoom >= Zoom.FULL and w.get("since") is not None:
            observer = f" · {w['observer']}" if w.get("observer") else ""
            rows.append(_line(
                f"        window: {stamp(w['since'])} → {time_str}{observer}",
                dim, width,
            ))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Stats — count surface (store stats [--by-kind])
# ---------------------------------------------------------------------------


def stats_view(
    data: dict,
    zoom: Zoom,
    width: int | None,
    palette: LoopsPalette | None = None,
) -> Block:
    """Render store statistics — topline totals, and (``--by-kind``) a
    count-descending per-kind tally.

    ``data`` shape: ``{vertex, by_kind: bool, total_facts, total_ticks,
    kind_count, kinds: [{kind, count}, ...] sorted count-desc}``. The
    per-kind table is gated on ``--by-kind`` (honesty rule: the flag is
    what adds the table).
    """
    p = palette or DEFAULT_PALETTE
    vertex = data.get("vertex", "")
    total_facts = data.get("total_facts", 0)
    total_ticks = data.get("total_ticks", 0)
    kind_count = data.get("kind_count", 0)
    kinds = data.get("kinds", [])
    by_kind = bool(data.get("by_kind"))

    rollup = (
        f"{vertex} · {_format_count(total_facts)} facts · "
        f"{kind_count} kinds · {_format_count(total_ticks)} ticks"
    )
    if zoom == Zoom.MINIMAL or not by_kind:
        return _line(rollup, p.metadata, width)

    rows: list[Block] = [_line(rollup, p.header, width)]
    if not kinds:
        rows.append(_line("  (empty store)", p.metadata, width))
        return join_vertical(*rows)

    name_w = max((len(str(k["kind"])) for k in kinds), default=4)
    for k in kinds:  # already count-descending from the fetch
        count = k["count"]
        pct = (count / total_facts * 100) if total_facts else 0.0
        line = f"  {str(k['kind']).ljust(name_w)}  {_format_count(count):>6}  {pct:4.1f}%"
        rows.append(_line(line, p.kind_style(k["kind"]), width))

    return join_vertical(*rows)


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


def _time_range(kinds: dict) -> str:
    """Format time range across all kinds: 'Feb 28 – Mar 1'."""
    earliest = None
    latest = None
    for info in kinds.values():
        e = info.get("earliest")
        l = info.get("latest")
        if isinstance(e, datetime):
            e = ensure_utc(e)
            if earliest is None or e < earliest:
                earliest = e
        if isinstance(l, datetime):
            l = ensure_utc(l)
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
