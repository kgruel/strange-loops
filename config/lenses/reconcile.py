"""Reconcile lens — does the store match reality?

Groups threads and tasks by attention-need, not by kind:
  THIS SESSION:   items modified since session open — probably accurate
  NEEDS REVIEW:   open items not touched this session — stale candidates
  RESOLVED:       completed/resolved/parked — de-emphasized

Decisions appear in THIS SESSION as confirmation only (decisions don't go stale).

Session boundary detected from the session fold section (most recent status=open).

Zoom levels:
- MINIMAL: counts per group ("2 this session · 24 need review (3 stale) · 14 resolved")
- SUMMARY: names + recency tags per group. Resolved as count only.
- DETAILED: + message snippets, observer
- FULL: + full payloads, timestamps
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

from loops.lenses._helpers import (
    RESOLVED_STATUSES,
    label as _helpers_label,
    body as _helpers_body,
)

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLOSED = frozenset(RESOLVED_STATUSES | {"dissolved", "shipped", "parked"})
_LABEL_FIELDS = ("topic", "name", "title", "summary")
_BODY_SKIP = frozenset({"status", "priority", "weight"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _label(item: FoldItem, key_field: str | None) -> str:
    return _helpers_label(item, key_field, label_fields=_LABEL_FIELDS)


def _body(item: FoldItem, key_field: str | None = None) -> str:
    return _helpers_body(item, key_field, skip=_BODY_SKIP,
                         label_fields=_LABEL_FIELDS)


def _now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def _recency_tag(ts: float | None, now: float) -> str:
    """Human-readable relative time tag."""
    if ts is None:
        return "(unknown)"
    delta = now - ts
    if delta < 300:       # 5 min
        return "(now)"
    if delta < 3600:      # 1 hour
        return f"({int(delta / 60)}m)"
    if delta < 86400:     # 1 day
        return f"({int(delta / 3600)}h)"
    days = int(delta / 86400)
    if days <= 7:
        return f"({days}d)"
    return "(stale)"


def _session_start_ts(data: FoldState) -> float | None:
    """Find the most recent session-open timestamp from fold state."""
    for section in data.sections:
        if section.kind != "session":
            continue
        # Session items are keyed by name. Find any with status=open.
        # Take the most recent one.
        best_ts = None
        for item in section.items:
            if item.payload.get("status") == "open" and item.ts is not None:
                if best_ts is None or item.ts > best_ts:
                    best_ts = item.ts
        return best_ts
    return None


def _is_resolved(item: FoldItem) -> bool:
    status = str(item.payload.get("status", "")).lower()
    return status in _CLOSED


def _status_tag(item: FoldItem) -> str:
    status = item.payload.get("status", "")
    if status and status not in ("open",):
        return f" [{status}]"
    return ""


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify_items(data: FoldState, session_ts: float | None):
    """Classify all thread/task items into three groups.

    Returns (this_session, needs_review, resolved) — each a list of
    (item, key_field, section_kind) tuples.

    Also returns decisions_this_session as a separate list.
    """
    this_session: list[tuple[FoldItem, str | None, str]] = []
    needs_review: list[tuple[FoldItem, str | None, str]] = []
    resolved: list[tuple[FoldItem, str | None, str]] = []
    decisions_this_session: list[tuple[FoldItem, str | None]] = []

    for section in data.sections:
        if section.kind == "decision":
            # Decisions only appear in THIS SESSION
            if session_ts is not None:
                for item in section.items:
                    if item.ts is not None and item.ts >= session_ts:
                        decisions_this_session.append((item, section.key_field))
            continue

        if section.kind not in ("thread", "task"):
            continue

        for item in section.items:
            if _is_resolved(item):
                resolved.append((item, section.key_field, section.kind))
            elif session_ts is not None and item.ts is not None and item.ts >= session_ts:
                this_session.append((item, section.key_field, section.kind))
            else:
                needs_review.append((item, section.key_field, section.kind))

    # Sort needs_review by recency (oldest first — most stale at top for reconciliation)
    needs_review.sort(key=lambda x: x[0].ts or 0)

    # Sort this_session by recency (newest first)
    this_session.sort(key=lambda x: x[0].ts or 0, reverse=True)

    return this_session, needs_review, resolved, decisions_this_session


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fold_view(
    data: FoldState,
    zoom: Zoom,
    width: int | None,
    **kwargs,
) -> Block:
    """Render reconciliation view at the given zoom level."""
    now = _now()
    session_ts = _session_start_ts(data)
    this_session, needs_review, resolved, decisions = _classify_items(
        data, session_ts,
    )

    total = len(this_session) + len(needs_review) + len(resolved)
    if total == 0 and not decisions:
        return Block.text("(nothing tracked)", Style(dim=True), width=width)

    # Count stale items (>7 days old)
    stale_count = sum(
        1 for item, _, _ in needs_review
        if item.ts is not None and (now - item.ts) > 7 * 86400
    )

    if zoom <= Zoom.MINIMAL:
        return _minimal(this_session, needs_review, resolved, decisions,
                        stale_count, width)

    return _expanded(this_session, needs_review, resolved, decisions,
                     stale_count, now, zoom, width)


# ---------------------------------------------------------------------------
# MINIMAL
# ---------------------------------------------------------------------------

def _minimal(this_session, needs_review, resolved, decisions,
             stale_count, width):
    parts = []
    n_session = len(this_session) + len(decisions)
    if n_session:
        parts.append(f"{n_session} this session")
    if needs_review:
        tag = f" ({stale_count} stale)" if stale_count else ""
        parts.append(f"{len(needs_review)} need review{tag}")
    if resolved:
        parts.append(f"{len(resolved)} resolved")
    return Block.text(" · ".join(parts), Style(), width=width)


# ---------------------------------------------------------------------------
# SUMMARY / DETAILED / FULL
# ---------------------------------------------------------------------------

def _expanded(this_session, needs_review, resolved, decisions,
              stale_count, now, zoom, width):
    rows: list[Block] = []
    plain = Style()
    dim = Style(dim=True)
    bold = Style(bold=True)
    accent = Style(bold=True)

    # --- THIS SESSION ---
    session_items = len(this_session) + len(decisions)
    if session_items > 0:
        rows.append(Block.text(f"This session ({session_items})", accent, width=width))

        for item, key_field, kind in this_session:
            _render_item(rows, item, key_field, kind, now, zoom, width,
                         plain, dim)

        for item, key_field in decisions:
            _render_item(rows, item, key_field, "decision", now, zoom, width,
                         plain, dim)

    # --- NEEDS REVIEW ---
    if needs_review:
        if rows:
            rows.append(Block.text("", plain, width=width))

        stale_tag = f" — {stale_count} stale" if stale_count else ""
        rows.append(Block.text(
            f"Needs review ({len(needs_review)}{stale_tag})", bold, width=width,
        ))

        for item, key_field, kind in needs_review:
            _render_item(rows, item, key_field, kind, now, zoom, width,
                         plain, dim)

    # --- RESOLVED ---
    if resolved:
        if rows:
            rows.append(Block.text("", plain, width=width))

        if zoom <= Zoom.SUMMARY:
            rows.append(Block.text(
                f"Resolved ({len(resolved)})", dim, width=width,
            ))
        else:
            rows.append(Block.text(
                f"Resolved ({len(resolved)})", dim, width=width,
            ))
            for item, key_field, kind in resolved:
                name = _label(item, key_field)
                status = item.payload.get("status", "resolved")
                rows.append(Block.text(
                    f"  {name} [{status}]", dim, width=width,
                ))

    return join_vertical(*rows)


def _render_item(rows, item, key_field, kind, now, zoom, width,
                 plain, dim):
    """Render a single item at the appropriate zoom level."""
    name = _label(item, key_field)
    tag = _recency_tag(item.ts, now)
    status = _status_tag(item)
    kind_prefix = f"{kind}: " if kind in ("task",) else ""

    if zoom >= Zoom.SUMMARY:
        body_text = _body(item, key_field)
        if body_text and zoom >= Zoom.DETAILED:
            snippet = body_text[:140] + "…" if len(body_text) > 140 else body_text
            rows.append(Block.text(
                f"  {kind_prefix}{name}{status} {tag}", plain, width=width,
            ))
            rows.append(Block.text(f"    {snippet}", dim, width=width))
        elif body_text and len(body_text) <= 80:
            rows.append(Block.text(
                f"  {kind_prefix}{name}{status} {tag}: {body_text}", plain, width=width,
            ))
        else:
            rows.append(Block.text(
                f"  {kind_prefix}{name}{status} {tag}", plain, width=width,
            ))

    # FULL: observer + timestamp
    if zoom >= Zoom.FULL:
        meta_parts = []
        if item.observer:
            meta_parts.append(f"observer: {item.observer}")
        if item.ts:
            dt = datetime.fromtimestamp(item.ts, tz=timezone.utc)
            meta_parts.append(f"ts: {dt:%Y-%m-%d %H:%M}")
        if meta_parts:
            rows.append(Block.text(f"    {', '.join(meta_parts)}", dim, width=width))
