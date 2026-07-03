"""Ticks lens — zoom-aware rendering of tick history and drill-down."""
from __future__ import annotations

from typing import Any

from painted import Block, Style, Zoom

from ._grammar import DateGrouper, clock, rail_glyph
from ._grammar import block as _block
from ._grammar import coerce_dt as _parse_ts
from ._grammar import duration as _format_duration


def ticks_view(data: dict[str, Any], zoom: Zoom, width: int | None,
               *, piped: bool | None = None) -> Block:
    """Render tick history at the given zoom level.

    Accepts {"ticks": [...], "vertex": str}.
    Each tick has: name, ts, since, origin, boundary, kind_counts.

    Zoom levels:
    - MINIMAL: tick count only
    - SUMMARY: date-grouped, time + boundary trigger + kind count summary
    - DETAILED: + per-kind counts, window duration
    - FULL: + since/ts timestamps, origin, all payload keys
    """
    is_piped = bool(piped or (piped is None and width is None))
    if is_piped:
        width = None  # piped register never clips (information-faithful)

    ticks = data.get("ticks", [])

    if not ticks:
        return _block("No ticks in the given time range.", Style(dim=True), width)

    if zoom == Zoom.MINIMAL:
        return _block(f"{len(ticks)} ticks", Style(), width)

    rows: list[tuple[str, Style]] = []
    dim = Style(dim=True)
    grouper = DateGrouper()

    for i, tick in enumerate(ticks):
        ts = _parse_ts(tick["ts"])
        if ts is None:
            continue
        since = _parse_ts(tick["since"]) if tick.get("since") else None

        rows.extend(grouper.header_rows(ts))

        time_str = clock(ts)
        boundary = tick.get("boundary", {})
        kind_counts = tick.get("kind_counts", {})

        # Boundary trigger label: observer/status from _boundary payload
        trigger = ""
        if boundary:
            bname = boundary.get("name", "")
            bstatus = boundary.get("status", "")
            if bname and bstatus:
                trigger = f"{bname} {bstatus}"
            elif bname:
                trigger = bname

        kinds_summary = ", ".join(f"{c} {k}" for k, c in kind_counts.items() if c > 0)

        # Duration
        duration = ""
        if since is not None:
            duration = _format_duration(since, ts)

        # Index for drill-down reference
        idx_label = f"#{i}"

        # Rail gutter (G4): a tick is a tree-cut container — its tier is the MAX
        # over the keys its window touched (fetch_ticks → tier_max). TTY renders
        # the glyph gutter; the piped ledger carries the tier as a WORD.
        tier = tick.get("tier", "")
        if is_piped:
            gutter = f"{tier or 'untiered':<8}  "
            row_style = Style()
        else:
            gutter = f"{rail_glyph(tier)} "
            row_style = Style(bold=True) if tier == "high" else Style()

        body = f"{time_str} {idx_label} {trigger}" if trigger \
            else f"{time_str} {idx_label} {tick['name']}"
        if duration:
            body += f" ({duration})"

        rows.append((f"{gutter}{body}", row_style))

        if zoom >= Zoom.DETAILED and kinds_summary:
            rows.append((f"           fold: {kinds_summary}", dim))

        if zoom >= Zoom.FULL:
            if since is not None:
                rows.append((f"           window: {tick['since']} → {tick['ts']}", dim))
            rows.append((f"           origin: {tick.get('origin', '')}", dim))

    # Footer with drill-down hint
    rows.append(("", Style()))
    rows.append(("Drill down: loops read <vertex> --ticks <#>", dim))

    return Block.column(rows, width=width)
