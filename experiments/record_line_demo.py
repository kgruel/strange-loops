#!/usr/bin/env python3
"""Record line rendering demo — design exploration for painted.

Explores how timestamped records (facts, ticks, log entries, events) should
render in the terminal with color, zoom levels, and width adaptation.

Research findings (see PLAN.md for full detail):
  - Color encodes ONE dimension: severity OR source, never both
  - INFO is baseline (unstyled); color marks deviation (journalctl principle)
  - Fixed-width metadata columns + variable message = scannable (Docker Compose)
  - Colored left gutter is minimal-footprint severity indicator (Grafana/Datadog)
  - Multi-line: continuation indentation > prefix repetition
  - Width-aware truncation is a gap in most terminal tools

Run: uv run python experiments/record_line_demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from typing import Callable

# Add libs to path for direct execution
sys.path.insert(0, "libs/painted/src")

from painted import (
    Block,
    Style,
    Zoom,
    print_block,
    current_palette,
    use_palette,
    NORD_PALETTE,
    MONO_PALETTE,
    DEFAULT_PALETTE,
)
from painted.compose import join_horizontal, join_vertical, pad


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

PayloadLens = Callable[[str, dict, Zoom], str | Block]


# ---------------------------------------------------------------------------
# Kind → color mapping
# ---------------------------------------------------------------------------

def _kind_style(kind: str) -> Style:
    """Map a record kind to a palette style.

    Semantic mapping, not arbitrary. Follows the journalctl principle:
    most things are unstyled, color marks deviation.
    """
    p = current_palette()
    _map = {
        # Attention: errors and warnings
        "error": p.error,
        "alert": p.error,
        "critical": p.error,
        "warning": p.warning,
        "warn": p.warning,
        # Progress: things that happened
        "change": p.success,
        "deploy": p.success,
        "success": p.success,
        "completed": p.success,
        # Interest: things to notice
        "decision": p.accent,
        "thread": p.accent,
        "task": p.accent,
        "exchange": p.accent,
        "tick": p.accent,
    }
    return _map.get(kind, Style())  # unstyled baseline


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------

def _fmt_ts(ts: datetime, zoom: Zoom) -> str:
    """Format timestamp based on zoom level."""
    if zoom <= Zoom.MINIMAL:
        return ""
    if zoom <= Zoom.SUMMARY:
        return ts.strftime("%H:%M")
    if zoom <= Zoom.DETAILED:
        return ts.strftime("%H:%M")
    # FULL
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_width(zoom: Zoom) -> int:
    """Fixed width allocated to timestamp column."""
    if zoom <= Zoom.MINIMAL:
        return 0
    if zoom <= Zoom.DETAILED:
        return 6  # "14:23 "
    return 21  # "2025-01-15T14:23:00Z "


# ---------------------------------------------------------------------------
# Default payload rendering
# ---------------------------------------------------------------------------

# Keys to try for a one-line summary, in priority order
_SUMMARY_KEYS = ("topic", "message", "name", "title", "summary", "description", "text")


def _default_payload_summary(kind: str, payload: dict) -> str:
    """Extract a one-line summary from payload using well-known keys."""
    parts: list[str] = []

    # Kind-specific patterns
    if kind == "decision":
        topic = payload.get("topic", "")
        msg = payload.get("message", "")
        if topic and msg:
            return f"{topic}: {msg}"
        return topic or msg

    if kind in ("thread", "task"):
        name = payload.get("name", "")
        status = payload.get("status", "")
        summary = payload.get("summary", "")
        if name:
            parts.append(name)
        if status:
            parts.append(f"[{status}]")
        if summary:
            parts.append(summary)
        return " ".join(parts)

    if kind == "exchange":
        prompt = payload.get("prompt", "")
        response = payload.get("response", "")
        if prompt:
            return f"→ {prompt}" + (f" ← {response}" if response else "")

    if kind == "tick":
        name = payload.get("name", "")
        status = payload.get("status", "")
        fold = payload.get("fold", "")
        parts = [p for p in [name, status, fold] if p]
        return " ".join(parts)

    # Generic: try well-known keys
    for key in _SUMMARY_KEYS:
        if key in payload and payload[key]:
            return str(payload[key])

    # Fallback: k=v
    return " ".join(f"{k}={v}" for k, v in payload.items() if v)


def _default_payload_full(payload: dict) -> list[str]:
    """All payload fields as individual lines."""
    return [f"{k}: {v}" for k, v in payload.items() if v is not None and v != ""]


# ---------------------------------------------------------------------------
# record_line — the core primitive
# ---------------------------------------------------------------------------

def record_line(
    ts: datetime,
    kind: str,
    payload: dict,
    zoom: Zoom,
    width: int,
    *,
    payload_lens: PayloadLens | None = None,
) -> Block:
    """Render a single timestamped record as a Block.

    Zoom behavior:
      MINIMAL  — one-line gist, no timestamp, no label
      SUMMARY  — HH:MM [kind] one-line summary
      DETAILED — HH:MM [kind] summary + continuation lines for secondary fields
      FULL     — ISO timestamp [kind] all fields on individual lines
    """
    p = current_palette()

    # --- MINIMAL: just the gist ---
    if zoom <= Zoom.MINIMAL:
        summary = _default_payload_summary(kind, payload)
        if payload_lens:
            result = payload_lens(kind, payload, zoom)
            summary = result if isinstance(result, str) else summary
        text = summary[:width] if len(summary) > width else summary
        return Block.text(text, Style(), width=width)

    # --- Build structured line ---

    # Timestamp
    ts_str = _fmt_ts(ts, zoom)
    ts_w = _ts_width(zoom)

    # Label
    label_text = kind
    kind_s = _kind_style(kind)

    # Content from lens or default
    if payload_lens:
        content = payload_lens(kind, payload, zoom)
    else:
        content = _default_payload_summary(kind, payload)

    # Calculate content width
    meta_width = ts_w + len(label_text) + 3  # 3 = "[] " around label + space after
    content_width = max(width - meta_width, 10)

    # --- SUMMARY: single line ---
    if zoom <= Zoom.SUMMARY:
        if isinstance(content, Block):
            content_str = ""  # Block content handled separately
        else:
            content_str = str(content)

        # Build segments with join_horizontal
        segments: list[Block] = []

        if ts_w > 0:
            ts_block = Block.text(f"{ts_str:<{ts_w}}", p.muted)
            segments.append(ts_block)

        # Label: [kind]
        bracket_l = Block.text("[", p.muted)
        label_block = Block.text(label_text, kind_s)
        bracket_r = Block.text("] ", p.muted)
        segments.extend([bracket_l, label_block, bracket_r])

        # Content (truncated to fit)
        if isinstance(content, Block):
            segments.append(content)
        else:
            if len(content_str) > content_width:
                content_str = content_str[: content_width - 1] + "…"
            segments.append(Block.text(content_str, Style()))

        return join_horizontal(*segments)

    # --- DETAILED: summary + secondary fields on continuation lines ---
    if zoom <= Zoom.DETAILED:
        if isinstance(content, str):
            primary = content
        else:
            primary = _default_payload_summary(kind, payload)

        # Primary line
        segments = []
        if ts_w > 0:
            segments.append(Block.text(f"{ts_str:<{ts_w}}", p.muted))

        segments.append(Block.text("[", p.muted))
        segments.append(Block.text(label_text, kind_s))
        segments.append(Block.text("] ", p.muted))

        if len(primary) > content_width:
            primary = primary[: content_width - 1] + "…"
        segments.append(Block.text(primary, Style()))

        primary_line = join_horizontal(*segments)
        lines: list[Block] = [primary_line]

        # Secondary fields: long values or specific keys
        indent = " " * (ts_w + len(label_text) + 3)
        for k, v in payload.items():
            if v is None or v == "":
                continue
            sv = str(v)
            if k in ("description", "message", "body", "response", "output") or len(sv) > 40:
                field_text = f"{indent}{k}: {sv}"
                if len(field_text) > width:
                    field_text = field_text[: width - 1] + "…"
                lines.append(Block.text(field_text, p.muted))

        return join_vertical(*lines)

    # --- FULL: ISO timestamp + every field on own line ---
    segments = []
    if ts_w > 0:
        segments.append(Block.text(f"{ts_str:<{ts_w}}", p.muted))
    segments.append(Block.text("[", p.muted))
    segments.append(Block.text(label_text, kind_s))
    segments.append(Block.text("]", p.muted))

    header_line = join_horizontal(*segments)
    lines = [header_line]

    indent = " " * (ts_w + len(label_text) + 3)
    for k, v in payload.items():
        if v is None or v == "":
            continue
        field_text = f"{indent}{k}: {v}"
        if len(field_text) > width:
            field_text = field_text[: width - 1] + "…"
        lines.append(Block.text(field_text, p.muted))

    return join_vertical(*lines)


# ---------------------------------------------------------------------------
# record_timeline — composition
# ---------------------------------------------------------------------------

def record_timeline(
    records: list[tuple[datetime, str, dict]],
    zoom: Zoom,
    width: int,
    *,
    payload_lens: PayloadLens | None = None,
) -> Block:
    """Render a chronological timeline of records, grouped by date.

    Zoom behavior:
      MINIMAL  — kind count summary
      SUMMARY+ — date-grouped record lines
    """
    if not records:
        return Block.text("(no records)", current_palette().muted)

    # --- MINIMAL: counts ---
    if zoom <= Zoom.MINIMAL:
        from collections import Counter

        counts = Counter(kind for _, kind, _ in records)
        parts = [f"{n} {k}" for k, n in counts.most_common()]
        return Block.text(", ".join(parts), Style(), width=width)

    # --- Group by date ---
    p = current_palette()
    groups: dict[str, list[tuple[datetime, str, dict]]] = {}
    for ts, kind, payload in records:
        date_key = ts.strftime("%Y-%m-%d")
        groups.setdefault(date_key, []).append((ts, kind, payload))

    all_blocks: list[Block] = []
    for date_key, group_records in groups.items():
        # Date header
        header = Block.text(f"{date_key}:", p.muted.merge(Style(bold=True)))
        all_blocks.append(header)

        # Record lines, indented
        for ts, kind, payload in group_records:
            line = record_line(ts, kind, payload, zoom, width - 2, payload_lens=payload_lens)
            indented = pad(line, left=2)
            all_blocks.append(indented)

    return join_vertical(*all_blocks, gap=0)


# ---------------------------------------------------------------------------
# Section rendering helpers
# ---------------------------------------------------------------------------

def _section(title: str, width: int = 80) -> None:
    """Print a section header."""
    p = current_palette()
    bar = "─" * width
    print()
    print_block(Block.text(bar, p.muted), use_ansi=True)
    print_block(Block.text(f"  {title}", Style(bold=True)), use_ansi=True)
    print_block(Block.text(bar, p.muted), use_ansi=True)


def _subsection(title: str) -> None:
    """Print a subsection label."""
    p = current_palette()
    print()
    print_block(Block.text(f"  ▸ {title}", p.accent), use_ansi=True)
    print()


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_BASE = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def _ts(hours: float = 0, days: int = 0) -> datetime:
    return _BASE + timedelta(hours=hours, days=days)


SAMPLE_RECORDS: list[tuple[datetime, str, dict]] = [
    (_ts(0), "decision", {
        "topic": "Use SQLite for persistence",
        "message": "Chose SQLite over filesystem for atomic writes and query support",
    }),
    (_ts(0.5), "thread", {
        "name": "vertex-routing",
        "status": "active",
        "summary": "Design slashed name resolution for vertex discovery",
    }),
    (_ts(1), "exchange", {
        "observer": "claude",
        "prompt": "How should vertex templates handle config registration?",
        "response": "Templates create local instance + register with config-level aggregator. Two kinds: instance (has store) vs aggregation (has discover).",
    }),
    (_ts(1.5), "tick", {
        "name": "fold-projection",
        "status": "running",
        "fold": "3 facts collected, 1 pending",
    }),
    (_ts(2, days=0), "change", {
        "summary": "Added boundary detection to spec validation",
        "files": "libs/atoms/src/atoms/spec.py",
    }),
    (_ts(3, days=0), "task", {
        "name": "implement-fold",
        "status": "in-progress",
        "summary": "Wire up Spec.apply to projection fold loop",
    }),
    # Next day
    (_ts(0, days=1), "deploy", {
        "service": "loops-api",
        "version": "0.4.2",
        "status": "healthy",
        "environment": "production",
    }),
    (_ts(0.5, days=1), "decision", {
        "topic": "KDL for config format",
        "message": "KDL is human-friendly and supports nested structure natively",
    }),
    (_ts(1, days=1), "error", {
        "message": "Connection refused on port 5432",
        "service": "loops-api",
        "severity": "error",
    }),
    # Blog/journal entry
    (_ts(2, days=1), "journal", {
        "title": "Dissolving transport into store operations",
        "body": "Transport was a separate concern that dissolved into store.merge() and store.slice(). The key insight: transport is just store operations across a boundary.",
    }),
    # Git commit
    (_ts(3, days=1), "commit", {
        "hash": "4e85bbe",
        "author": "kaygee",
        "message": "Fix handoff fold: collect 1 instead of latest",
        "files_changed": 3,
    }),
    (_ts(4, days=1), "warning", {
        "message": "Disk usage at 87% on /data volume",
        "threshold": "85%",
        "service": "monitoring",
    }),
]


# ---------------------------------------------------------------------------
# Domain-specific payload lenses
# ---------------------------------------------------------------------------

def loops_lens(kind: str, payload: dict, zoom: Zoom) -> str | Block:
    """Loops-aware payload lens — knows about facts, ticks, decisions."""
    if kind == "decision":
        topic = payload.get("topic", "")
        msg = payload.get("message", "")
        if zoom <= Zoom.SUMMARY:
            return f"{topic}: {msg}" if msg else topic
        return topic  # detailed/full show message as continuation

    if kind == "tick":
        name = payload.get("name", "")
        status = payload.get("status", "")
        fold = payload.get("fold", "")
        p = current_palette()
        # Tick gets the ⚡ marker
        parts: list[Block] = [Block.text("⚡ ", p.warning)]
        parts.append(Block.text(name + " ", Style()))
        if status:
            status_style = {
                "running": p.accent,
                "completed": p.success,
                "errored": p.error,
            }.get(status, Style())
            parts.append(Block.text(status, status_style))
        if fold and zoom >= Zoom.SUMMARY:
            parts.append(Block.text(f"  {fold}", p.muted))
        return join_horizontal(*parts)

    if kind == "exchange":
        prompt = payload.get("prompt", "")
        if zoom <= Zoom.SUMMARY:
            return f"→ {prompt}"
        return f"→ {prompt}"

    if kind == "commit":
        h = payload.get("hash", "")[:7]
        author = payload.get("author", "")
        msg = payload.get("message", "")
        p = current_palette()
        parts = [
            Block.text(h + " ", p.accent),
            Block.text(f"({author}) ", p.muted),
            Block.text(msg, Style()),
        ]
        return join_horizontal(*parts)

    # Fall through to default
    return _default_payload_summary(kind, payload)


# ---------------------------------------------------------------------------
# Demo sections
# ---------------------------------------------------------------------------

def demo_zoom_levels(width: int = 80) -> None:
    """Section 2: Same record at all 4 zoom levels."""
    _section("Record at All Zoom Levels", width)

    ts = _ts(0)
    kind = "decision"
    payload = {
        "topic": "Use SQLite for persistence",
        "message": "Chose SQLite over filesystem for atomic writes and query support",
    }

    for z in Zoom:
        _subsection(f"Zoom.{z.name}")
        block = record_line(ts, kind, payload, z, width)
        print_block(block, use_ansi=True)


def demo_default_vs_lens(width: int = 80) -> None:
    """Section 3: Default rendering vs domain payload lens."""
    _section("Default Payload vs Domain Lens", width)

    # Tick record — most visually different with a lens
    ts = _ts(1.5)
    kind = "tick"
    payload = {"name": "fold-projection", "status": "running", "fold": "3 facts collected, 1 pending"}

    _subsection("Default rendering")
    block = record_line(ts, kind, payload, Zoom.SUMMARY, width)
    print_block(block, use_ansi=True)

    _subsection("With loops_lens")
    block = record_line(ts, kind, payload, Zoom.SUMMARY, width, payload_lens=loops_lens)
    print_block(block, use_ansi=True)

    # Git commit
    ts2 = _ts(3, days=1)
    kind2 = "commit"
    payload2 = {"hash": "4e85bbe", "author": "kaygee", "message": "Fix handoff fold: collect 1 instead of latest", "files_changed": 3}

    _subsection("Commit — default")
    block = record_line(ts2, kind2, payload2, Zoom.SUMMARY, width)
    print_block(block, use_ansi=True)

    _subsection("Commit — with loops_lens")
    block = record_line(ts2, kind2, payload2, Zoom.SUMMARY, width, payload_lens=loops_lens)
    print_block(block, use_ansi=True)


def demo_width_degradation(width: int = 80) -> None:
    """Section 4: How width affects rendering."""
    _section("Width Degradation", width)

    ts = _ts(0)
    kind = "decision"
    payload = {
        "topic": "Use SQLite for persistence",
        "message": "Chose SQLite over filesystem for atomic writes and query support",
    }

    for w in [120, 80, 60, 40]:
        _subsection(f"width={w}")
        block = record_line(ts, kind, payload, Zoom.SUMMARY, w)
        print_block(block, use_ansi=True)


def demo_variety(width: int = 80) -> None:
    """Section 5: Different record types to prove generality."""
    _section("Variety of Record Types", width)

    _subsection("All types at SUMMARY zoom")
    for ts, kind, payload in SAMPLE_RECORDS:
        block = record_line(ts, kind, payload, Zoom.SUMMARY, width)
        print_block(block, use_ansi=True)

    _subsection("All types at SUMMARY zoom — with domain lens")
    for ts, kind, payload in SAMPLE_RECORDS:
        block = record_line(ts, kind, payload, Zoom.SUMMARY, width, payload_lens=loops_lens)
        print_block(block, use_ansi=True)


def demo_timeline(width: int = 80) -> None:
    """Section 6: Timeline composition with date grouping."""
    _section("Timeline Composition", width)

    for z in [Zoom.MINIMAL, Zoom.SUMMARY, Zoom.DETAILED]:
        _subsection(f"Timeline at Zoom.{z.name}")
        block = record_timeline(SAMPLE_RECORDS, z, width, payload_lens=loops_lens)
        print_block(block, use_ansi=True)


def demo_color_exploration(width: int = 80) -> None:
    """Section 7: Same timeline in three palettes."""
    _section("Color Exploration: Three Palettes", width)

    # Use a shorter slice for readability
    records = SAMPLE_RECORDS[:6]

    for name, palette in [("DEFAULT", DEFAULT_PALETTE), ("NORD", NORD_PALETTE), ("MONO", MONO_PALETTE)]:
        _subsection(f"Palette: {name}")
        with use_palette(palette):
            block = record_timeline(records, Zoom.SUMMARY, width, payload_lens=loops_lens)
            print_block(block, use_ansi=True)


# ---------------------------------------------------------------------------
# Gutter exploration — the Grafana/Datadog pattern (fixed)
# ---------------------------------------------------------------------------

def _gutter_char(kind: str) -> str:
    """Map kind to a gutter indicator character.

    Thicker for attention-level kinds, thin line for everything else.
    """
    return {
        "error": "█",
        "critical": "█",
        "warning": "▐",
    }.get(kind, "│")


def _record_line_unstyled_label(
    ts: datetime,
    kind: str,
    payload: dict,
    zoom: Zoom,
    width: int,
    *,
    payload_lens: PayloadLens | None = None,
) -> Block:
    """Record line with unstyled (muted) label — for gutter-only color mode."""
    p = current_palette()

    if zoom <= Zoom.MINIMAL:
        summary = _default_payload_summary(kind, payload)
        if payload_lens:
            result = payload_lens(kind, payload, zoom)
            summary = result if isinstance(result, str) else summary
        text = summary[:width] if len(summary) > width else summary
        return Block.text(text, Style(), width=width)

    ts_str = _fmt_ts(ts, zoom)
    ts_w = _ts_width(zoom)

    # Content from lens or default
    if payload_lens:
        content = payload_lens(kind, payload, zoom)
    else:
        content = _default_payload_summary(kind, payload)

    meta_width = ts_w + len(kind) + 3
    content_width = max(width - meta_width, 10)

    # Build line with MUTED label instead of kind-colored
    segments: list[Block] = []
    if ts_w > 0:
        segments.append(Block.text(f"{ts_str:<{ts_w}}", p.muted))

    segments.append(Block.text("[", p.muted))
    segments.append(Block.text(kind, p.muted))  # <-- muted, not kind-colored
    segments.append(Block.text("] ", p.muted))

    if isinstance(content, Block):
        segments.append(content)
    else:
        content_str = str(content)
        if len(content_str) > content_width:
            content_str = content_str[: content_width - 1] + "…"
        segments.append(Block.text(content_str, Style()))

    primary = join_horizontal(*segments)

    if zoom <= Zoom.SUMMARY:
        return primary

    # DETAILED/FULL continuation lines (same as record_line)
    lines: list[Block] = [primary]
    indent = " " * (ts_w + len(kind) + 3)
    if zoom <= Zoom.DETAILED:
        for k, v in payload.items():
            if v is None or v == "":
                continue
            sv = str(v)
            if k in ("description", "message", "body", "response", "output") or len(sv) > 40:
                field_text = f"{indent}{k}: {sv}"
                if len(field_text) > width:
                    field_text = field_text[: width - 1] + "…"
                lines.append(Block.text(field_text, p.muted))
    else:
        for k, v in payload.items():
            if v is None or v == "":
                continue
            field_text = f"{indent}{k}: {v}"
            if len(field_text) > width:
                field_text = field_text[: width - 1] + "…"
            lines.append(Block.text(field_text, p.muted))

    return join_vertical(*lines)


def _record_line_no_label(
    ts: datetime,
    kind: str,
    payload: dict,
    zoom: Zoom,
    width: int,
    *,
    payload_lens: PayloadLens | None = None,
) -> Block:
    """Record line with NO label — gutter is the sole kind indicator."""
    p = current_palette()

    if zoom <= Zoom.MINIMAL:
        summary = _default_payload_summary(kind, payload)
        if payload_lens:
            result = payload_lens(kind, payload, zoom)
            summary = result if isinstance(result, str) else summary
        text = summary[:width] if len(summary) > width else summary
        return Block.text(text, Style(), width=width)

    ts_str = _fmt_ts(ts, zoom)
    ts_w = _ts_width(zoom)

    if payload_lens:
        content = payload_lens(kind, payload, zoom)
    else:
        content = _default_payload_summary(kind, payload)

    content_width = max(width - ts_w, 10)

    segments: list[Block] = []
    if ts_w > 0:
        segments.append(Block.text(f"{ts_str:<{ts_w}}", p.muted))

    if isinstance(content, Block):
        segments.append(content)
    else:
        content_str = str(content)
        if len(content_str) > content_width:
            content_str = content_str[: content_width - 1] + "…"
        segments.append(Block.text(content_str, Style()))

    primary = join_horizontal(*segments)

    if zoom <= Zoom.SUMMARY:
        return primary

    lines: list[Block] = [primary]
    indent = " " * ts_w
    if zoom <= Zoom.DETAILED:
        for k, v in payload.items():
            if v is None or v == "":
                continue
            sv = str(v)
            if k in ("description", "message", "body", "response", "output") or len(sv) > 40:
                field_text = f"{indent}{k}: {sv}"
                if len(field_text) > width:
                    field_text = field_text[: width - 1] + "…"
                lines.append(Block.text(field_text, p.muted))
    else:
        for k, v in payload.items():
            if v is None or v == "":
                continue
            field_text = f"{indent}{k}: {v}"
            if len(field_text) > width:
                field_text = field_text[: width - 1] + "…"
            lines.append(Block.text(field_text, p.muted))

    return join_vertical(*lines)


def record_line_gutter(
    ts: datetime,
    kind: str,
    payload: dict,
    zoom: Zoom,
    width: int,
    *,
    payload_lens: PayloadLens | None = None,
    show_label: bool = True,
) -> Block:
    """Record line with colored left gutter.

    show_label=True: gutter + muted label (Grafana style)
    show_label=False: gutter only, no label text (maximum density)
    """
    kind_s = _kind_style(kind)
    gutter_ch = _gutter_char(kind)
    gutter = Block.text(f"{gutter_ch} ", kind_s)

    if show_label:
        inner = _record_line_unstyled_label(
            ts, kind, payload, zoom, width - 2, payload_lens=payload_lens,
        )
    else:
        inner = _record_line_no_label(
            ts, kind, payload, zoom, width - 2, payload_lens=payload_lens,
        )

    return join_horizontal(gutter, inner)


def demo_gutter_variant(width: int = 80) -> None:
    """Gutter-style rendering — three variants, all zoom levels."""
    _section("Gutter Variants (Grafana/Datadog Pattern)", width)

    records = SAMPLE_RECORDS[:6]

    # --- Variant 1: Standard (colored label, no gutter) ---
    _subsection("Variant A: Standard (colored label, no gutter)")
    for ts, kind, payload in records:
        block = record_line(ts, kind, payload, Zoom.SUMMARY, width, payload_lens=loops_lens)
        print_block(block, use_ansi=True)

    # --- Variant 2: Gutter-only (colored bar, unstyled label text) ---
    _subsection("Variant B: Gutter + unstyled label (the Grafana pattern)")
    for ts, kind, payload in records:
        block = record_line_gutter(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=loops_lens, show_label=True,
        )
        print_block(block, use_ansi=True)

    # --- Variant 3: No-label gutter (colored bar, label omitted) ---
    _subsection("Variant C: Gutter only, no label (maximum density)")
    for ts, kind, payload in records:
        block = record_line_gutter(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=loops_lens, show_label=False,
        )
        print_block(block, use_ansi=True)

    # --- All three through zoom levels ---
    _subsection("Variant B across all zoom levels")
    ts, kind, payload = SAMPLE_RECORDS[0]  # decision
    for z in Zoom:
        p = current_palette()
        label = Block.text(f"  {z.name:>8}: ", p.muted)
        line = record_line_gutter(
            ts, kind, payload, z, width - 12,
            payload_lens=loops_lens, show_label=True,
        )
        block = join_horizontal(label, line)
        print_block(block, use_ansi=True)

    print()
    ts, kind, payload = SAMPLE_RECORDS[4]  # change (green gutter)
    for z in Zoom:
        p = current_palette()
        label = Block.text(f"  {z.name:>8}: ", p.muted)
        line = record_line_gutter(
            ts, kind, payload, z, width - 12,
            payload_lens=loops_lens, show_label=True,
        )
        block = join_horizontal(label, line)
        print_block(block, use_ansi=True)

    print()
    ts, kind, payload = SAMPLE_RECORDS[8]  # error (red gutter)
    for z in Zoom:
        p = current_palette()
        label = Block.text(f"  {z.name:>8}: ", p.muted)
        line = record_line_gutter(
            ts, kind, payload, z, width - 12,
            payload_lens=loops_lens, show_label=True,
        )
        block = join_horizontal(label, line)
        print_block(block, use_ansi=True)

    _subsection("Variant C across all zoom levels")
    ts, kind, payload = SAMPLE_RECORDS[0]
    for z in Zoom:
        p = current_palette()
        label = Block.text(f"  {z.name:>8}: ", p.muted)
        line = record_line_gutter(
            ts, kind, payload, z, width - 12,
            payload_lens=loops_lens, show_label=False,
        )
        block = join_horizontal(label, line)
        print_block(block, use_ansi=True)


# ---------------------------------------------------------------------------
# Research philosophy — rendered as styled terminal output
# ---------------------------------------------------------------------------

def _bullet(text: str, style: Style = Style(), indent: int = 4) -> Block:
    """Render a bullet point."""
    prefix = " " * indent + "• "
    return join_horizontal(
        Block.text(prefix, current_palette().muted),
        Block.text(text, style),
    )


def _principle(number: int, title: str, body: str, width: int = 80) -> Block:
    """Render a numbered design principle."""
    p = current_palette()
    num_block = Block.text(f"  {number}. ", p.accent)
    title_block = Block.text(title, Style(bold=True))
    header = join_horizontal(num_block, title_block)

    body_indent = "     "
    body_text = body
    body_lines: list[str] = []
    max_body = width - len(body_indent)
    while body_text:
        if len(body_text) <= max_body:
            body_lines.append(body_text)
            break
        # Word-wrap
        cut = body_text[:max_body].rfind(" ")
        if cut <= 0:
            cut = max_body
        body_lines.append(body_text[:cut])
        body_text = body_text[cut:].lstrip()

    parts: list[Block] = [header]
    for line in body_lines:
        parts.append(Block.text(f"{body_indent}{line}", p.muted))

    return join_vertical(*parts)


def _table_row(cells: list[tuple[str, Style]], col_widths: list[int]) -> Block:
    """Render a table row with fixed column widths."""
    segments: list[Block] = []
    for (text, style), w in zip(cells, col_widths):
        truncated = text[:w] if len(text) > w else text
        padded = f"{truncated:<{w}}"
        segments.append(Block.text(padded, style))
    return join_horizontal(*segments)


def demo_research_philosophy(width: int = 80) -> None:
    """Rendered research findings — what we learned, presented attractively."""
    _section("Research: What We Learned", width)

    p = current_palette()

    # --- The 6 principles ---
    _subsection("Six Design Principles")

    principles = [
        (
            "Color encodes exactly one dimension",
            "Every tool picks one: severity (journalctl, Rich, Grafana) or source "
            "identity (Docker Compose, stern). None mix both. The eye tracks one "
            "color-meaning mapping at a time.",
        ),
        (
            "INFO is the baseline — color means deviation",
            "journalctl's insight: unstyled INFO, dim DEBUG, yellow WARNING, red "
            "ERROR. Color budget goes to deviations from normal. Rich breaks this "
            "by coloring INFO blue — adds noise to the most common level.",
        ),
        (
            "Prefix alignment creates scannable columns",
            "Docker Compose right-pads service names with a pipe gutter. Rich uses "
            "a fixed-width level column. The pattern: fixed metadata on the left, "
            "variable message on the right, separated by a visible gutter.",
        ),
        (
            "The severity gutter is underused in terminals",
            "Grafana/Datadog use a colored left-edge bar — minimal footprint, "
            "instantly scannable. Takes almost no horizontal space but conveys "
            "kind at a glance. Terminal tools almost never do this.",
        ),
        (
            "Multi-line is the hardest unsolved problem",
            "Docker Compose repeats the prefix per line (noisy). journalctl dumps "
            "raw. Only lnav detects continuation lines and pins the first line. "
            "Continuation indentation beats prefix repetition.",
        ),
        (
            "Width-aware rendering is a gap",
            "Most tools just wrap at terminal width. lnav has per-field max_width "
            "with '..' overflow. Rich enforces column wrapping. This is a real "
            "opportunity for painted to own.",
        ),
    ]
    for i, (title, body) in enumerate(principles, 1):
        block = _principle(i, title, body, width)
        print_block(block, use_ansi=True)
        if i < len(principles):
            print()

    # --- Severity color consensus ---
    _subsection("Severity Color Consensus Across Tools")

    # Render as colored example lines showing the same record at different severities
    ts = _ts(0)
    severity_examples = [
        ("critical", {"message": "Database corruption detected", "action": "failover initiated"}),
        ("error", {"message": "Connection refused on port 5432", "service": "loops-api"}),
        ("warning", {"message": "Disk usage at 87% on /data volume", "threshold": "85%"}),
        ("task", {"name": "implement-fold", "status": "in-progress", "summary": "Normal work"}),
        ("change", {"summary": "Added boundary detection", "files": "spec.py"}),
    ]
    labels = ["CRITICAL", "ERROR  ", "WARNING", "INFO   ", "SUCCESS"]
    for (kind, payload), label in zip(severity_examples, labels):
        role_block = Block.text(f"  {label}  ", _kind_style(kind).merge(Style(bold=True)))
        line = record_line(ts, kind, payload, Zoom.SUMMARY, width - 12, payload_lens=loops_lens)
        block = join_horizontal(role_block, line)
        print_block(block, use_ansi=True)

    print()
    print_block(_bullet(
        "Red for errors (universal). Yellow for warnings (near-universal).",
        p.muted, indent=2,
    ), use_ansi=True)
    print_block(_bullet(
        "Unstyled for info/normal (journalctl's best choice). Dim for debug.",
        p.muted, indent=2,
    ), use_ansi=True)
    print_block(_bullet(
        "Green for success/progress. Accent for items of interest.",
        p.muted, indent=2,
    ), use_ansi=True)

    # --- The multi-line problem, demonstrated ---
    _subsection("The Multi-Line Problem")

    exchange = SAMPLE_RECORDS[2]  # exchange with long response

    print_block(Block.text("  Approach A: Prefix repetition (Docker Compose style)", p.muted), use_ansi=True)
    ts_e, kind_e, payload_e = exchange
    for field in ["observer", "prompt", "response"]:
        v = payload_e.get(field, "")
        if v:
            line = record_line(ts_e, kind_e, {field: v}, Zoom.SUMMARY, width)
            print_block(line, use_ansi=True)

    print()
    print_block(Block.text("  Approach B: Continuation indentation (our approach)", p.muted), use_ansi=True)
    block = record_line(ts_e, kind_e, payload_e, Zoom.DETAILED, width)
    print_block(block, use_ansi=True)

    print()
    print_block(Block.text("  Approach C: Gutter with continuation", p.muted), use_ansi=True)
    block = record_line_gutter(ts_e, kind_e, payload_e, Zoom.DETAILED, width, payload_lens=loops_lens)
    print_block(block, use_ansi=True)


# ---------------------------------------------------------------------------
# Creative exploration: what would the loops way be?
# ---------------------------------------------------------------------------

def demo_loops_way(width: int = 80) -> None:
    """What makes loops record rendering different from a generic log viewer?"""
    _section("Creative Exploration: The Loops Way", width)

    p = current_palette()

    # === 1. Attention/information-gain rendering ===
    _subsection("Idea 1: Attention — not severity, but information-gain")

    print_block(Block.text(
        "  What if rendering reflected how much a record changes your understanding?",
        p.muted,
    ), use_ansi=True)
    print_block(Block.text(
        "  Severity says 'how bad'. Attention says 'how new'.",
        p.muted,
    ), use_ansi=True)
    print()

    # A decision that changes the project direction: HIGH attention
    # A routine tick: LOW attention
    # An error seen for the first time: HIGH attention
    # The same error for the 50th time: LOW attention (it's noise now)

    attention_records = [
        # (ts, kind, payload, attention_level, reason)
        (_ts(0), "decision", {
            "topic": "Dissolve transport layer",
            "message": "Transport is just store operations across a boundary",
        }, "high", "first decision on this topic"),
        (_ts(0.25), "tick", {
            "name": "fold-projection",
            "status": "running",
            "fold": "4 facts collected",
        }, "low", "routine heartbeat"),
        (_ts(0.5), "error", {
            "message": "Connection refused on port 5432",
            "service": "loops-api",
            "occurrences": 1,
        }, "high", "first occurrence"),
        (_ts(1), "error", {
            "message": "Connection refused on port 5432",
            "service": "loops-api",
            "occurrences": 47,
        }, "low", "47th occurrence — it's noise"),
        (_ts(1.5), "exchange", {
            "observer": "claude",
            "prompt": "Should vertex support nested discovery?",
            "response": "No — flat is better. Nesting dissolves into aggregation.",
        }, "high", "design insight"),
        (_ts(2), "change", {
            "summary": "Bumped version to 0.4.3",
            "files": "pyproject.toml",
        }, "low", "mechanical change"),
    ]

    for ts, kind, payload, attention, reason in attention_records:
        # High attention: full style. Low attention: muted.
        if attention == "high":
            line = record_line(ts, kind, payload, Zoom.SUMMARY, width - 4, payload_lens=loops_lens)
            marker = Block.text(" ◆  ", _kind_style(kind))
        else:
            # Dim the entire line for low-attention records
            summary = _default_payload_summary(kind, payload)
            if len(summary) > width - 12:
                summary = summary[: width - 13] + "…"
            ts_str = ts.strftime("%H:%M")
            line = Block.text(f"{ts_str} {kind}: {summary}", p.muted)
            marker = Block.text(" ·  ", p.muted)

        row = join_horizontal(marker, line)
        print_block(row, use_ansi=True)

    print()
    print_block(Block.text(
        "  ◆ = high information-gain (new topic, first error, design insight)",
        p.accent,
    ), use_ansi=True)
    print_block(Block.text(
        "  · = low information-gain (routine, repeated, mechanical)",
        p.muted,
    ), use_ansi=True)

    # === 2. Records that show their own history ===
    _subsection("Idea 2: Records with history — facts that evolved")

    print_block(Block.text(
        "  A thread isn't a point — it's a trajectory. Show the arc.",
        p.muted,
    ), use_ansi=True)
    print()

    # Thread evolution: exploring → active → resolved
    thread_states = [
        (_ts(0), "exploring", "What should vertex routing look like?"),
        (_ts(2), "active", "Slashed names: dev/project → home/dev/project/project.vertex"),
        (_ts(8), "decided", "resolve_vertex supports slashed names, registered with config"),
    ]

    # Render as a connected timeline showing the thread evolving
    thread_name = "vertex-routing"
    for i, (ts, status, note) in enumerate(thread_states):
        ts_str = ts.strftime("%H:%M")

        # Visual connector
        if i == 0:
            connector = "┌"
        elif i == len(thread_states) - 1:
            connector = "└"
        else:
            connector = "├"

        # Status gets progressively more styled as the thread matures
        if status == "exploring":
            status_s = p.muted
            connector_s = p.muted
        elif status == "active":
            status_s = p.accent
            connector_s = p.accent
        else:
            status_s = p.success
            connector_s = p.success

        segments = [
            Block.text(f"  {connector}─ ", connector_s),
            Block.text(f"{ts_str} ", p.muted),
            Block.text(f"{thread_name} ", Style()),
            Block.text(f"[{status}] ", status_s),
            Block.text(note, p.muted),
        ]
        total = join_horizontal(*segments)

        # Connector between entries
        if i < len(thread_states) - 1:
            pipe = Block.text("  │", connector_s)
            block = join_vertical(total, pipe)
            print_block(block, use_ansi=True)
        else:
            print_block(total, use_ansi=True)

    # === 3. Cross-references: records that spawned other records ===
    _subsection("Idea 3: Cross-references — a decision spawns a task spawns a commit")

    print_block(Block.text(
        "  Records don't exist in isolation. Show the causal chain.",
        p.muted,
    ), use_ansi=True)
    print()

    chain = [
        ("decision", "Use SQLite for persistence", None),
        ("task", "implement-fold: Wire up Spec.apply", "from decision above"),
        ("change", "Added fold loop to projection engine", "implements task"),
        ("commit", "4e85bbe Fix handoff fold: collect 1", "closes task"),
    ]

    for i, (kind, text, ref) in enumerate(chain):
        kind_s = _kind_style(kind)

        if i == 0:
            arrow = "    "
        else:
            arrow = " └→ "

        segments = [
            Block.text(arrow, p.muted),
            Block.text("[", p.muted),
            Block.text(kind, kind_s),
            Block.text("] ", p.muted),
            Block.text(text, Style()),
        ]
        if ref:
            segments.append(Block.text(f"  ({ref})", p.muted))

        block = join_horizontal(*segments)
        print_block(block, use_ansi=True)

    # === 4. Temporal density — burst vs sparse ===
    _subsection("Idea 4: Temporal density — when 10 things happen in 5 minutes")

    print_block(Block.text(
        "  Time gaps carry meaning. A burst of activity is different from a trickle.",
        p.muted,
    ), use_ansi=True)
    print()

    # Dense burst (deploy sequence)
    burst_records = [
        (_ts(0), "deploy", {"service": "loops-api", "version": "0.4.2", "status": "starting"}),
        (_ts(0.02), "tick", {"name": "health-check", "status": "waiting", "fold": "0/3 passed"}),
        (_ts(0.05), "tick", {"name": "health-check", "status": "running", "fold": "1/3 passed"}),
        (_ts(0.08), "tick", {"name": "health-check", "status": "running", "fold": "2/3 passed"}),
        (_ts(0.1), "tick", {"name": "health-check", "status": "completed", "fold": "3/3 passed"}),
        (_ts(0.12), "deploy", {"service": "loops-api", "version": "0.4.2", "status": "healthy"}),
        # --- 6 hour gap ---
        (_ts(6), "journal", {"title": "Reflecting on the fold abstraction", "body": "..."}),
        # --- 2 hour gap ---
        (_ts(8), "decision", {"topic": "Dissolve transport", "message": "It's just store ops across a boundary"}),
    ]

    prev_ts = None
    for ts, kind, payload in burst_records:
        # Show time gaps
        if prev_ts is not None:
            gap = (ts - prev_ts).total_seconds()
            if gap > 3600:  # > 1 hour
                hours = gap / 3600
                gap_text = f"  {'·' * 3} {hours:.0f}h later {'·' * 3}"
                print()
                print_block(Block.text(gap_text, p.muted), use_ansi=True)
                print()

        line = record_line(ts, kind, payload, Zoom.SUMMARY, width, payload_lens=loops_lens)
        print_block(line, use_ansi=True)
        prev_ts = ts

    # === 5. Multi-observer view ===
    _subsection("Idea 5: Multi-observer — who said what")

    print_block(Block.text(
        "  Facts have observers. An agent's output and a human's journal",
        p.muted,
    ), use_ansi=True)
    print_block(Block.text(
        "  side by side — the conversation between human and system.",
        p.muted,
    ), use_ansi=True)
    print()

    # Observer-tagged records
    multi_obs = [
        (_ts(0), "kaygee", "decision", "Use SQLite for persistence"),
        (_ts(0.5), "claude", "exchange", "→ What about migration path from filesystem?"),
        (_ts(0.5), "claude", "exchange", "← Store.migrate() wraps both, one-time conversion"),
        (_ts(1), "kaygee", "journal", "The migration dissolves — filesystem IS the degenerate case of SQLite"),
        (_ts(1.5), "claude", "change", "Removed filesystem store backend (132 lines deleted)"),
        (_ts(2), "ci", "tick", "tests: 47 passed, 0 failed"),
    ]

    # Observer gets its own color from a rotating assignment
    _observer_styles = {
        "kaygee": Style(fg="white", bold=True),
        "claude": p.accent,
        "ci": p.success,
    }

    for ts, observer, kind, text in multi_obs:
        ts_str = ts.strftime("%H:%M")
        obs_s = _observer_styles.get(observer, Style())

        segments = [
            Block.text(f"{ts_str} ", p.muted),
            Block.text(f"{observer:<7}", obs_s),
            Block.text(" [", p.muted),
            Block.text(kind, _kind_style(kind)),
            Block.text("] ", p.muted),
            Block.text(text, Style()),
        ]
        block = join_horizontal(*segments)
        print_block(block, use_ansi=True)

    print()
    print_block(Block.text(
        "  Note: color encodes source (observer), not severity.",
        p.muted,
    ), use_ansi=True)
    print_block(Block.text(
        "  This is the Docker Compose / stern pattern applied to loops.",
        p.muted,
    ), use_ansi=True)

    # === 6. Fold-aware rendering: records as computation state ===
    _subsection("Idea 6: Fold rendering — records as computation, not just events")

    print_block(Block.text(
        "  A tick isn't just 'something happened'. It's a fold step.",
        p.muted,
    ), use_ansi=True)
    print_block(Block.text(
        "  Show the accumulator evolving.",
        p.muted,
    ), use_ansi=True)
    print()

    fold_steps = [
        (_ts(0), "init", "spec=boundary-detect, acc={}"),
        (_ts(0.5), "collect", "fact:change +boundary-detection  acc={changes: 1}"),
        (_ts(1), "collect", "fact:test   +spec-validation      acc={changes: 1, tests: 1}"),
        (_ts(1.5), "collect", "fact:change +fold-loop            acc={changes: 2, tests: 1}"),
        (_ts(2), "apply", "Spec.apply(acc) → projection updated, 3 facts folded"),
    ]

    for i, (ts, phase, detail) in enumerate(fold_steps):
        ts_str = ts.strftime("%H:%M")

        # Phase styling
        if phase == "init":
            phase_s = p.muted
            marker = "○"
        elif phase == "collect":
            phase_s = p.accent
            marker = "●"
        elif phase == "apply":
            phase_s = p.success
            marker = "◉"
        else:
            phase_s = Style()
            marker = "·"

        segments = [
            Block.text(f"  {marker} ", phase_s),
            Block.text(f"{ts_str} ", p.muted),
            Block.text(f"{phase:<8}", phase_s),
            Block.text(detail, Style() if phase == "apply" else p.muted),
        ]
        block = join_horizontal(*segments)
        print_block(block, use_ansi=True)

    print()
    print_block(Block.text(
        "  The fold has shape: init → collect* → apply. Rendering can",
        p.muted,
    ), use_ansi=True)
    print_block(Block.text(
        "  show which phase you're in and what the accumulator holds.",
        p.muted,
    ), use_ansi=True)

    # === 7. Dev check / CI as records ===
    _subsection("Idea 7: Dev check results as records")

    print_block(Block.text(
        "  CI output is just records too. What does ./dev check look like",
        p.muted,
    ), use_ansi=True)
    print_block(Block.text(
        "  when rendered through the same record_line primitive?",
        p.muted,
    ), use_ansi=True)
    print()

    check_results = [
        ("atoms", "check", [
            ("ruff", "passed", 0.3),
            ("mypy", "passed", 1.2),
            ("pytest", "passed", 0.8),
        ]),
        ("engine", "check", [
            ("ruff", "passed", 0.4),
            ("mypy", "warning", 2.1),
            ("pytest", "passed", 1.5),
        ]),
        ("painted", "check", [
            ("ruff", "passed", 0.3),
            ("mypy", "passed", 1.8),
            ("pytest", "failed", 3.2),
        ]),
    ]

    for lib, cmd, steps in check_results:
        all_passed = all(s == "passed" for _, s, _ in steps)
        any_failed = any(s == "failed" for _, s, _ in steps)

        if any_failed:
            status_s = p.error
            icon = "✗"
        elif not all_passed:
            status_s = p.warning
            icon = "~"
        else:
            status_s = p.success
            icon = "✓"

        total_time = sum(t for _, _, t in steps)

        # Summary line
        segments = [
            Block.text(f"  {icon} ", status_s),
            Block.text(f"{lib:<12}", Style(bold=True)),
        ]

        step_parts: list[Block] = []
        for step_name, status, duration in steps:
            if status == "passed":
                step_parts.append(Block.text(f" {step_name}", p.success))
                step_parts.append(Block.text(f"({duration:.1f}s)", p.muted))
            elif status == "warning":
                step_parts.append(Block.text(f" {step_name}", p.warning))
                step_parts.append(Block.text(f"({duration:.1f}s)", p.muted))
            else:
                step_parts.append(Block.text(f" {step_name}", p.error))
                step_parts.append(Block.text(f"({duration:.1f}s)", p.muted))

        segments.extend(step_parts)
        segments.append(Block.text(f"  {total_time:.1f}s", p.muted))

        block = join_horizontal(*segments)
        print_block(block, use_ansi=True)

    print()
    print_block(Block.text(
        "  Same pattern: record_line(ts, 'check', {lib, steps, status}, zoom, width).",
        p.muted,
    ), use_ansi=True)
    print_block(Block.text(
        "  A check run IS a fold: init → step* → result. The tick model fits.",
        p.muted,
    ), use_ansi=True)


# ===========================================================================
# PART 2: Composable Lens Modifiers
# ===========================================================================
#
# Modifiers are functions that transform a rendered Block (the output of
# record_line) by adding a visual dimension. They compose by wrapping:
#
#   gutter(attention(record_line(...)))
#
# Each modifier takes the Block + the record's metadata and returns a new
# Block with the modifier applied. This is function composition, not
# parameter accumulation.

# ---------------------------------------------------------------------------
# Modifier: gutter — colored left edge encoding one dimension
# ---------------------------------------------------------------------------

GutterFn = Callable[[str, dict], tuple[str, Style]]
"""(kind, payload) -> (gutter_char, style). Maps record to gutter appearance."""


def gutter_lifecycle(kind: str, payload: dict) -> tuple[str, Style]:
    """Gutter by task lifecycle: green=moving, yellow=stalled, red=blocked."""
    p = current_palette()
    status = payload.get("status", "")
    if status in ("blocked", "errored", "failed"):
        return "█", p.error
    if status in ("stalled", "waiting", "pending"):
        return "▐", p.warning
    if status in ("running", "in-progress", "active"):
        return "│", p.success
    if status in ("completed", "done", "decided", "healthy"):
        return "│", p.success
    return "│", p.muted


def gutter_freshness(kind: str, payload: dict) -> tuple[str, Style]:
    """Gutter by freshness: bright=recent, dim=stale."""
    p = current_palette()
    age_days = payload.get("_age_days", 0)
    if age_days <= 1:
        return "│", p.accent
    if age_days <= 7:
        return "│", Style()
    if age_days <= 30:
        return "│", p.muted
    return "·", p.muted


def gutter_pass_fail(kind: str, payload: dict) -> tuple[str, Style]:
    """Gutter by pass/fail for test/check results."""
    p = current_palette()
    status = payload.get("status", "")
    if status in ("passed", "success", "ok"):
        return "│", p.success
    if status in ("warning", "warn"):
        return "▐", p.warning
    if status in ("failed", "error"):
        return "█", p.error
    return "│", p.muted


def gutter_observer(kind: str, payload: dict) -> tuple[str, Style]:
    """Gutter by observer source."""
    p = current_palette()
    observer = payload.get("observer", payload.get("source", ""))
    # Rotate through palette roles
    _obs_map = {
        "human": Style(fg="white", bold=True),
        "kaygee": Style(fg="white", bold=True),
        "claude": p.accent,
        "agent": p.accent,
        "ci": p.success,
        "system": p.muted,
    }
    return "│", _obs_map.get(observer, Style())


def apply_gutter(
    block: Block,
    kind: str,
    payload: dict,
    gutter_fn: GutterFn,
) -> Block:
    """Apply a gutter modifier to a rendered block."""
    ch, style = gutter_fn(kind, payload)
    gutter = Block.text(f"{ch} ", style)
    return join_horizontal(gutter, block)


# ---------------------------------------------------------------------------
# Modifier: attention — dim/highlight by information-gain
# ---------------------------------------------------------------------------

AttentionFn = Callable[[str, dict], float]
"""(kind, payload) -> attention score 0.0 (ignore) to 1.0 (highlight)."""


def attention_staleness(kind: str, payload: dict) -> float:
    """Stale items dim, fresh items bright."""
    age_days = payload.get("_age_days", 0)
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.7
    if age_days <= 30:
        return 0.3
    return 0.1


def attention_novelty(kind: str, payload: dict) -> float:
    """First occurrences highlight, repeated events dim."""
    occurrences = payload.get("occurrences", payload.get("_count", 1))
    if occurrences <= 1:
        return 1.0
    if occurrences <= 3:
        return 0.6
    return 0.2


def attention_blocked(kind: str, payload: dict) -> float:
    """Blocked tasks scream, completed tasks whisper."""
    status = payload.get("status", "")
    if status in ("blocked", "errored", "failed"):
        return 1.0
    if status in ("stalled", "waiting"):
        return 0.8
    if status in ("running", "in-progress", "active"):
        return 0.5
    if status in ("completed", "done"):
        return 0.2
    return 0.5


def attention_relevance(kind: str, payload: dict) -> float:
    """Score-based attention for search results."""
    return payload.get("_relevance", 0.5)


def apply_attention(
    block: Block,
    kind: str,
    payload: dict,
    attention_fn: AttentionFn,
    *,
    zoom: Zoom = Zoom.SUMMARY,
    width: int = 80,
    ts: datetime | None = None,
    payload_lens: PayloadLens | None = None,
) -> Block:
    """Apply attention modifier: high-attention records render fully,
    low-attention records collapse to a dimmed one-liner."""
    score = attention_fn(kind, payload)
    p = current_palette()

    if score >= 0.7:
        # Full rendering — return block unchanged (or add highlight marker)
        marker = Block.text("◆ ", _kind_style(kind))
        return join_horizontal(marker, block)
    elif score >= 0.3:
        # Normal rendering, no marker
        return join_horizontal(Block.text("  ", Style()), block)
    else:
        # Collapse to dim one-liner regardless of zoom
        summary = _default_payload_summary(kind, payload)
        if len(summary) > width - 10:
            summary = summary[: width - 11] + "…"
        ts_str = ts.strftime("%H:%M") if ts else ""
        prefix = f"{ts_str} " if ts_str else ""
        dim_line = Block.text(f"· {prefix}{kind}: {summary}", p.muted)
        return dim_line


# ---------------------------------------------------------------------------
# Composed rendering: record with modifiers
# ---------------------------------------------------------------------------

def record_line_composed(
    ts: datetime,
    kind: str,
    payload: dict,
    zoom: Zoom,
    width: int,
    *,
    payload_lens: PayloadLens | None = None,
    gutter_fn: GutterFn | None = None,
    attention_fn: AttentionFn | None = None,
) -> Block:
    """record_line with composable modifiers applied.

    Composition order: record_line → attention → gutter (outside-in).
    Gutter is outermost because it's a visual frame.
    """
    # Reserve width for gutter if present
    inner_width = width - 2 if gutter_fn else width

    # Base render
    block = record_line(ts, kind, payload, zoom, inner_width, payload_lens=payload_lens)

    # Apply attention (may collapse to one-liner)
    if attention_fn:
        block = apply_attention(
            block, kind, payload, attention_fn,
            zoom=zoom, width=inner_width, ts=ts, payload_lens=payload_lens,
        )

    # Apply gutter (outermost)
    if gutter_fn:
        block = apply_gutter(block, kind, payload, gutter_fn)

    return block


# ---------------------------------------------------------------------------
# record_map — topological grouping by key hierarchy
# ---------------------------------------------------------------------------

def record_map(
    records: list[tuple[datetime, str, dict]],
    zoom: Zoom,
    width: int,
    *,
    group_key: Callable[[str, dict], str] = lambda k, p: k,
    payload_lens: PayloadLens | None = None,
    gutter_fn: GutterFn | None = None,
    attention_fn: AttentionFn | None = None,
    sort_groups: str = "alpha",  # "alpha", "count", "recent"
) -> Block:
    """Render records grouped by a topological key, not by time.

    group_key: (kind, payload) -> group name. Supports hierarchy via '/'.
    sort_groups: how to order groups — alphabetical, by count, or most recent first.

    Zoom behavior:
      MINIMAL  — group names + counts, one line
      SUMMARY  — group headers + latest record per group
      DETAILED — group headers + all records per group
      FULL     — group headers + all records fully expanded
    """
    if not records:
        return Block.text("(no records)", current_palette().muted)

    p = current_palette()

    # Group records
    groups: dict[str, list[tuple[datetime, str, dict]]] = {}
    for ts, kind, payload in records:
        key = group_key(kind, payload)
        groups.setdefault(key, []).append((ts, kind, payload))

    # Sort groups
    if sort_groups == "count":
        sorted_keys = sorted(groups.keys(), key=lambda k: len(groups[k]), reverse=True)
    elif sort_groups == "recent":
        sorted_keys = sorted(groups.keys(), key=lambda k: max(ts for ts, _, _ in groups[k]), reverse=True)
    else:
        sorted_keys = sorted(groups.keys())

    # --- MINIMAL: group names + counts ---
    if zoom <= Zoom.MINIMAL:
        parts = [f"{k} ({len(v)})" for k, v in [(k, groups[k]) for k in sorted_keys]]
        return Block.text("  ".join(parts), Style(), width=width)

    # --- Build tree structure ---
    # Parse hierarchy from '/' in keys
    tree: dict[str, dict[str, list[tuple[datetime, str, dict]]]] = {}
    for key in sorted_keys:
        parts = key.split("/", 1)
        if len(parts) == 2:
            tree.setdefault(parts[0], {})[parts[1]] = groups[key]
        else:
            tree.setdefault(key, {})[""] = groups[key]

    all_blocks: list[Block] = []

    for top_key in tree:
        subtree = tree[top_key]
        total_count = sum(len(v) for v in subtree.values())

        # Top-level group header
        header_parts = [
            Block.text(f"  {top_key}", Style(bold=True)),
            Block.text(f" ({total_count})", p.muted),
        ]
        all_blocks.append(join_horizontal(*header_parts))

        for sub_key, sub_records in subtree.items():
            # Sort by timestamp within group
            sub_records.sort(key=lambda r: r[0])

            if sub_key:
                # Sub-group header
                sub_header = Block.text(f"    {sub_key} ({len(sub_records)})", p.accent)
                all_blocks.append(sub_header)
                indent = 6
            else:
                indent = 4

            if zoom <= Zoom.SUMMARY:
                # Show only the latest record per group
                latest_ts, latest_kind, latest_payload = sub_records[-1]
                line = record_line_composed(
                    latest_ts, latest_kind, latest_payload, Zoom.SUMMARY,
                    width - indent,
                    payload_lens=payload_lens,
                    gutter_fn=gutter_fn,
                    attention_fn=attention_fn,
                )
                all_blocks.append(pad(line, left=indent))
            else:
                # Show all records
                record_zoom = Zoom.DETAILED if zoom <= Zoom.DETAILED else Zoom.FULL
                for ts, kind, payload in sub_records:
                    line = record_line_composed(
                        ts, kind, payload, record_zoom,
                        width - indent,
                        payload_lens=payload_lens,
                        gutter_fn=gutter_fn,
                        attention_fn=attention_fn,
                    )
                    all_blocks.append(pad(line, left=indent))

        # Gap between top-level groups
        all_blocks.append(Block.text("", Style()))

    return join_vertical(*all_blocks)


# ===========================================================================
# PART 3: Concrete Scenario Demos
# ===========================================================================

# ---------------------------------------------------------------------------
# Scenario 1: loops dev project — Task Board
# ---------------------------------------------------------------------------

TASK_BOARD_DATA: list[tuple[datetime, str, dict]] = [
    (_ts(0), "task", {
        "name": "implement-fold",
        "status": "in-progress",
        "summary": "Wire up Spec.apply to projection fold loop",
        "assignee": "worker-1",
        "_age_days": 1,
    }),
    (_ts(0.5), "task", {
        "name": "vertex-routing",
        "status": "blocked",
        "summary": "Waiting on slashed name resolution design",
        "blocked_by": "decision: vertex naming convention",
        "_age_days": 3,
    }),
    (_ts(1), "task", {
        "name": "store-transport",
        "status": "completed",
        "summary": "Dissolved into store.merge() + store.slice()",
        "_age_days": 0,
    }),
    (_ts(1.5), "task", {
        "name": "sqlite-migration",
        "status": "stalled",
        "summary": "Migration harness written, needs integration test",
        "_age_days": 5,
    }),
    (_ts(2), "task", {
        "name": "kdl-validator",
        "status": "running",
        "summary": "Schema validation for .vertex files",
        "assignee": "worker-2",
        "_age_days": 0,
    }),
]

TEST_RESULT_DATA: list[tuple[datetime, str, dict]] = [
    (_ts(3), "test", {"name": "atoms", "status": "passed", "tests": 24, "duration": "0.8s"}),
    (_ts(3), "test", {"name": "engine", "status": "passed", "tests": 31, "duration": "1.5s"}),
    (_ts(3), "test", {"name": "painted", "status": "failed", "tests": 47, "duration": "3.2s",
                       "failures": "test_gutter_wrap: expected 80 cols, got 82"}),
    (_ts(3), "test", {"name": "store", "status": "passed", "tests": 18, "duration": "0.9s"}),
    (_ts(3), "test", {"name": "lang", "status": "warning", "tests": 12, "duration": "2.1s",
                       "warnings": "2 deprecation warnings"}),
]

SESSION_LOG_DATA: list[tuple[datetime, str, dict]] = [
    (_ts(0), "session.start", {"observer": "worker-1", "task": "implement-fold"}),
    (_ts(0.5), "change", {
        "summary": "Added fold loop skeleton",
        "observer": "worker-1",
        "files": "libs/engine/src/engine/projection.py",
    }),
    (_ts(1), "exchange", {
        "observer": "worker-1",
        "prompt": "Should fold collect latest or collect 1?",
        "response": "Collect 1 — latest loses intermediate state",
        "occurrences": 1,
    }),
    (_ts(1.5), "tick", {
        "name": "implement-fold",
        "status": "running",
        "fold": "3 files changed, tests passing",
        "observer": "worker-1",
    }),
    (_ts(2), "error", {
        "message": "Assertion failed: fold boundary not detected",
        "observer": "worker-1",
        "occurrences": 1,
    }),
    (_ts(2.5), "change", {
        "summary": "Fixed boundary detection in fold loop",
        "observer": "worker-1",
        "files": "libs/atoms/src/atoms/spec.py",
        "occurrences": 1,
    }),
    (_ts(3), "tick", {
        "name": "implement-fold",
        "status": "running",
        "fold": "6 files changed, tests passing",
        "observer": "worker-1",
        "occurrences": 3,  # routine progress
    }),
]


def test_lens(kind: str, payload: dict, zoom: Zoom) -> str | Block:
    """Lens for test results."""
    name = payload.get("name", "")
    status = payload.get("status", "")
    tests = payload.get("tests", 0)
    duration = payload.get("duration", "")
    p = current_palette()

    status_style = {
        "passed": p.success, "failed": p.error, "warning": p.warning,
    }.get(status, Style())

    if zoom <= Zoom.SUMMARY:
        parts = [
            Block.text(f"{name:<10}", Style(bold=True)),
            Block.text(f" {status:<8}", status_style),
            Block.text(f" {tests} tests", p.muted),
            Block.text(f" {duration}", p.muted),
        ]
        return join_horizontal(*parts)

    return f"{name}: {status} ({tests} tests, {duration})"


def demo_task_board(width: int = 80) -> None:
    """Scenario 1: loops dev project — task board with composed modifiers."""
    _section("Scenario: Task Board (loops dev project)", width)

    p = current_palette()

    # --- Tasks with gutter(lifecycle) + attention(blocked_duration) ---
    _subsection("Tasks: gutter(lifecycle) + attention(blocked_duration)")

    for ts, kind, payload in TASK_BOARD_DATA:
        block = record_line_composed(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=loops_lens,
            gutter_fn=gutter_lifecycle,
            attention_fn=attention_blocked,
        )
        print_block(block, use_ansi=True)

    # --- Same tasks without modifiers for comparison ---
    _subsection("Same tasks, no modifiers (flat list)")

    for ts, kind, payload in TASK_BOARD_DATA:
        block = record_line(ts, kind, payload, Zoom.SUMMARY, width, payload_lens=loops_lens)
        print_block(block, use_ansi=True)

    # --- Test results with gutter(pass/fail) ---
    _subsection("Test results: gutter(pass/fail)")

    for ts, kind, payload in TEST_RESULT_DATA:
        block = record_line_composed(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=test_lens,
            gutter_fn=gutter_pass_fail,
        )
        print_block(block, use_ansi=True)

    # --- Session log with attention(novelty) ---
    _subsection("Session log: attention(novelty) — new events highlight, routine dims")

    for ts, kind, payload in SESSION_LOG_DATA:
        block = record_line_composed(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=loops_lens,
            attention_fn=attention_novelty,
        )
        print_block(block, use_ansi=True)

    # --- Full composition: gutter + attention ---
    _subsection("Full composition: gutter(lifecycle) + attention(novelty)")

    for ts, kind, payload in SESSION_LOG_DATA:
        block = record_line_composed(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=loops_lens,
            gutter_fn=gutter_lifecycle,
            attention_fn=attention_novelty,
        )
        print_block(block, use_ansi=True)


# ---------------------------------------------------------------------------
# Scenario 2: meta-discussion — Decision Map
# ---------------------------------------------------------------------------

META_DECISIONS: list[tuple[datetime, str, dict]] = [
    # architecture/*
    (_ts(0, days=-30), "decision", {
        "topic": "architecture/claude-md-levels",
        "message": "Four levels, each adds not repeats",
        "_age_days": 30,
    }),
    (_ts(0, days=-25), "decision", {
        "topic": "architecture/claude-md-antipatterns",
        "message": "God/stale/redundant/missing — the four failure modes",
        "_age_days": 25,
    }),
    (_ts(0, days=-20), "decision", {
        "topic": "architecture/doc-roles",
        "message": "CLAUDE.md is working context, README for API consumers",
        "_age_days": 20,
    }),
    (_ts(0, days=-2), "decision", {
        "topic": "architecture/app-dissolution",
        "message": "Apps dissolve into lenses + feedback over vertex declarations",
        "_age_days": 2,
    }),
    # design/*
    (_ts(0, days=-15), "decision", {
        "topic": "design/dissolution-method",
        "message": "Before building X, ask if X dissolves into existing primitives",
        "_age_days": 15,
    }),
    (_ts(0, days=-10), "decision", {
        "topic": "design/progressive-vertex-chain",
        "message": "CLAUDE.md is the lens, the vertex store is the state",
        "_age_days": 10,
    }),
    (_ts(0, days=-1), "decision", {
        "topic": "design/record-rendering",
        "message": "Three-layer architecture: painted → store atoms → domain lenses",
        "_age_days": 1,
    }),
    # workflow/*
    (_ts(0, days=-12), "decision", {
        "topic": "workflow/handoff-as-fact",
        "message": "Handoff dissolves into the store — no separate mechanism",
        "_age_days": 12,
    }),
    (_ts(0, days=-5), "decision", {
        "topic": "workflow/subtask-workers",
        "message": "Workers branch from HEAD, verify claims, commit before drafting dependents",
        "_age_days": 5,
    }),
    # testing/*
    (_ts(0, days=-8), "decision", {
        "topic": "testing/golden-snapshots",
        "message": "Snapshot tests across 4 zoom levels for all display commands",
        "_age_days": 8,
    }),
]

META_THREADS: list[tuple[datetime, str, dict]] = [
    (_ts(0, days=-3), "thread", {
        "topic": "architecture/record-rendering",
        "name": "record-rendering-api",
        "status": "active",
        "summary": "Designing record_line/record_timeline/PayloadLens primitives",
        "_age_days": 0,  # hot
    }),
    (_ts(0, days=-7), "thread", {
        "topic": "design/vertex-templates",
        "name": "vertex-template-system",
        "status": "active",
        "summary": "Domain vertices = code, knowledge vertices = runtime config",
        "_age_days": 7,
    }),
    (_ts(0, days=-20), "thread", {
        "topic": "architecture/transport-dissolution",
        "name": "dissolve-transport",
        "status": "decided",
        "summary": "Transport dissolved into store.merge() + store.slice()",
        "_age_days": 0,
    }),
    (_ts(0, days=-14), "thread", {
        "topic": "workflow/ci-pipeline",
        "name": "ci-pipeline-design",
        "status": "exploring",
        "summary": "Should dev check be the only CI gate?",
        "_age_days": 14,  # stale
    }),
]


def _topic_group(kind: str, payload: dict) -> str:
    """Extract topic namespace from payload for record_map grouping."""
    topic = payload.get("topic", payload.get("name", kind))
    # Return the namespace prefix (e.g. "architecture" from "architecture/doc-roles")
    parts = topic.split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])  # preserve "architecture/subtopic"
    return parts[0]


def _topic_namespace(kind: str, payload: dict) -> str:
    """Extract just the top-level namespace."""
    topic = payload.get("topic", payload.get("name", kind))
    return topic.split("/")[0]


def meta_lens(kind: str, payload: dict, zoom: Zoom) -> str | Block:
    """Lens for meta-discussion records — shows topic hierarchy."""
    p = current_palette()
    topic = payload.get("topic", "")
    message = payload.get("message", "")
    status = payload.get("status", "")
    name = payload.get("name", "")

    if kind == "decision":
        # Show just the leaf topic + message
        leaf = topic.split("/")[-1] if "/" in topic else topic
        if zoom <= Zoom.SUMMARY:
            return f"{leaf}: {message}" if message else leaf
        return leaf

    if kind == "thread":
        status_style = {
            "active": p.accent,
            "decided": p.success,
            "exploring": p.muted,
        }.get(status, Style())
        parts = [
            Block.text(f"{name} ", Style()),
            Block.text(f"[{status}]", status_style),
        ]
        if zoom >= Zoom.SUMMARY and payload.get("summary"):
            parts.append(Block.text(f" {payload['summary']}", p.muted))
        return join_horizontal(*parts)

    return _default_payload_summary(kind, payload)


def demo_decision_map(width: int = 80) -> None:
    """Scenario 2: meta-discussion decision map — topological, not temporal."""
    _section("Scenario: Decision Map (meta-discussion)", width)

    p = current_palette()

    # --- Decision landscape as record_map ---
    _subsection("Decision map: grouped by topic namespace")

    print_block(Block.text(
        "  record_map groups by key hierarchy, not time.",
        p.muted,
    ), use_ansi=True)
    print_block(Block.text(
        "  MINIMAL shows density. SUMMARY shows latest per group. DETAILED shows all.",
        p.muted,
    ), use_ansi=True)
    print()

    for z in [Zoom.MINIMAL, Zoom.SUMMARY, Zoom.DETAILED]:
        label = Block.text(f"  {z.name:>8}: ", p.muted)
        print_block(label, use_ansi=True)
        block = record_map(
            META_DECISIONS, z, width - 2,
            group_key=_topic_namespace,
            payload_lens=meta_lens,
            gutter_fn=gutter_freshness,
            sort_groups="count",
        )
        print_block(pad(block, left=2), use_ansi=True)
        print()

    # --- Thread pipeline with attention(staleness) + gutter(freshness) ---
    _subsection("Thread pipeline: gutter(freshness) + attention(staleness)")

    print_block(Block.text(
        "  Open threads — stale ones dim, fresh ones highlight.",
        p.muted,
    ), use_ansi=True)
    print()

    for ts, kind, payload in META_THREADS:
        block = record_line_composed(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=meta_lens,
            gutter_fn=gutter_freshness,
            attention_fn=attention_staleness,
        )
        print_block(block, use_ansi=True)

    # --- Thread status as history arc (from Idea 2, now with modifiers) ---
    _subsection("Thread arcs within decision map")

    print_block(Block.text(
        "  Same thread evolution from Idea 2, now inside a topological group.",
        p.muted,
    ), use_ansi=True)
    print()

    # architecture/ group header
    header = join_horizontal(
        Block.text("  architecture", Style(bold=True)),
        Block.text(" — 4 decisions, 1 active thread, 1 resolved", p.muted),
    )
    print_block(header, use_ansi=True)

    # Thread arc nested under the group
    arc_states = [
        (_ts(0, days=-20), "exploring", "What replaces direct cross-lib imports?"),
        (_ts(0, days=-10), "active", "Three-layer architecture: painted → atoms → domain"),
        (_ts(0, days=-1), "decided", "Lenses + feedback over vertex declarations"),
    ]
    for i, (ts, status, note) in enumerate(arc_states):
        ts_str = ts.strftime("%b %d")
        if i == 0:
            connector, connector_s = "┌", p.muted
        elif i == len(arc_states) - 1:
            connector, connector_s = "└", p.success
        else:
            connector, connector_s = "├", p.accent

        status_s = {"exploring": p.muted, "active": p.accent, "decided": p.success}.get(status, Style())

        segments = [
            Block.text(f"    {connector}─ ", connector_s),
            Block.text(f"{ts_str} ", p.muted),
            Block.text(f"[{status}] ", status_s),
            Block.text(note, p.muted if status == "exploring" else Style()),
        ]
        line = join_horizontal(*segments)

        if i < len(arc_states) - 1:
            pipe = Block.text("    │", connector_s)
            print_block(join_vertical(line, pipe), use_ansi=True)
        else:
            print_block(line, use_ansi=True)


# ---------------------------------------------------------------------------
# Scenario 3: siftd — Conversation Views
# ---------------------------------------------------------------------------

SIFTD_CONVERSATIONS: list[tuple[datetime, str, dict]] = [
    (_ts(0, days=-1), "conversation", {
        "title": "Dissolving transport into store operations",
        "observer": "claude",
        "source": "claude",
        "tags": "architecture, dissolution",
        "exchanges": 14,
        "_relevance": 0.95,
        "_age_days": 1,
    }),
    (_ts(0, days=-2), "conversation", {
        "title": "Progressive CLAUDE.md system design",
        "observer": "claude",
        "source": "claude",
        "tags": "architecture, documentation",
        "exchanges": 22,
        "_relevance": 0.88,
        "_age_days": 2,
    }),
    (_ts(0, days=-3), "conversation", {
        "title": "Vertex template system — instance vs aggregation",
        "observer": "claude",
        "source": "claude",
        "tags": "architecture, vertex",
        "exchanges": 8,
        "_relevance": 0.72,
        "_age_days": 3,
    }),
    (_ts(0, days=-7), "conversation", {
        "title": "Setting up alcove monitoring with Grafana",
        "observer": "claude",
        "source": "claude",
        "tags": "homelab, monitoring",
        "exchanges": 6,
        "_relevance": 0.3,
        "_age_days": 7,
    }),
    (_ts(0, days=-14), "conversation", {
        "title": "Initial loops project setup and pyproject.toml",
        "observer": "claude",
        "source": "claude",
        "tags": "setup, tooling",
        "exchanges": 4,
        "_relevance": 0.15,
        "_age_days": 14,
    }),
]

SIFTD_SEARCH_RESULTS: list[tuple[datetime, str, dict]] = [
    (_ts(0, days=-1), "search_result", {
        "query": "dissolution",
        "title": "Dissolving transport into store operations",
        "excerpt": "The key insight: transport is just store operations across a boundary.",
        "source": "conversation-2025-01-14",
        "_relevance": 0.95,
        "_age_days": 1,
    }),
    (_ts(0, days=-10), "search_result", {
        "query": "dissolution",
        "title": "Dissolution method — design principle",
        "excerpt": "Before building X, ask if X dissolves into existing primitives. If yes, it's not a new thing.",
        "source": "meta-discussion",
        "_relevance": 0.88,
        "_age_days": 10,
    }),
    (_ts(0, days=-5), "search_result", {
        "query": "dissolution",
        "title": "Should vertex discovery use dissolution?",
        "excerpt": "Flat discovery dissolves into aggregation vertices. No nested discovery needed.",
        "source": "conversation-2025-01-10",
        "_relevance": 0.65,
        "_age_days": 5,
    }),
    (_ts(0, days=-20), "search_result", {
        "query": "dissolution",
        "title": "Exploring cells library architecture",
        "excerpt": "Cells dissolved into painted. The block/cell model replaced the cells library entirely.",
        "source": "conversation-2025-01-01",
        "_relevance": 0.4,
        "_age_days": 20,
    }),
]

SIFTD_TAGS: list[tuple[datetime, str, dict]] = [
    (_ts(0, days=-1), "tag", {"name": "architecture", "conversations": 12, "last_used_days": 1, "_age_days": 1}),
    (_ts(0, days=-2), "tag", {"name": "dissolution", "conversations": 5, "last_used_days": 1, "_age_days": 1}),
    (_ts(0, days=-3), "tag", {"name": "vertex", "conversations": 4, "last_used_days": 3, "_age_days": 3}),
    (_ts(0, days=-5), "tag", {"name": "documentation", "conversations": 3, "last_used_days": 2, "_age_days": 2}),
    (_ts(0, days=-7), "tag", {"name": "homelab", "conversations": 6, "last_used_days": 7, "_age_days": 7}),
    (_ts(0, days=-14), "tag", {"name": "tooling", "conversations": 8, "last_used_days": 14, "_age_days": 14}),
    (_ts(0, days=-30), "tag", {"name": "setup", "conversations": 2, "last_used_days": 30, "_age_days": 30}),
]


def siftd_lens(kind: str, payload: dict, zoom: Zoom) -> str | Block:
    """Lens for siftd records."""
    p = current_palette()

    if kind == "conversation":
        title = payload.get("title", "")
        exchanges = payload.get("exchanges", 0)
        tags = payload.get("tags", "")
        if zoom <= Zoom.SUMMARY:
            parts = [
                Block.text(title, Style()),
                Block.text(f"  ({exchanges} exchanges)", p.muted),
            ]
            return join_horizontal(*parts)
        return title

    if kind == "search_result":
        title = payload.get("title", "")
        excerpt = payload.get("excerpt", "")
        source = payload.get("source", "")
        relevance = payload.get("_relevance", 0)
        # Relevance bar: filled proportional to score
        bar_width = 5
        filled = int(relevance * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        parts = [
            Block.text(f"{bar} ", p.accent if relevance > 0.7 else p.muted),
            Block.text(title, Style(bold=True) if relevance > 0.7 else Style()),
        ]
        if zoom >= Zoom.SUMMARY:
            parts.append(Block.text(f"  {source}", p.muted))
        return join_horizontal(*parts)

    if kind == "tag":
        name = payload.get("name", "")
        count = payload.get("conversations", 0)
        # Visual density indicator
        density = min(count, 12)
        dots = "●" * density + "○" * (12 - density)
        parts = [
            Block.text(f"{name:<16}", Style(bold=True)),
            Block.text(f"{dots} ", p.accent),
            Block.text(f"{count} conversations", p.muted),
        ]
        return join_horizontal(*parts)

    return _default_payload_summary(kind, payload)


def _tag_group(kind: str, payload: dict) -> str:
    """Group by tag name for record_map."""
    return payload.get("name", kind)


def demo_siftd_views(width: int = 80) -> None:
    """Scenario 3: siftd conversation views."""
    _section("Scenario: siftd Conversation Views", width)

    p = current_palette()

    # --- Conversation list with gutter(observer) + attention(freshness) ---
    _subsection("Conversation list: gutter(observer) + attention(freshness)")

    for ts, kind, payload in SIFTD_CONVERSATIONS:
        block = record_line_composed(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=siftd_lens,
            gutter_fn=gutter_observer,
            attention_fn=attention_staleness,
        )
        print_block(block, use_ansi=True)

    # --- Search results with attention(relevance) ---
    _subsection("Search results for 'dissolution': attention(relevance)")

    for ts, kind, payload in SIFTD_SEARCH_RESULTS:
        block = record_line_composed(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=siftd_lens,
            attention_fn=attention_relevance,
        )
        print_block(block, use_ansi=True)

    # --- Tag view as record_map ---
    _subsection("Tag view: record_map grouped by tag name")

    print_block(Block.text(
        "  Tags as a density map — which topics are active?",
        p.muted,
    ), use_ansi=True)
    print()

    for ts, kind, payload in SIFTD_TAGS:
        block = record_line_composed(
            ts, kind, payload, Zoom.SUMMARY, width,
            payload_lens=siftd_lens,
            gutter_fn=gutter_freshness,
        )
        print_block(block, use_ansi=True)

    # --- Search results at DETAILED zoom ---
    _subsection("Search results at DETAILED — excerpt visible")

    for ts, kind, payload in SIFTD_SEARCH_RESULTS[:3]:
        # Render with excerpt as secondary field
        block = record_line_composed(
            ts, kind, payload, Zoom.DETAILED, width,
            payload_lens=siftd_lens,
            attention_fn=attention_relevance,
        )
        print_block(block, use_ansi=True)


# ===========================================================================
# PART 4: New Research Principles
# ===========================================================================

def demo_research_update(width: int = 80) -> None:
    """New principles discovered from topological + composition work."""
    _section("Research Update: New Principles from Composition", width)

    p = current_palette()

    principles = [
        (
            "Modifiers compose outside-in: content → attention → gutter",
            "Attention can collapse content to a one-liner. Gutter wraps whatever "
            "attention produces. This is function composition: gutter(attention("
            "record_line(...))). Parameters don't compose; wrapper functions do.",
        ),
        (
            "Topological > temporal for decision stores",
            "Decisions cluster by topic, not by time. record_map groups by key "
            "hierarchy, showing density per group. MINIMAL gives the landscape; "
            "SUMMARY shows latest per group; DETAILED shows everything.",
        ),
        (
            "Attention is not severity — it's information-gain",
            "The 47th repeated error is low-attention. A first decision on a new "
            "topic is high-attention. Staleness, novelty, and relevance are all "
            "attention dimensions. Different views pick different attention functions.",
        ),
        (
            "The gutter encodes a single orthogonal dimension",
            "Lifecycle (green/yellow/red), freshness (bright/dim), pass/fail, "
            "observer source — each is a different gutter function. A view picks "
            "ONE gutter. The gutter never repeats what the label already says.",
        ),
    ]

    for i, (title, body) in enumerate(principles, 7):  # Continue numbering from Part 1
        block = _principle(i, title, body, width)
        print_block(block, use_ansi=True)
        if i < 10:
            print()

    _subsection("The universal rendering vocabulary")

    print_block(Block.text(
        "  record_line  = one timestamped entry with a kind + payload",
        Style(),
    ), use_ansi=True)
    print_block(Block.text(
        "  record_map   = records grouped by key hierarchy (topological)",
        Style(),
    ), use_ansi=True)
    print_block(Block.text(
        "  record_timeline = records grouped by date (temporal)",
        Style(),
    ), use_ansi=True)
    print_block(Block.text(
        "  PayloadLens  = (kind, payload, zoom) → str | Block",
        Style(),
    ), use_ansi=True)
    print_block(Block.text(
        "  GutterFn     = (kind, payload) → (char, style)",
        Style(),
    ), use_ansi=True)
    print_block(Block.text(
        "  AttentionFn  = (kind, payload) → float 0..1",
        Style(),
    ), use_ansi=True)
    print()
    print_block(Block.text(
        "  A view is: record_{timeline,map} + PayloadLens + GutterFn? + AttentionFn?",
        p.accent,
    ), use_ansi=True)
    print_block(Block.text(
        "  Everything else is a parameter on one of these.",
        p.muted,
    ), use_ansi=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    width = 80

    print_block(Block.text(
        "Record Line Demo — painted design exploration",
        Style(bold=True),
    ), use_ansi=True)
    print_block(Block.text(
        "Exploring timestamped record rendering with zoom, width, and color",
        current_palette().muted,
    ), use_ansi=True)

    # Part 1: Original explorations
    demo_zoom_levels(width)
    demo_default_vs_lens(width)
    demo_width_degradation(width)
    demo_variety(width)
    demo_timeline(width)
    demo_color_exploration(width)
    demo_gutter_variant(width)
    demo_research_philosophy(width)
    demo_loops_way(width)

    # Part 2-3: Composable modifiers + Concrete scenarios
    demo_task_board(width)
    demo_decision_map(width)
    demo_siftd_views(width)

    # Part 4: Updated research
    demo_research_update(width)

    print()
    print_block(Block.text("Done.", current_palette().muted), use_ansi=True)


if __name__ == "__main__":
    main()
