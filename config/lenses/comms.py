"""Comms lens — unified communications rendering.

Designed for hook consumption: presence-aware, delta-oriented, self-scoping.
Works with the comms combine vertex (discord, native, future sources).

Delta model: check facts (kind=check, fold by name) mark when each observer
last checked comms. Messages newer than the observer's last check are "new."
Emit a check fact after reading to advance the cursor.

Fold view:
  MINIMAL: delta line — "discord: 3 new (5m) | native: 1 new (2m)"
  SUMMARY: new messages first, then recent context
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
# Check cursor extraction
# ---------------------------------------------------------------------------

def _extract_last_check(data: "FoldState", observer: str | None) -> float:
    """Find the most recent check timestamp for this observer.

    Check facts fold by name (observer name). The timestamp of the matching
    check item is the cursor — messages after this are "new."
    Returns 0.0 if no check found (everything is new).
    """
    for section in data.sections:
        if section.kind != "check":
            continue
        for item in section.items:
            name = item.payload.get("name", "")
            if name == observer and item.ts:
                return float(item.ts)
    return 0.0


# ---------------------------------------------------------------------------
# Fold lens — collapsed comms state
# ---------------------------------------------------------------------------

def fold_view(data: "FoldState", zoom: Zoom, width: int | None, **kwargs) -> Block:
    """Render comms fold as delta-aware status.

    MINIMAL: delta line — "discord: 3 new (5m) | native: quiet"
    SUMMARY: new messages with author + content
    DETAILED: all messages with timestamps, new marked
    FULL: full content, no truncation
    """
    plain = Style()
    self_obs = _self_observer()
    last_check = _extract_last_check(data, self_obs)

    # Collect all message items across sections (skip non-message sections)
    messages: list[dict[str, Any]] = []
    for section in data.sections:
        if section.kind == "check":
            continue
        for item in section.items:
            content = _extract_content(item.payload)
            if not content:
                continue  # skip operational/status facts with no message body
            author = _extract_author(item.payload)
            # Fall back to fact observer when payload has no author
            if author == "unknown" and item.observer:
                author = item.observer
            # Scope out self
            if self_obs and author == self_obs:
                continue
            ts = float(item.ts) if item.ts else 0.0
            messages.append({
                "author": author,
                "content": _extract_content(item.payload),
                "channel": _extract_channel(item.payload),
                "ts": ts,
                "observer": item.observer,
                "is_new": ts > last_check,
            })

    if not messages:
        return Block.text("(no messages)", plain)

    # Sort by timestamp, most recent first
    messages.sort(key=lambda m: m.get("ts") or 0, reverse=True)

    new_messages = [m for m in messages if m["is_new"]]

    if zoom <= Zoom.MINIMAL:
        return _render_minimal(messages, new_messages, plain)

    if zoom <= Zoom.SUMMARY:
        return _render_summary(new_messages or messages[:5], plain, width,
                               max_items=10, is_delta=bool(new_messages))

    if zoom <= Zoom.DETAILED:
        return _render_summary(messages, plain, width, max_items=50,
                               show_time=True, new_cutoff=last_check)

    return _render_summary(messages, plain, width, max_items=len(messages),
                           show_time=True, full=True, new_cutoff=last_check)


def _render_minimal(
    messages: list[dict],
    new_messages: list[dict],
    plain: Style,
) -> Block:
    """Delta-aware status line per channel."""
    if not new_messages:
        # No new messages — show quiet status with last activity time
        newest_ts = max((m.get("ts") or 0) for m in messages)
        return Block.text(f"(quiet, last activity {_relative_time(newest_ts)} ago)", plain)

    # Group new messages by channel
    channels: dict[str, list[dict]] = {}
    for m in new_messages:
        ch = m["channel"]
        channels.setdefault(ch, []).append(m)

    parts: list[str] = []
    for ch, msgs in channels.items():
        newest_ts = max((m.get("ts") or 0) for m in msgs)
        recency = _relative_time(newest_ts)
        authors = sorted({m["author"] for m in msgs})
        if len(authors) <= 3:
            who = ", ".join(authors)
            part = f"{ch}: {len(msgs)} new from {who} ({recency})"
        else:
            part = f"{ch}: {len(msgs)} new ({recency})"
        parts.append(part)

    return Block.text(" | ".join(parts), plain)


def _render_summary(
    messages: list[dict],
    plain: Style,
    width: int | None,
    max_items: int = 10,
    show_time: bool = False,
    full: bool = False,
    is_delta: bool = False,
    new_cutoff: float = 0.0,
) -> Block:
    """Messages with author + content."""
    rows: list[Block] = []

    shown = messages[:max_items]
    multi_channel = len({x["channel"] for x in messages}) > 1

    for m in shown:
        author = m["author"]
        content = m["content"]
        if not full:
            content = _truncate(content)

        time_tag = f" ({_relative_time(m['ts'])})" if show_time and m.get("ts") else ""
        ch_tag = f"[{m['channel']}] " if multi_channel else ""
        new_tag = "* " if new_cutoff and m.get("ts", 0) > new_cutoff else "  "

        rows.append(Block.text(f"{new_tag}{ch_tag}{author}{time_tag}: {content}", plain))

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

    # Filter out self and check facts
    filtered: list[dict] = []
    for f in facts:
        if f.get("kind") == "check":
            continue
        author = _extract_author(f.get("payload", {}))
        if self_obs and author == self_obs:
            continue
        filtered.append(f)

    if not filtered:
        return Block.text("(no new messages)", plain)

    if zoom <= Zoom.MINIMAL:
        authors: dict[str, int] = {}
        for f in filtered:
            author = _extract_author(f.get("payload", {}))
            authors[author] = authors.get(author, 0) + 1
        parts = [f"{count} from {author}" for author, count in authors.items()]
        return Block.text(f"{len(filtered)} new ({', '.join(parts)})", plain)

    rows: list[Block] = []
    max_items = 10 if zoom <= Zoom.SUMMARY else len(filtered)
    truncate_len = 200 if zoom <= Zoom.SUMMARY else 0

    shown = filtered[:max_items]
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

    remaining = len(filtered) - len(shown)
    if remaining > 0:
        rows.append(Block.text(f"  ({remaining} more)", plain))

    return join_vertical(*rows)
