"""Identity prompt lens — narrative rendering for identity vertices.

Composes self-knowledge into orienting narrative rather than dumping schema.
Self, principles, observations, intentions, decisions — rendered in
deliberate order for LLM consumption.

Extracted from the built-in prompt lens. Declared in identity.vertex:
  lens { fold "identity_prompt" }
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

from loops.lenses._helpers import (
    RESOLVED_STATUSES,
    body as _body,
    find_item as _find_item,
    label as _label,
    render_session as _render_session,
)

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


_IDENTITY_KINDS = {"self", "principle", "observation", "intention", "decision"}
_SESSION_KINDS = {"session"}
_ACTIONABLE_KINDS = {"task", "session"}
_SKIP_KINDS = {"log", "change"}
_PROMPT_ITEM_CAP = 3


def fold_view(data: "FoldState", zoom: Zoom, width: int | None, **kwargs) -> Block:
    """Render identity fold as narrative system prompt."""
    populated = [s for s in data.sections if s.items]
    if not populated:
        return Block.text("(empty)", Style())

    return _identity_prompt(populated)


def _identity_prompt(sections: list["FoldSection"]) -> Block:
    """Narrative identity prompt — orients rather than configures."""
    plain = Style()
    all_lines: list[str] = []

    section_map = {s.kind: s for s in sections}

    # 1. Self — who you are
    if "self" in section_map:
        all_lines.extend(_render_self_narrative(section_map["self"]))

    # 2. Principles and preferences — what you hold
    if "principle" in section_map:
        all_lines.extend(_render_principles(section_map["principle"]))

    # 3. Observations — what you've noticed
    if "observation" in section_map:
        all_lines.extend(_render_observations(section_map["observation"]))

    # 4. Intentions — what you're watching for
    if "intention" in section_map:
        all_lines.extend(_render_intentions(section_map["intention"]))

    # 5. Identity decisions — resolved working positions
    if "decision" in section_map:
        all_lines.extend(_render_identity_decisions(section_map["decision"]))

    # 6. Non-identity sections — compressed for orientation
    non_identity = [s for s in sections if s.kind not in _IDENTITY_KINDS]
    if non_identity:
        all_lines.extend(_render_project_compressed(non_identity))

    # Strip trailing blank lines
    while all_lines and not all_lines[-1].strip():
        all_lines.pop()

    rows = [Block.text(line, plain) for line in all_lines]
    return join_vertical(*rows) if rows else Block.text("(empty)", plain)


# ---------------------------------------------------------------------------
# Identity section renderers
# ---------------------------------------------------------------------------

def _render_self_narrative(section: "FoldSection") -> list[str]:
    """Compose self entries into orienting narrative paragraphs."""
    if not section.items:
        return []

    lines: list[str] = []

    name_item = _find_item(section.items, "name")
    role_item = _find_item(section.items, "role")

    if name_item or role_item:
        core_parts = []
        if name_item:
            core_parts.append(_body(name_item))
        if role_item:
            core_parts.append(_body(role_item))
        lines.append(" ".join(core_parts))
        lines.append("")

    shown = {"name", "role"}
    remaining = [i for i in section.items if _label(i, section.key_field) not in shown]
    if remaining:
        for item in remaining:
            label = _label(item, section.key_field)
            body = _body(item)
            if body:
                lines.append(f"**{label}**: {body}")
        lines.append("")

    return lines


def _render_principles(section: "FoldSection") -> list[str]:
    """Render principles with weight distinction."""
    if not section.items:
        return []

    strong = []
    preferences = []
    for item in section.items:
        weight = item.payload.get("weight", "principle")
        if weight == "preference":
            preferences.append(item)
        else:
            strong.append(item)

    lines: list[str] = []

    if strong:
        lines.append("**Principles** (load-bearing — these constrain decisions):")
        for item in strong:
            label = _label(item, section.key_field)
            body = _body(item)
            lines.append(f"- **{label}**: {body}" if body else f"- **{label}**")
        lines.append("")

    if preferences:
        lines.append("**Preferences** (tendencies — these shape defaults, can be overridden):")
        for item in preferences:
            label = _label(item, section.key_field)
            body = _body(item)
            lines.append(f"- **{label}**: {body}" if body else f"- **{label}**")
        lines.append("")

    return lines


def _render_observations(section: "FoldSection", *, max_items: int = 5) -> list[str]:
    """Render most recent observations. Attention budget: not everything."""
    if not section.items:
        return []

    sorted_items = sorted(section.items, key=lambda i: i.ts or 0, reverse=True)
    shown = sorted_items[:max_items]
    remaining = len(sorted_items) - len(shown)

    lines: list[str] = ["**Recent observations**:"]
    for item in shown:
        label = _label(item, section.key_field)
        body = _body(item)
        lines.append(f"- **{label}**: {body}" if body else f"- **{label}**")

    if remaining > 0:
        lines.append(f"- *({remaining} more in store)*")
    lines.append("")
    return lines


def _render_intentions(section: "FoldSection") -> list[str]:
    """Render intentions as open questions / things to watch for."""
    if not section.items:
        return []

    lines: list[str] = ["**Watching for**:"]
    for item in section.items:
        trigger = _label(item, section.key_field)
        body = _body(item)
        lines.append(f"- *{trigger}*: {body}" if body else f"- *{trigger}*")
    lines.append("")
    return lines


def _render_identity_decisions(section: "FoldSection", *, max_items: int = 5) -> list[str]:
    """Render most recent identity decisions. Rest available via drill-down."""
    if not section.items:
        return []

    sorted_items = sorted(section.items, key=lambda i: i.ts or 0, reverse=True)
    shown = sorted_items[:max_items]
    remaining = len(sorted_items) - len(shown)

    lines: list[str] = ["**Recent working decisions**:"]
    for item in shown:
        label = _label(item, section.key_field)
        body = _body(item)
        lines.append(f"- **{label}**: {body}" if body else f"- **{label}**")

    if remaining > 0:
        lines.append(f"- *({remaining} more in store)*")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Compressed project sections (for non-identity kinds in identity context)
# ---------------------------------------------------------------------------

def _render_project_compressed(sections: list["FoldSection"]) -> list[str]:
    """Render non-identity sections compressed for orientation."""
    lines: list[str] = []

    section_map = {s.kind: s for s in sections}

    # 1. Session — active sessions
    if "session" in section_map:
        lines.extend(_render_session(section_map["session"]))

    # 2. Tasks — show open items
    if "task" in section_map:
        active = [
            i for i in section_map["task"].items
            if i.payload.get("status") not in RESOLVED_STATUSES
        ]
        if active:
            lines.append("")
            lines.append("## Open Tasks")
            for item in active:
                label = _label(item, section_map["task"].key_field)
                body = _body(item)
                priority = item.payload.get("priority", "")
                pri_tag = f" [{priority}]" if priority else ""
                if body:
                    lines.append(f"  {label}{pri_tag}: {body}")
                else:
                    lines.append(f"  {label}{pri_tag}")

    # 3. Threads — open names, split by delegation
    if "thread" in section_map:
        active = [
            i for i in section_map["thread"].items
            if i.payload.get("status") not in RESOLVED_STATUSES
        ]
        mine = [i for i in active if not i.payload.get("delegate")]
        delegated = [i for i in active if i.payload.get("delegate")]
        kf = section_map["thread"].key_field
        if mine:
            lines.append("")
            names = [_label(i, kf) for i in mine]
            if len(names) <= _PROMPT_ITEM_CAP:
                lines.append(f"**Open threads**: {', '.join(names)}")
            else:
                shown = names[:_PROMPT_ITEM_CAP]
                lines.append(
                    f"**Open threads**: {', '.join(shown)} "
                    f"(+{len(names) - _PROMPT_ITEM_CAP} more)"
                )
        if delegated:
            by_kind: dict[str, list[str]] = {}
            for i in delegated:
                d = i.payload["delegate"]
                by_kind.setdefault(d, []).append(_label(i, kf))
            for kind, names in by_kind.items():
                lines.append(
                    f"  *delegate {kind}*: {', '.join(names)}"
                )

    # 4. Everything else — count summary only
    for s in sections:
        if s.kind in _ACTIONABLE_KINDS | _SESSION_KINDS | _SKIP_KINDS | {"thread"}:
            continue
        if s.kind in _IDENTITY_KINDS:
            continue
        active = [
            i for i in s.items
            if i.payload.get("status") not in RESOLVED_STATUSES
        ]
        if active:
            lines.append(f"**{s.kind}**: {len(active)} active ({len(s.items)} total)")

    return lines


