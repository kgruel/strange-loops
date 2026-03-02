"""Record rendering primitives — timestamped records as styled Blocks.

Three composable primitives for rendering timestamped records:

    record_line       — one record → one Block (zoom-aware)
    record_timeline   — records grouped by date (temporal)
    record_map        — records grouped by key hierarchy (topological)

Plus composable modifiers applied via record_line_composed:

    GutterFn    — colored left edge encoding one dimension
    AttentionFn — dim/highlight by information-gain score

Promoted from experiments/record_line_demo.py.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from .block import Block
from .cell import Style
from .compose import join_horizontal, join_vertical, pad, truncate
from .fidelity import Zoom
from .palette import current_palette
from ._text_width import display_width


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class PayloadLens(Protocol):
    """(kind, payload, zoom) → str | Block.

    Domain-specific rendering of a record's payload. Returns either a plain
    string (rendered with default style) or a pre-styled Block.
    """

    def __call__(self, kind: str, payload: dict, zoom: Zoom) -> str | Block: ...


class GutterFn(Protocol):
    """(kind, payload) → (gutter_char, style).

    Maps a record to its gutter appearance — a single character with a style.
    The gutter encodes exactly one orthogonal dimension (lifecycle, freshness,
    pass/fail, etc.). A view picks ONE gutter function.
    """

    def __call__(self, kind: str, payload: dict) -> tuple[str, Style]: ...


class AttentionFn(Protocol):
    """(kind, payload) → float 0.0–1.0.

    Scores a record's information-gain. High-attention records render fully,
    low-attention records collapse to a dimmed one-liner. Attention is not
    severity — it's how much a record changes your understanding.
    """

    def __call__(self, kind: str, payload: dict) -> float: ...


# ---------------------------------------------------------------------------
# Kind → color mapping
# ---------------------------------------------------------------------------


def _kind_style(kind: str) -> Style:
    """Map a record kind to a palette style.

    Semantic mapping. Follows the journalctl principle:
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
        return Block.text(summary, Style(), width=width)

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
    meta_width = ts_w + display_width(label_text) + 3  # 3 = "[] " around label + space after
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
            segments.append(truncate(content, content_width))
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
        indent = " " * (ts_w + display_width(label_text) + 3)
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

    indent = " " * (ts_w + display_width(label_text) + 3)
    for k, v in payload.items():
        if v is None or v == "":
            continue
        field_text = f"{indent}{k}: {v}"
        if len(field_text) > width:
            field_text = field_text[: width - 1] + "…"
        lines.append(Block.text(field_text, p.muted))

    return join_vertical(*lines)


# ---------------------------------------------------------------------------
# record_timeline — temporal composition
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
# Modifier application
# ---------------------------------------------------------------------------


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


def apply_attention(
    block: Block,
    kind: str,
    payload: dict,
    attention_fn: AttentionFn,
    *,
    zoom: Zoom = Zoom.SUMMARY,
    width: int,
    ts: datetime | None = None,
    payload_lens: PayloadLens | None = None,
) -> Block:
    """Apply attention modifier: high-attention records render fully,
    low-attention records collapse to a dimmed one-liner.

    Args:
        width: Target width. Required because the low-attention collapse path
            creates a Block at this width.
    """
    score = attention_fn(kind, payload)
    p = current_palette()

    if score >= 0.7:
        # Full rendering with highlight marker
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
        return Block.text(f"· {prefix}{kind}: {summary}", p.muted, width=width)


# ---------------------------------------------------------------------------
# record_line_composed — record with modifiers
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
# record_map — topological grouping
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

    group_key: (kind, payload) → group name. Supports hierarchy via '/'.
    sort_groups: how to order groups — "alpha", "count", or "recent".

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
        key_parts = key.split("/", 1)
        if len(key_parts) == 2:
            tree.setdefault(key_parts[0], {})[key_parts[1]] = groups[key]
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


# ---------------------------------------------------------------------------
# Concrete gutter functions
# ---------------------------------------------------------------------------


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
    """Gutter by freshness: bright=recent, dim=stale.

    Reads ``_age_days`` from payload (default 0).
    """
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


# ---------------------------------------------------------------------------
# Concrete attention functions
# ---------------------------------------------------------------------------


def attention_staleness(kind: str, payload: dict) -> float:
    """Stale items dim, fresh items bright.

    Reads ``_age_days`` from payload (default 0).
    """
    age_days = payload.get("_age_days", 0)
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.7
    if age_days <= 30:
        return 0.3
    return 0.1


def attention_novelty(kind: str, payload: dict) -> float:
    """First occurrences highlight, repeated events dim.

    Reads ``occurrences`` or ``_count`` from payload (default 1).
    """
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
    """Score-based attention for search results.

    Reads ``_relevance`` from payload (default 0.5).
    """
    return payload.get("_relevance", 0.5)
