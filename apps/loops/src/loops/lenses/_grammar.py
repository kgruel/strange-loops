"""The shared static-grammar vocabulary (spine G0).

One time vocabulary, one width-honoring block helper, one date-group
pattern, one tick-drill header. Lenses import these instead of
hand-rolling — the four-way timestamp fork (fold/stream/ticks/store/ls)
dissolves here.

Vocabulary contract (decision:design/spine-options-ratified):
- ``recency``    compact relative with calendar cutover — ``now``, ``5m``,
                 ``2h``, ``3d``, ``2w``, then ``Feb 27``. The one "how
                 stale" form, used by fold badges, ls updated-cells, and
                 store rollups alike.
- ``clock``      ``HH:MM`` — "when exactly", under a date-group header.
- ``date_key``   ``YYYY-MM-DD`` — the date-group header text.
- ``short_date`` ``Feb 27`` — calendar form on its own.
- ``stamp``      ``YYYY-MM-DD HH:MM`` — greppable absolute (piped/agent).
- ``full_iso``   ISO seconds — FULL zoom and the piped ledger's ISO column.
- ``duration``   ``45s`` / ``5m`` / ``2h30m`` / ``3d`` — window spans.

All accept the timestamp shapes that circulate in fetch dicts (ISO
string, datetime, epoch int/float); naive datetimes are assumed UTC.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from painted import Block, Style

# ---------------------------------------------------------------------------
# Timestamp coercion
# ---------------------------------------------------------------------------


def ensure_utc(dt: datetime) -> datetime:
    """Normalize to UTC — naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def coerce_dt(ts: object) -> datetime | None:
    """Best-effort timestamp coercion: ISO str / datetime / epoch → aware UTC.

    Returns None for unparseable input — callers render their own
    placeholder ("?", "—", "") since the right one is contextual.
    """
    if isinstance(ts, datetime):
        return ensure_utc(ts)
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        try:
            return ensure_utc(datetime.fromisoformat(ts))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# The time vocabulary
# ---------------------------------------------------------------------------


def recency(ts: object) -> str:
    """Compact "how stale" tag: now / 5m / 2h / 3d / 2w, then ``Feb 27``.

    The calendar cutover keeps old items addressable and greppable
    instead of drifting into ``847d``-style noise.
    """
    dt = coerce_dt(ts)
    if dt is None:
        return ""
    age = time.time() - dt.timestamp()
    if age < 60:
        return "now"
    if age < 3600:
        return f"{int(age / 60)}m"
    if age < 86400:
        return f"{int(age / 3600)}h"
    if age < 604800:
        return f"{int(age / 86400)}d"
    if age < 2592000:
        return f"{int(age / 604800)}w"
    return short_date(dt)


def clock(ts: object) -> str:
    """``HH:MM`` — the within-day form, under a date-group header."""
    dt = coerce_dt(ts)
    return dt.strftime("%H:%M") if dt else "?"


def date_key(ts: object) -> str:
    """``YYYY-MM-DD`` — the date-group header text (and grouping key)."""
    dt = coerce_dt(ts)
    return dt.strftime("%Y-%m-%d") if dt else "?"


def short_date(ts: object) -> str:
    """``Feb 27`` — the calendar form on its own."""
    dt = coerce_dt(ts)
    if dt is None:
        if isinstance(ts, str):
            return ts[:10] if len(ts) >= 10 else ts
        return "?"
    return f"{dt.strftime('%b')} {dt.day}"


def stamp(ts: object) -> str:
    """``YYYY-MM-DD HH:MM`` (UTC) — greppable, stable, channel-safe."""
    dt = coerce_dt(ts)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "?"


def full_iso(ts: object) -> str:
    """ISO-seconds timestamp — FULL zoom and the piped ISO column."""
    if isinstance(ts, str):
        return ts
    dt = coerce_dt(ts)
    return dt.isoformat(timespec="seconds") if dt else "?"


