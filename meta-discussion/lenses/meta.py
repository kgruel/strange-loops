"""Meta lens — attention-radius-aware rendering for the meta design space.

Zoom levels interpreted as attention radius:
  MINIMAL  (0): Self only — your open tasks, your active threads
  SUMMARY  (1): Self + orientation — recent decisions, active threads,
                 plus one-liner peer summaries
  DETAILED (2): Everything up a level — full decision content, all threads,
                 peer context visible
  FULL     (3): Complete store — all decisions, all threads, dissolutions,
                 session history

The meta store is a design knowledge base, not an identity vertex.
Priority order: session/handoff (where we left off), recent decisions
(what just landed), active threads (what's being worked on),
dissolutions (what collapsed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

from loops.lenses._helpers import (
    RESOLVED_STATUSES,
    body as _helpers_body,
    label as _helpers_label,
)

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


_META_LABEL_FIELDS = ("topic", "name", "title", "trigger", "concept", "summary")
_META_BODY_SKIP = frozenset(
    {"weight", "status", "produced", "thread", "observer"}
    | set(_META_LABEL_FIELDS)
)


def _label(item: "FoldItem", key_field: str | None) -> str:
    return _helpers_label(item, key_field, label_fields=_META_LABEL_FIELDS)


def _body(item: "FoldItem") -> str:
    return _helpers_body(item, skip=_META_BODY_SKIP,
                         label_fields=_META_LABEL_FIELDS)


def fold_view(data: "FoldState", zoom: Zoom, width: int | None) -> Block:
    """Render meta fold at the given attention radius."""
    sections = {s.kind: s for s in data.sections if s.items}
    if not sections:
        return Block.text("No data yet.", Style())

    lines: list[str] = []

    if zoom == Zoom.MINIMAL:
        lines.extend(_minimal(sections))
    elif zoom == Zoom.SUMMARY:
        lines.extend(_summary(sections))
    elif zoom == Zoom.DETAILED:
        lines.extend(_detailed(sections))
    else:
        lines.extend(_full(sections))

    while lines and not lines[-1].strip():
        lines.pop()

    plain = Style()
    rows = [Block.text(line, plain) for line in lines]
    return join_vertical(*rows) if rows else Block.text("(empty)", plain)


# ---------------------------------------------------------------------------
# MINIMAL — self only
# ---------------------------------------------------------------------------

def _minimal(sections: dict[str, "FoldSection"]) -> list[str]:
    lines: list[str] = []

    # Open tasks (yours)
    if "task" in sections:
        active = [i for i in sections["task"].items
                  if i.payload.get("status") not in RESOLVED_STATUSES]
        if active:
            names = [_label(i, sections["task"].key_field) for i in active]
            lines.append(f"Tasks: {', '.join(names)}")

    # Active thread count
    if "thread" in sections:
        active = [i for i in sections["thread"].items
                  if i.payload.get("status") not in RESOLVED_STATUSES]
        if active:
            lines.append(f"Threads: {len(active)} active")

    # Recent decision count
    if "decision" in sections:
        lines.append(f"Decisions: {len(sections['decision'].items)} total")

    if "dissolution" in sections:
        lines.append(f"Dissolutions: {len(sections['dissolution'].items)}")

    return lines if lines else ["(empty)"]


# ---------------------------------------------------------------------------
# SUMMARY — self + orientation
# ---------------------------------------------------------------------------

def _summary(sections: dict[str, "FoldSection"]) -> list[str]:
    lines: list[str] = []

    # Session/handoff — where we left off
    if "session" in sections:
        lines.extend(_render_session(sections["session"]))

    # Open tasks
    if "task" in sections:
        active = [i for i in sections["task"].items
                  if i.payload.get("status") not in RESOLVED_STATUSES]
        if active:
            lines.append("")
            lines.append("# Open Tasks")
            for item in active:
                label = _label(item, sections["task"].key_field)
                lines.append(f"  {label}: {item.payload.get('status', 'open')}")

    # Recent decisions — last 5, grouped by namespace prefix
    if "decision" in sections:
        sorted_items = sorted(sections["decision"].items,
                              key=lambda i: i.ts or 0, reverse=True)
        recent = sorted_items[:5]
        if recent:
            lines.append("")
            lines.append("# Recent Decisions")
            for item in recent:
                topic = _label(item, sections["decision"].key_field)
                lines.append(f"  {topic}")

        remaining = len(sorted_items) - len(recent)
        if remaining > 0:
            lines.append(f"  ({remaining} more)")

    # Active threads — names only
    if "thread" in sections:
        active = [i for i in sections["thread"].items
                  if i.payload.get("status") not in RESOLVED_STATUSES]
        if active:
            lines.append("")
            names = [_label(i, sections["thread"].key_field) for i in active[:5]]
            remaining = len(active) - len(names)
            lines.append(f"# Active Threads ({len(active)})")
            for n in names:
                lines.append(f"  {n}")
            if remaining > 0:
                lines.append(f"  (+{remaining} more)")

    # Dissolution count
    if "dissolution" in sections:
        lines.append("")
        lines.append(f"Dissolutions: {len(sections['dissolution'].items)} recorded")

    return lines


# ---------------------------------------------------------------------------
# DETAILED — everything up a level
# ---------------------------------------------------------------------------

def _detailed(sections: dict[str, "FoldSection"]) -> list[str]:
    lines: list[str] = []

    # Session/handoff
    if "session" in sections:
        lines.extend(_render_session(sections["session"]))

    # Open tasks with messages
    if "task" in sections:
        active = [i for i in sections["task"].items
                  if i.payload.get("status") not in RESOLVED_STATUSES]
        if active:
            lines.append("")
            lines.append("# Open Tasks")
            for item in active:
                label = _label(item, sections["task"].key_field)
                body = _body(item)
                if body:
                    lines.append(f"  {label}: {body}")
                else:
                    lines.append(f"  {label}")

    # All decisions grouped by namespace
    if "decision" in sections:
        lines.append("")
        lines.append("# Decisions")
        grouped = _group_by_namespace(sections["decision"])
        for ns, items in sorted(grouped.items()):
            lines.append(f"  ## {ns}")
            for item in items:
                topic = _label(item, sections["decision"].key_field)
                short_topic = topic.split("/", 1)[1] if "/" in topic else topic
                body = _body(item)
                if body:
                    lines.append(f"    {short_topic}: {body[:80]}")
                else:
                    lines.append(f"    {short_topic}")

    # All threads with status
    if "thread" in sections:
        active = [i for i in sections["thread"].items
                  if i.payload.get("status") not in RESOLVED_STATUSES]
        resolved = [i for i in sections["thread"].items
                    if i.payload.get("status") in RESOLVED_STATUSES]
        if active:
            lines.append("")
            lines.append(f"# Active Threads ({len(active)})")
            for item in active:
                name = _label(item, sections["thread"].key_field)
                body = _body(item)
                if body:
                    lines.append(f"  {name}: {body[:60]}")
                else:
                    lines.append(f"  {name}")
        if resolved:
            lines.append(f"  ({len(resolved)} resolved)")

    # Dissolutions
    if "dissolution" in sections:
        lines.append("")
        lines.append("# Dissolutions")
        for item in sections["dissolution"].items:
            concept = _label(item, sections["dissolution"].key_field)
            body = _body(item)
            if body:
                lines.append(f"  {concept}: {body[:60]}")
            else:
                lines.append(f"  {concept}")

    return lines


# ---------------------------------------------------------------------------
# FULL — complete store
# ---------------------------------------------------------------------------

def _full(sections: dict[str, "FoldSection"]) -> list[str]:
    lines: list[str] = []

    # Session
    if "session" in sections:
        lines.extend(_render_session(sections["session"]))

    # Tasks
    if "task" in sections:
        lines.append("")
        lines.append("# Tasks")
        for item in sections["task"].items:
            label = _label(item, sections["task"].key_field)
            status = item.payload.get("status", "?")
            body = _body(item)
            if body:
                lines.append(f"  {label} [{status}]: {body}")
            else:
                lines.append(f"  {label} [{status}]")

    # All decisions with full content
    if "decision" in sections:
        lines.append("")
        lines.append("# Decisions")
        grouped = _group_by_namespace(sections["decision"])
        for ns, items in sorted(grouped.items()):
            lines.append(f"  ## {ns}")
            for item in items:
                topic = _label(item, sections["decision"].key_field)
                short_topic = topic.split("/", 1)[1] if "/" in topic else topic
                body = _body(item)
                lines.append(f"    {short_topic}: {body}")

    # All threads with full content
    if "thread" in sections:
        lines.append("")
        lines.append("# Threads")
        for item in sections["thread"].items:
            name = _label(item, sections["thread"].key_field)
            status = item.payload.get("status", "?")
            body = _body(item)
            lines.append(f"  {name} [{status}]: {body}")

    # Dissolutions with full content
    if "dissolution" in sections:
        lines.append("")
        lines.append("# Dissolutions")
        for item in sections["dissolution"].items:
            concept = _label(item, sections["dissolution"].key_field)
            body = _body(item)
            lines.append(f"  {concept}: {body}")

    return lines


# ---------------------------------------------------------------------------
# Session rendering (meta-specific format — uses # headers, not ##)
# ---------------------------------------------------------------------------

def _render_session(section: "FoldSection") -> list[str]:
    lines: list[str] = []
    for item in section.items:
        status = item.payload.get("status", "")
        message = item.payload.get("message", "")
        produced = item.payload.get("produced", [])

        if status in RESOLVED_STATUSES and message:
            lines.append("# Last Session Handoff")
            lines.append(f"  {message}")
            if produced:
                lines.append(f"  produced: {', '.join(produced)}")
        else:
            label = _label(item, section.key_field)
            lines.append(f"# Session: {label} ({status or 'active'})")
    return lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group_by_namespace(section: "FoldSection") -> dict[str, list["FoldItem"]]:
    groups: dict[str, list["FoldItem"]] = {}
    for item in section.items:
        topic = _label(item, section.key_field)
        ns = topic.split("/", 1)[0] if "/" in topic else "(general)"
        groups.setdefault(ns, []).append(item)
    return groups
