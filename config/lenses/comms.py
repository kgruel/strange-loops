"""Comms lens — unified communications rendering.

Designed for hook consumption: presence-aware, delta-oriented, self-scoping.
Works with the comms combine vertex (discord, native, future sources).

Lifecycle model — three states per message:
  NEW:       message timestamp > observer's last check (never delivered)
  DELIVERED: message timestamp <= last check, no ack (hook surfaced it)
  HANDLED:   ack fact exists with ref=<message_id> (suppressed from view)

Check facts (kind=check, fold by name) mark when the hook last polled.
Ack facts (kind=ack, fold by ref) mark individual messages as handled.
Messages persist in hook output until explicitly acked.

Fold view:
  MINIMAL: delta line — "3 unhandled (1 new, 2 delivered)"
  SUMMARY: unhandled messages with author + content + ack command
  DETAILED: all unhandled with timestamps, state markers
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
# Check cursor + ack extraction
# ---------------------------------------------------------------------------

def _extract_all_checks(data: "FoldState") -> dict[str, float]:
    """Get last check timestamps for all observers.

    Check facts fold by name — each observer has one entry with its most
    recent check timestamp. Used for both self-cursor and presence detection.
    """
    checks: dict[str, float] = {}
    for section in data.sections:
        if section.kind != "check":
            continue
        for item in section.items:
            name = item.payload.get("name", "")
            if name and item.ts:
                checks[name] = float(item.ts)
    return checks


def _extract_acked_refs(data: "FoldState") -> set[str]:
    """Collect all message IDs that have been acked.

    Ack facts fold by ref — each ref is a message ULID that has been handled.
    """
    acked: set[str] = set()
    for section in data.sections:
        if section.kind != "ack":
            continue
        for item in section.items:
            ref = item.payload.get("ref", "")
            if ref:
                acked.add(ref)
    return acked


# ---------------------------------------------------------------------------
# Fold lens — collapsed comms state
# ---------------------------------------------------------------------------

def fold_view(data: "FoldState", zoom: Zoom, width: int | None, **kwargs) -> Block:
    """Render comms fold as lifecycle-aware status.

    Three states: NEW (never delivered), DELIVERED (hook surfaced, unacked),
    HANDLED (acked, suppressed). Only unhandled messages shown.

    MINIMAL: delta line — "3 unhandled (1 new, 2 delivered)"
    SUMMARY: unhandled messages with author + content + ack command
    DETAILED: all unhandled with timestamps, state markers
    FULL: full content, no truncation, all metadata
    """
    plain = Style()
    self_obs = _self_observer()
    all_checks = _extract_all_checks(data)
    last_check = all_checks.get(self_obs, 0.0) if self_obs else 0.0
    acked_refs = _extract_acked_refs(data)

    # Collect all message items across sections (skip operational sections)
    messages: list[dict[str, Any]] = []
    for section in data.sections:
        if section.kind in ("check", "ack"):
            continue
        for item in section.items:
            content = _extract_content(item.payload)
            if not content:
                continue  # skip operational/status facts with no message body
            # Skip handled messages
            msg_id = item.id or ""
            if msg_id and msg_id in acked_refs:
                continue
            author = _extract_author(item.payload)
            # Fall back to fact observer when payload has no author
            if author == "unknown" and item.observer:
                author = item.observer
            # Scope out self
            if self_obs and author == self_obs:
                continue
            ts = float(item.ts) if item.ts else 0.0
            # Three states: new (never delivered), delivered (surfaced but unacked)
            if ts > last_check:
                state = "new"
            else:
                state = "delivered"
            messages.append({
                "author": author,
                "content": _extract_content(item.payload),
                "channel": _extract_channel(item.payload),
                "ts": ts,
                "id": msg_id,
                "observer": item.observer,
                "state": state,
            })

    # Sort by timestamp, most recent first
    messages.sort(key=lambda m: m.get("ts") or 0, reverse=True)

    # MINIMAL always renders — shows presence even without messages
    if zoom <= Zoom.MINIMAL:
        return _render_minimal(messages, plain, all_checks, self_obs)

    if not messages:
        return Block.text("(no messages)", plain)

    if zoom <= Zoom.SUMMARY:
        return _render_summary(messages, plain, width,
                               max_items=10)

    if zoom <= Zoom.DETAILED:
        return _render_summary(messages, plain, width, max_items=50,
                               show_time=True, show_ack=True)

    return _render_summary(messages, plain, width, max_items=len(messages),
                           show_time=True, full=True, show_ack=True)


_ONLINE_THRESHOLD = 1800  # 30 minutes — recent check = active session


def _render_minimal(
    messages: list[dict],
    plain: Style,
    all_checks: dict[str, float],
    self_obs: str | None,
) -> Block:
    """Status bar: presence + channel counts.

    Format: [3m] online: loops-claude (6m) | native: 3 (1 new) | discord: 5
    Shows freshness, who's active, and unhandled message counts per channel.
    Returns (quiet) when nothing to report — hook filters this out.
    """
    now = time.time()
    parts: list[str] = []

    # Self check freshness — how stale is this view?
    self_check = all_checks.get(self_obs, 0.0) if self_obs else 0.0
    if self_check:
        parts.append(f"[{_relative_time(self_check)}]")

    # Presence — other observers with recent checks
    online: list[str] = []
    for name, ts in sorted(all_checks.items()):
        if name == self_obs:
            continue
        if now - ts < _ONLINE_THRESHOLD:
            online.append(f"{name} ({_relative_time(ts)})")
    if online:
        parts.append(f"online: {', '.join(online)}")

    # Message counts per channel
    channels: dict[str, dict[str, int]] = {}
    for m in messages:
        ch = m["channel"]
        if ch not in channels:
            channels[ch] = {"total": 0, "new": 0}
        channels[ch]["total"] += 1
        if m["state"] == "new":
            channels[ch]["new"] += 1

    ch_parts: list[str] = []
    for ch in sorted(channels):
        c = channels[ch]
        if c["new"] > 0:
            ch_parts.append(f"{ch}: {c['total']} ({c['new']} new)")
        else:
            ch_parts.append(f"{ch}: {c['total']}")

    if ch_parts:
        parts.append(" | ".join(ch_parts))

    if not parts:
        return Block.text("(quiet)", plain)

    # Hint: when messages exist, show how to drill in
    if channels:
        parts.append("→ fold comms --observer all")

    return Block.text(" ".join(parts), plain)


def _render_summary(
    messages: list[dict],
    plain: Style,
    width: int | None,
    max_items: int = 10,
    show_time: bool = False,
    full: bool = False,
    show_ack: bool = False,
) -> Block:
    """Messages with author + content + lifecycle state."""
    rows: list[Block] = []

    shown = messages[:max_items]
    multi_channel = len({x["channel"] for x in messages}) > 1

    for m in shown:
        author = m["author"]
        content = m["content"]
        if not full:
            content = _truncate(content)

        rel = _relative_time(m["ts"]) if m.get("ts") else ""
        time_tag = f" ({rel})" if show_time and rel else ""
        ch_tag = f"[{m['channel']}] " if multi_channel else ""

        # State marker: * = new, ~ = delivered (surfaced but unacked)
        state = m.get("state", "new")
        state_tag = "* " if state == "new" else "~ "

        # Compact: author (time): snippet — or with ack handle at DETAILED+
        if show_ack and m.get("id"):
            rows.append(Block.text(f"{state_tag}{ch_tag}{author}{time_tag}: {content}", plain))
            rows.append(Block.text(f"    ack: loops emit comms/native ack ref={m['id']}", plain))
        else:
            # Status line: author (recency): truncated content
            tag = f" ({rel})" if rel else ""
            rows.append(Block.text(f"{state_tag}{ch_tag}{author}{tag}: {content}", plain))

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

    # Filter out self, check, and ack facts
    filtered: list[dict] = []
    for f in facts:
        if f.get("kind") in ("check", "ack"):
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