def duration(start: datetime, end: datetime) -> str:
    """Human-readable span between two datetimes: 45s / 5m / 2h30m / 3d."""
    secs = int((ensure_utc(end) - ensure_utc(start)).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        hours = secs // 3600
        mins = (secs % 3600) // 60
        return f"{hours}h{mins}m" if mins else f"{hours}h"
    days = secs // 86400
    hours = (secs % 86400) // 3600
    return f"{days}d{hours}h" if hours else f"{days}d"


# ---------------------------------------------------------------------------
# The rail (salience gutter)
# ---------------------------------------------------------------------------

# Tier → gutter glyph. The leftmost column means the same thing from ls down
# to a single fact (decision:design/rail-wins-gutter). Tier values are
# materialized on Surface rows (surface._assign_tiers — quantile buckets,
# vertex-scoped, view-invariant); "stale" is the ⊘ status overlay, stampable
# over any tier once the lifecycle declaration lands.
TIER_GLYPHS: dict[str, str] = {
    "high": "◆",
    "mid": "│",
    "tail": "·",
    "stale": "⊘",
    "": " ",  # UNTIERED — an event with no matching folded entity (collect id
    # aged out, unfolded kind). Honest absence: a blank gutter, never an
    # invented tier glyph (decision:design/tier-one-home-inheritance).
}

RAIL_LEGEND = "rail  ◆ high  │ mid  · tail  ⊘ stale"


def rail_glyph(tier: str) -> str:
    """Gutter glyph for a tier — unknown tiers render the mid rail."""
    return TIER_GLYPHS.get(tier, TIER_GLYPHS["mid"])


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def block(text: str, style: Style, width: int | None) -> Block:
    """Block.text honoring the piped contract — width=None → natural size."""
    if width is None:
        return Block.text(text, style)
    return Block.text(text, style, width=width)


class DateGrouper:
    """The date-group header pattern shared by stream and ticks.

    Call :meth:`header_rows` per item, in timestamp order; it returns the
    rows to emit *before* the item — a blank separator + ``YYYY-MM-DD:``
    header when the date changes, nothing otherwise.
    """

    def __init__(self) -> None:
        self._current: str | None = None

    def header_rows(self, ts: object) -> list[tuple[str, Style]]:
        key = date_key(ts)
        if key == self._current:
            return []
        rows: list[tuple[str, Style]] = []
        if self._current is not None:
            rows.append(("", Style()))
        rows.append((f"{key}:", Style(bold=True)))
        self._current = key
        return rows


# ---------------------------------------------------------------------------
# Tick envelope rendering (shared by stream drill + read --ticks drill)
# ---------------------------------------------------------------------------


def attest_line(envelope: dict | None) -> str:
    """Render a tick's witness-era envelope as one header line.

    The envelope is the attestation metadata added at append time
    (chain link, signature, fact cursor) — see StoreReader.ticks_between.
    Absent envelope (not read, or range mode) renders nothing. An
    unchained envelope renders explicitly — pre-chain tick or aggregate
    read, neither of which attests.
    """
    if envelope is None:
        return ""
    if not envelope.get("chained"):
        return "  attest: none (no chain envelope)"
    parts = ["chained", "signed" if envelope.get("signed") else "unsigned"]
    line = f"  attest: {' · '.join(parts)}"
    kind = envelope.get("cursor_kind", "")
    if kind:
        preview = envelope.get("cursor_preview", "")
        target = f'{kind}: "{preview}"' if preview else kind
        line += f" · cursor → {target}"
    return line


def tick_drill_rows(tick_meta: dict) -> list[tuple[str, Style]]:
    """Header rows for a tick drill-down: title, window, attest line.

    Returns (text, style) rows without a trailing blank — callers
    compose their own tail (fact count, spacing).
    """
    if not tick_meta:
        return []

    boundary = tick_meta.get("boundary", {})
    bname = boundary.get("name", "")
    bstatus = boundary.get("status", "")
    trigger = f" — {bname} {bstatus}" if bname else ""

    range_end = tick_meta.get("range_end")
    if range_end is not None:
        range_boundaries = tick_meta.get("range_boundaries", [])
        observers = list(dict.fromkeys(
            b.get("name", "") for b in range_boundaries if b.get("name")
        ))
        if observers:
            trigger = f" — {', '.join(observers)}"
        title = f"Ticks #{tick_meta['index']}:{range_end} of {tick_meta['total']}{trigger}"
    else:
        title = f"Tick #{tick_meta['index']} of {tick_meta['total']}{trigger}"

    rows: list[tuple[str, Style]] = [(title, Style(bold=True))]
    if tick_meta.get("since") and tick_meta.get("ts"):
        rows.append(
            (f"  window: {tick_meta['since']} → {tick_meta['ts']}", Style(dim=True))
        )
    attest = attest_line(tick_meta.get("envelope"))
    if attest:
        rows.append((attest, Style(dim=True)))
    return rows
