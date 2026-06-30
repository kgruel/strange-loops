"""Shared stat-over-containment rendering — the rich TTY register for ``sl ls``.

The ``ls`` verb is ``stat`` over the containment tree (vertex ⊃ kind ⊃ key);
every level lists its entries with the same stat columns. This module is the
*human/TTY register* of that listing: a rounded header **card** (the entry's own
stat summary) over a clean columnar **table** (no vertical dividers) whose cells
carry a share meter, a per-entry density **sparkline**, kind colour, and a
freshness-graded "updated" column.

The pipe/agent register is deliberately NOT here — piped output stays terse
aligned text, monochrome, with no visual-only columns (bar/sparkline). Lenses
branch on ``piped`` and only reach for this module on the TTY path. Colour is
auto-stripped at the writer when ``not isatty`` regardless, but the *structural*
divergence (card/table vs plain rows) is the lens's call, keyed on ``piped`` —
never on ``width`` (decision:design/presentation-register-keys-on-channel).
"""
from __future__ import annotations

from datetime import datetime, timezone

from painted import (
    Block,
    BorderChars,
    Line,
    ROUNDED,
    Span,
    Style,
    Wrap,
    border,
    join_vertical,
)
from painted.views import Column, Overflow, TableState, table

from ..palette import DEFAULT_PALETTE, LoopsPalette
from .store import _ensure_utc, _relative_time

# Column gap is two spaces; the header rule fills the gap with ─ so it reads as
# one continuous line. Corners are unused by table() (it only consumes
# horizontal / vertical / crossing).
_CLEAN_BORDERS = BorderChars(
    top_left=" ", top_right=" ", bottom_left=" ", bottom_right=" ",
    horizontal="─", vertical="  ", crossing="─",
)

_SPARK = "▁▂▃▄▅▆▇█"
_BAR_FULL = "█"
_BAR_EMPTY = "░"


# ---------------------------------------------------------------------------
# Visual-quantity primitives — strings, so they slot into table Line cells
# ---------------------------------------------------------------------------


def spark(values: list[int]) -> str:
    """8-level density sparkline over ``values`` (oldest→newest).

    Per-series normalized to its own max, so the glyph shows *shape* (recent
    momentum), not absolute volume. A bucket with zero activity renders as a
    dim baseline ``·`` so gaps stay visible; an all-zero series (a kind dormant
    in the window) reads as a flat ``·`` row — the honest "no recent activity"
    signal.
    """
    if not values:
        return ""
    hi = max(values)
    if hi <= 0:
        return "·" * len(values)
    out = []
    for v in values:
        if v <= 0:
            out.append("·")
        else:
            out.append(_SPARK[min(7, int((v / hi) * 7 + 0.999))])
    return "".join(out)


def share_bar(pct: float, max_pct: float, width: int = 7) -> str:
    """A ranked share meter — ``pct`` scaled against the listing's ``max_pct``.

    Scaling to the leading entry (not absolute 0–100%) makes the bar a relative
    rank cue; the exact ``%`` rides alongside it as the precise number.
    """
    if max_pct <= 0:
        return _BAR_EMPTY * width
    filled = round(pct / max_pct * width)
    filled = max(0, min(width, filled))
    return _BAR_FULL * filled + _BAR_EMPTY * (width - filled)


def freshness_style(p: LoopsPalette, dt: datetime | None) -> Style:
    """Style for an "updated" cell, graded by how long ago (revives the
    tested-but-unused :meth:`LoopsPalette.freshness_style`). The freshest row
    glows — the resumption orient, "where did I leave off", made visible."""
    if dt is None:
        return p.metadata
    secs = (datetime.now(timezone.utc) - _ensure_utc(dt)).total_seconds()
    return p.freshness_style(secs)


def updated_text(dt: datetime | None) -> str:
    return _relative_time(dt) if isinstance(dt, datetime) else "—"


# ---------------------------------------------------------------------------
# Cell + table + card construction
# ---------------------------------------------------------------------------


def cell(text: str, style: Style | None = None) -> Line:
    """A single-span table cell."""
    return Line((Span(str(text), style or Style()),))


def meter_cell(
    value: float, max_value: float, label: str, p: LoopsPalette, *, width: int = 7
) -> Line:
    """A ranked meter cell — filled bar (accent) + remainder (dim) + ``label``.

    ``value`` is scaled against ``max_value`` (the listing's leading row) so the
    bar reads as a rank cue; ``label`` is the precise number shown alongside.
    """
    bar = share_bar(value, max_value, width)
    filled = bar.count(_BAR_FULL)
    return Line((
        Span(_BAR_FULL * filled, Style(fg="cyan")),
        Span(_BAR_EMPTY * (width - filled), p.chrome),
        Span(f" {label}", p.metadata),
    ))


def stat_table(
    columns: list[Column],
    rows: list[list[Line]],
    width: int | None,
    *,
    p: LoopsPalette,
) -> Block:
    """Clean columnar table — header + continuous rule + rows, no ``│`` dividers.

    Per-cell colour survives (the table only sets the row's *default* style;
    each cell's spans keep their own). Numeric columns right-align via
    ``Align.END`` on the ``Column``.
    """
    if not rows:
        return Block.empty(width or 1, 0)
    return table(
        TableState(),
        columns,
        rows,
        visible_height=len(rows),
        width=width,
        overflow=Overflow.FIT,
        header_style=p.section,
        separator_style=p.chrome,
        # A static listing has no cursor — suppress the TUI selection highlight
        # (table() reverse-videos row 0 by default; an empty style is a no-op).
        selected_style=Style(),
        borders=_CLEAN_BORDERS,
    )


def card(title: str, sublines: list[str], width: int, *, p: LoopsPalette) -> Block:
    """Rounded header card — ``title`` in the top edge, stat ``sublines`` inside.

    Body lines carry a one-space interior margin so they don't kiss the border.
    """
    inner_w = max(1, width - 2)
    # Ellipsize (not hard-clip) so a stat line that won't fit a narrow card
    # signals the loss with a marker instead of silently dropping a number.
    body = [
        Block.text(f" {s}", p.metadata, width=inner_w, wrap=Wrap.ELLIPSIS)
        for s in sublines if s
    ]
    inner = join_vertical(*body) if body else Block.empty(inner_w, 1)
    return border(inner, ROUNDED, p.chrome, title=title, title_style=p.header)


def card_width(
    body: Block, title: str, sublines: list[str], width: int | None
) -> int:
    """Width for a header card that fits both its sublines and the table below
    it — so a short table never clips a longer stat line. Capped at ``width``."""
    needed = max(
        [body.width or 0, len(title) + 4, *(len(s) + 3 for s in sublines)]
    )
    return min(needed, width) if width else needed


def palette_of(palette: LoopsPalette | None) -> LoopsPalette:
    return palette or DEFAULT_PALETTE
