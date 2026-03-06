"""Comms lens — unified communications rendering.

Designed for hook consumption: presence-aware, delta-oriented, self-scoping.
Works with the comms combine vertex (discord, native, future sources).

Fold view:
  MINIMAL: status line — "discord: 12 new (5m) | native: 2 (1h)"
  SUMMARY: recent messages with author + content
  DETAILED: all messages with timestamps
  FULL: full content, no truncation, all metadata

Stream view:
  Delta since last check — messages with author + content.
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


# ---------------------------------------------------------------------------
# Relative time formatting
# ---------------------------------------------------------------------------

def _relative_time(ts: float | None) -> str:
    """Format timestamp as relative time (e.g., '5m', '2h', '3d')."""
    if ts is None:
        return ""
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return ""
    delta = time.time() - ts
    if delta < 0:
        return "now"
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{int(delta / 60)}m"
    if delta < 86400:
        return f"{int(delta / 3600)}h"
    return f"{int(delta / 86400)}d"


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------

_AUTHOR_FIELDS = ("author", "username", "sender", "from")
_CONTENT_FIELDS = ("content", "message", "text", "body")


def _extract_author(payload: dict[str, Any]) -> str:
    for field in _AUTHOR_FIELDS:
        if payload.get(field):
            return str(payload[field])
    return "unknown"


def _extract_content(payload: dict[str, Any]) -> str:
    for field in _CONTENT_FIELDS:
        if payload.get(field):
            return str(payload[field])
    return ""


def _extract_channel(payload: dict[str, Any]) -> str:
    """Infer channel from payload fields."""
    if payload.get("channel"):
        return str(payload["channel"])
    if payload.get("discord_message_id"):
        return "discord"
    return "native"


def _truncate(text: str, max_len: int = 200) -> str:
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _self_observer() -> str | None:
    """Current observer identity — used to scope out self."""
    return os.environ.get("LOOPS_OBSERVER") or None


# ---------------------------------------------------------------------------
# Fold lens — collapsed comms state
# ---------------------------------------------------------------------------

def fold_view(data: "FoldState", zoom: Zoom, width: int | None, **kwargs) -> Block:
    """Render comms fold as presence + delta status.

    MINIMAL: status line per channel — "discord: 12 new (5m)"
    SUMMARY: recent messages with author + content
    DETAILED: all messages with timestamps
    FULL: full content, no truncation
    """
    plain = Style()
    self_obs = _self_observer()

    # Collect all message items across sections (skip non-message sections)
    messages: list[dict[str, Any]] = []
    for section in data.sections:
        if section.kind == "check":
            continue
        for item in section.items:
            author = _extract_author(item.payload)
            # Fall back to fact observer when payload has no author
            if author == "unknown" and item.observer:
                author = item.observer
            # Scope out self
            if self_obs and author == self_obs:
                continue
            messages.append({
                "author": author,
                "content": _extract_content(item.payload),
                "channel": _extract_channel(item.payload),
                "ts": item.ts,
                "observer": item.observer,
            })

    if not messages:
        return Block.text("(no messages)", plain)

    # Sort by timestamp, most recent first
    messages.sort(key=lambda m: m.get("ts") or 0, reverse=True)

    if zoom <= Zoom.MINIMAL:
        return _render_minimal(messages, plain)

    if zoom <= Zoom.SUMMARY:
        return _render_summary(messages, plain, width, max_items=10)

    if zoom <= Zoom.DETAILED:
        return _render_summary(messages, plain, width, max_items=50, show_time=True)

    return _render_summary(messages, plain, width, max_items=len(messages),
                           show_time=True, full=True)


def _render_minimal(messages: list[dict], plain: Style) -> Block:
    """Status line: channel counts + recency."""
    # Group by channel
    channels: dict[str, list[dict]] = {}
    for m in messages:
        ch = m["channel"]
        channels.setdefault(ch, []).append(m)

    parts: list[str] = []
    for ch, msgs in channels.items():
        newest_ts = max((m.get("ts") or 0) for m in msgs)
        recency = _relative_time(newest_ts)
        # Count unique authors (excluding self)
        authors = {m["author"] for m in msgs}
        if len(authors) <= 3:
            who = ", ".join(sorted(authors))
            part = f"{ch}: {len(msgs)} ({who}, {recency})"
        else:
            part = f"{ch}: {len(msgs)} ({recency})"
        parts.append(part)

    return Block.text(" | ".join(parts), plain)


def _render_summary(
    messages: list[dict],
    plain: Style,
    width: int | None,
    max_items: int = 10,
    show_time: bool = False,
    full: bool = False,
) -> Block:
    """Messages with author + content."""
    rows: list[Block] = []

    shown = messages[:max_items]
    for m in shown:
        author = m["author"]
        content = m["content"]
        if not full:
            content = _truncate(content)

        time_tag = f" ({_relative_time(m['ts'])})" if show_time and m.get("ts") else ""
        ch_tag = f"[{m['channel']}] " if len({x['channel'] for x in messages}) > 1 else ""

        rows.append(Block.text(f"  {ch_tag}{author}{time_tag}: {content}", plain))

    remaining = len(messages) - len(shown)
    if remaining > 0:
        rows.append(Block.text(f"  ({remaining} more)", plain))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Stream lens — time-ordered delta
# ---------------------------------------------------------------------------

def stream_view(
    data: dict[str, Any] | list[dict[str, Any]],
    zoom: Zoom,
    width: int | None,
) -> Block:
    """Render comms stream as delta since last check."""
    plain = Style()
    self_obs = _self_observer()

    if isinstance(data, dict):
        facts = data.get("facts", [])
    else:
        facts = data

    if not facts:
        return Block.text("(no new messages)", plain)

    # Filter out self
    if self_obs:
        facts = [f for f in facts
                 if _extract_author(f.get("payload", {})) != self_obs]

    if not facts:
        return Block.text("(no new messages)", plain)

    if zoom <= Zoom.MINIMAL:
        authors: dict[str, int] = {}
        for f in facts:
            author = _extract_author(f.get("payload", {}))
            authors[author] = authors.get(author, 0) + 1
        parts = [f"{count} from {author}" for author, count in authors.items()]
        return Block.text(f"{len(facts)} new ({', '.join(parts)})", plain)

    rows: list[Block] = []
    max_items = 10 if zoom <= Zoom.SUMMARY else len(facts)
    truncate_len = 200 if zoom <= Zoom.SUMMARY else 0

    shown = facts[:max_items]
    for f in shown:
        payload = f.get("payload", {})
        author = _extract_author(payload)
        content = _extract_content(payload)
        ts = f.get("ts")
        rel = _relative_time(ts)

        if truncate_len:
            content = _truncate(content, truncate_len)

        tag = f" ({rel})" if rel else ""
        rows.append(Block.text(f"  {author}{tag}: {content}", plain))

    remaining = len(facts) - len(shown)
    if remaining > 0:
        rows.append(Block.text(f"  ({remaining} more)", plain))

    return join_vertical(*rows)
