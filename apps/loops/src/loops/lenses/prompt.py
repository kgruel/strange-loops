"""Prompt lenses — render fold/stream data for system prompts.

Optimized for LLM consumption: markdown sections, no truncation, no ANSI,
no zoom levels. Always renders the same shape regardless of context.

The identity-aware prompt lens composes narrative from fold data rather than
dumping schema. Self-knowledge reads as orientation, not configuration.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


# ---------------------------------------------------------------------------
# Identity-aware sections — rendered as narrative
# ---------------------------------------------------------------------------

_IDENTITY_KINDS = {"self", "principle", "observation", "intention", "decision"}
_RESOLVED_STATUSES = {"resolved", "completed", "done"}


def _is_identity_vertex(data: FoldState) -> bool:
    """True if this looks like an identity vertex (majority identity kinds)."""
    if not data.sections:
        return False
    identity_count = sum(1 for s in data.sections if s.kind in _IDENTITY_KINDS)
    # Require at least one identity kind (avoids false positive when
    # a single non-identity section like 'task' is queried alone)
    return identity_count > 0 and identity_count >= len(data.sections) // 2


def _render_self_narrative(section: FoldSection) -> list[str]:
    """Compose self entries into orienting narrative paragraphs."""
    if not section.items:
        return []

    lines: list[str] = []

    # Core identity — name and role first, then the rest as characterization
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

    # Remaining self entries as characterization
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


def _render_principles(section: FoldSection) -> list[str]:
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


def _render_observations(section: FoldSection, *, max_items: int = 5) -> list[str]:
    """Render most recent observations. Attention budget: not everything."""
    if not section.items:
        return []

    # Sort by recency, take most recent
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


def _render_intentions(section: FoldSection) -> list[str]:
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


def _render_identity_decisions(section: FoldSection, *, max_items: int = 5) -> list[str]:
    """Render most recent identity decisions. Rest available via drill-down."""
    if not section.items:
        return []

    # Most recent first
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
# Fold prompt lens (identity-aware)
# ---------------------------------------------------------------------------

def prompt_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render fold data as a system prompt fragment.

    For identity vertices: composes narrative from fold sections.
    For other vertices: structured schema (original behavior).
    """
    populated = [s for s in data.sections if s.items]
    if not populated:
        return Block.text("(empty)", Style())

    if _is_identity_vertex(data):
        return _identity_prompt(populated)
    return _schema_prompt(populated)


def _identity_prompt(sections: list[FoldSection]) -> Block:
    """Narrative identity prompt — orients rather than configures."""
    plain = Style()
    all_lines: list[str] = []

    # Render identity sections in a deliberate order
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
    # Session/handoff: full render (it's the handoff content)
    # Tasks: show open items (they're actionable)
    # Everything else: count + most recent, rest summarized
    non_identity = [s for s in sections if s.kind not in _IDENTITY_KINDS]
    if non_identity:
        all_lines.extend(_render_project_compressed(non_identity))

    # Strip trailing blank lines
    while all_lines and not all_lines[-1].strip():
        all_lines.pop()

    rows = [Block.text(line, plain) for line in all_lines]
    return join_vertical(*rows) if rows else Block.text("(empty)", plain)


# ---------------------------------------------------------------------------
# Compressed project sections (for combined identity+project prompts)
# ---------------------------------------------------------------------------

_HANDOFF_KINDS = {"session", "handoff"}
# Kinds that get full rendering in prompt (actionable or orientation)
_ACTIONABLE_KINDS = {"task", "session", "handoff"}
# Kinds to skip entirely in prompt (available via stream if needed)
_SKIP_KINDS = {"log", "change"}
# Max items to show before summarizing
_PROMPT_ITEM_CAP = 3
# Cap for _schema_prompt sections (non-identity vertices)
_SCHEMA_ITEM_CAP = 10


def _render_project_compressed(sections: list["FoldSection"]) -> list[str]:
    """Render non-identity sections compressed for orientation.

    Priority: session/handoff (full), tasks (open items), threads (open names),
    decisions/other (count + recent few). Changes and log skipped.
    """
    lines: list[str] = []

    section_map = {s.kind: s for s in sections}

    # 1. Session/handoff — full render, this is the handoff content
    for kind in ("session", "handoff"):
        if kind in section_map:
            lines.extend(_render_session(section_map[kind]))

    # 2. Tasks — show open items (they're actionable)
    if "task" in section_map:
        active = [
            i for i in section_map["task"].items
            if i.payload.get("status") not in _RESOLVED_STATUSES
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
            if i.payload.get("status") not in _RESOLVED_STATUSES
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
        if s.kind in _ACTIONABLE_KINDS | _HANDOFF_KINDS | _SKIP_KINDS | {"thread"}:
            continue
        if s.kind in _IDENTITY_KINDS:
            continue
        active = [
            i for i in s.items
            if i.payload.get("status") not in _RESOLVED_STATUSES
        ]
        if active:
            lines.append(f"**{s.kind}**: {len(active)} active ({len(s.items)} total)")

    return lines


def _render_session(section: FoldSection) -> list[str]:
    """Render session as handoff content — message and produced artifacts.

    Handles two session shapes:
    - Project sessions: name + status + message (handoff content)
    - Identity sessions: trigger + context (operational, e.g. daemon wakes)

    Uses generic label/body helpers as fallback so unknown shapes never
    produce ``?: ?``.
    """
    lines: list[str] = []
    for item in section.items:
        status = item.payload.get("status", "")
        message = item.payload.get("message", "")
        produced = item.payload.get("produced", [])

        if status in _RESOLVED_STATUSES and message:
            # Resolved session IS the handoff — render the message as content
            lines.append("## HANDOFF")
            lines.append(f"  {message}")
            if produced:
                lines.append(f"  produced: {', '.join(produced)}")
        else:
            # Open/active session — use generic label extraction
            label = _label(item, section.key_field)
            body = _body(item)
            lines.append("## SESSION")
            if body:
                lines.append(f"  {label}: {body}")
            else:
                lines.append(f"  {label}")

    return lines


def _schema_prompt(sections: list[FoldSection]) -> Block:
    """Structured schema prompt — original behavior for non-identity vertices.

    Filters out resolved/completed items — the prompt lens shows what's
    active, not what's done. Exception: session/handoff kinds get custom
    rendering (resolved state IS the handoff content).

    Attention budget: skip log/change, cap large sections to most recent items.
    """
    rows: list[Block] = []
    plain = Style()

    for s in sections:
        # Session/handoff: custom rendering
        if s.kind in _HANDOFF_KINDS:
            for line in _render_session(s):
                rows.append(Block.text(line, plain))
            continue

        # Skip noisy kinds — available via stream if needed
        if s.kind in _SKIP_KINDS:
            continue

        # Other kinds: filter resolved items
        items = [
            item for item in s.items
            if item.payload.get("status") not in _RESOLVED_STATUSES
        ]
        if not items:
            continue

        # Split delegated items out
        mine = [i for i in items if not i.payload.get("delegate")]
        delegated = [i for i in items if i.payload.get("delegate")]

        # Cap large sections to most recent items
        remaining = 0
        if len(mine) > _SCHEMA_ITEM_CAP:
            sorted_items = sorted(mine, key=lambda i: i.ts or 0, reverse=True)
            remaining = len(mine) - _SCHEMA_ITEM_CAP
            mine = sorted_items[:_SCHEMA_ITEM_CAP]

        if not mine and not delegated:
            continue

        if rows:
            rows.append(Block.text("", plain))

        rows.append(Block.text(f"## {s.kind.upper()}", plain))

        for item in mine:
            label = _label(item, s.key_field)
            body = _body(item)
            if body:
                rows.append(Block.text(f"  {label}: {body}", plain))
            else:
                rows.append(Block.text(f"  {label}", plain))

        if remaining > 0:
            rows.append(Block.text(f"  ({remaining} more in store)", plain))

        # Delegated items: grouped summary
        if delegated:
            by_kind: dict[str, list[str]] = {}
            for item in delegated:
                d = item.payload["delegate"]
                by_kind.setdefault(d, []).append(_label(item, s.key_field))
            for d_kind, d_names in by_kind.items():
                rows.append(
                    Block.text(f"  *delegate {d_kind}*: {', '.join(d_names)}", plain)
                )

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Stream prompt lens (unchanged)
# ---------------------------------------------------------------------------

def stream_prompt_view(data: dict[str, Any] | list[dict[str, Any]], zoom: Zoom, width: int) -> Block:
    """Render stream facts as system prompt content.

    Strips timestamps, date headers, and kind tags. Emits the full message
    of each fact — most recent first. For single-fact use cases (handoff),
    this produces just the message text.
    """
    if isinstance(data, dict):
        facts = data.get("facts", [])
        fold_meta = data.get("fold_meta", {})
    else:
        facts = data
        fold_meta = {}

    if not facts:
        return Block.text("(empty)", Style())

    plain = Style()
    rows: list[Block] = []

    for f in facts:
        payload = f["payload"]
        key_field = fold_meta.get(f["kind"], {}).get("key_field")
        label = _find_stream_label(payload, key_field)
        body = _body_from_payload(payload, label)
        if body:
            rows.append(Block.text(f"{label}: {body}", plain))
        else:
            rows.append(Block.text(label, plain))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_LABEL_FIELDS = ("topic", "name", "title", "trigger", "summary", "message")


def _label(item: FoldItem, key_field: str | None) -> str:
    """Extract primary label from a FoldItem."""
    candidates = (key_field,) + _LABEL_FIELDS if key_field else _LABEL_FIELDS
    for field in candidates:
        if field and item.payload.get(field):
            return str(item.payload[field])
    for k, v in item.payload.items():
        if v and k != "weight":
            return f"{k}: {v}"
    return "?"


def _body(item: FoldItem) -> str:
    """Find the body text of a FoldItem — first non-label, non-metadata field."""
    return _body_from_payload(item.payload, _label(item, None))


def _body_from_payload(payload: dict, used_label: str) -> str:
    """Find first non-label field value from a payload dict."""
    skip = {"weight"}  # metadata fields that aren't body content
    for k, v in payload.items():
        if not v:
            continue
        if str(v) == used_label:
            continue
        if k in skip:
            continue
        return str(v)
    return ""


def _find_item(items: tuple[FoldItem, ...], name_value: str) -> FoldItem | None:
    """Find an item by its name/key field value."""
    for item in items:
        if item.payload.get("name") == name_value:
            return item
    return None


def _find_stream_label(payload: dict, key_field: str | None) -> str:
    """Extract primary label from a stream fact payload."""
    candidates = (key_field,) + _LABEL_FIELDS if key_field else _LABEL_FIELDS
    for field in candidates:
        if field and payload.get(field):
            return str(payload[field])
    for k, v in payload.items():
        if v:
            return str(v)
    return ""
