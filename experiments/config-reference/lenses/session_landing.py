"""Session landing lens — window-framed view of the accumulated vertex.

The view you get when you land in a session. Composes two shapes:

1. **Window header** — what moved in the most recent tick window
   (density, compression, per-kind deltas). The window IS the attention
   frame: it's what happened since the last boundary fired.

2. **History strip** — compact row per prior window for orientation.
   Replaces the bash-era ``--ticks --since 3d | head -15`` stanza with
   a native render; each row is one TickWindow's identity + delta.

3. **Accumulated, focus-filtered** — the standing threads / tasks /
   decisions in the vertex, with items whose keys appear in the current
   window's ``added_keys`` / ``updated_keys`` marked and pulled to the
   top of their section. Untouched items de-emphasize at SUMMARY zoom.

The third block is the concrete form of the *derived-keys-as-focus-filter*
pattern: the window produces a bounded ``(kind, key)`` set; membership
drives salience marks on the accumulated view. Same shape as ``--refs``
as focus filter.

**Input contract** — this lens declares its own ``fetch`` (see
``design/lens-declares-fetch``). The view function consumes ``LandingData``,
not a bare ``FoldState`` — the ticks composition is part of the lens's
operation, not the caller's.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_horizontal, join_vertical

from loops.lenses._helpers import RESOLVED_STATUSES, label as _label
from loops.lenses.fold import FoldPalette, _default_fold_palette, _recency_tag

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState, TickWindow


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Hook-mechanical kinds — exclude from WINDOW/HISTORY chip strips. These are
# emitted by session lifecycle / observation plumbing rather than by domain
# work. They inflate kind chips and crowd out signal. Note: ``cite`` is *not*
# in here — it's a deliberate attention signal, worth surfacing as activity.
# Total counts (``total_items`` / ``total_facts``) are intentionally NOT
# filtered: the bar reflects raw window shape; the chips reflect what's worth
# attending to.
_HEADER_SKIP_KINDS = frozenset({"session", "log", "change", "message"})

# Header
_BAR_WIDTH = 20            # compression bar characters

# History strip
_HISTORY_CAP = 4           # prior windows to show
_TRIGGER_WIDTH = 18        # column width for boundary trigger (post-strip)

# Body (same semantics as session_start, plus focus-filter boost)
_DECISION_BODY_CAP = 3
_DECISION_GROUP_CAP = 8
_SALIENCE_BODY_THRESHOLD = 2
_PARKED_CAP = 15
_TASK_CAP = 10
_PLAN_CAP = 3              # plans are heavy — few should be in flight
_BODY_LIMIT = 200

def _cap(base: int, zoom: "Zoom") -> int:
    """Scale a section cap by zoom level — depth governs both detail and count.

    -q (MINIMAL): halve the budget — minimal orient.
    default (SUMMARY): base — comfort zone.
    -v (DETAILED): double — expanded view.
    -vv (FULL): effectively unbounded — show all.

    Resolves verbosity-fidelity-review symptom 4 ('-v / -vv expand fact
    detail but don't expand structural truncation'): one knob, two effects,
    both meaning give-me-more. Per rendering/salience-driven-display.
    """
    z = int(zoom)
    if z <= 0:
        return max(1, base // 2)
    if z == 1:
        return base
    if z == 2:
        return base * 2
    return 10000  # FULL/-vv — effectively unbounded


# Focus-filter marks
_MARK_ADDED = "added"
_MARK_UPDATED = "updated"
_MARK_CITED = "cited"
_MARK_STALE = "stale"
_MARK_GLYPH = {
    _MARK_ADDED: "✦",
    _MARK_UPDATED: "◦",
    _MARK_CITED: "⊙",
    _MARK_STALE: "⊘",
}


# ---------------------------------------------------------------------------
# Input shape — declared alongside fetch
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LandingData:
    """Composite input for the landing view.

    ``windows`` is newest-first; index 0 is the landing window (last close →
    now). Empty when the vertex has no ticks yet — the view falls back to
    pure fold rendering.

    ``fold`` is the current accumulated state, fetched with ``retain_facts``
    disabled (the landing view doesn't surface raw facts).

    ``observer`` is the current observer name. Used to strip self-prefixes
    from boundary triggers so single-observer vertices don't display a
    redundant ``<observer>`` column on every history row.

    ``stale_keys`` is the (kind, key) set for open work items not touched
    in >7d. Third instance of derived-keys-as-focus-filter: structurally
    derived from fold + clock; drives ⊘ marks on the accumulated body.
    Clock-derived: same store, different time → different stale_keys.
    Acknowledged in design/stale-as-focus-filter.

    ``cite_keys`` is the set of ref strings carried by cite items emitted
    within the landing window's time range. Fourth instance of
    derived-keys-as-focus-filter: items targeted by cites in the current
    window get the ⊙ "cited" mark. Stored as raw ref strings (kind/key or
    bare) — dual-form matched against item full keys at mark-resolution
    time, mirroring _inbound_count's approach. See
    design/cite-as-partial-information-primitive and
    rendering/salience-driven-display.
    """
    windows: tuple
    fold: "FoldState"
    observer: str = ""
    stale_keys: frozenset[tuple[str, str]] = frozenset()
    cite_keys: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Fetch — lens-declared input contract
# ---------------------------------------------------------------------------

_STALE_THRESHOLD_SECS = 7 * 86400   # 7d — stale-open boundary
_STALE_INACTIVE = RESOLVED_STATUSES | {"parked"}


def fetch(vertex_path: Path, **kwargs) -> LandingData:
    """Compose TickWindow series + FoldState for the landing view.

    Called by the CLI in place of the default fetch when ``--lens
    session_landing`` (or a vertex lens{} declaration) selects this lens.
    Ignores ``retain_facts`` / ``kind`` — the landing view uses the full
    fold, unfiltered.
    """
    from loops.commands.fetch import fetch_fold, fetch_tick_windows

    observer = kwargs.get("observer")
    windows = fetch_tick_windows(vertex_path, since="30d")
    fold = fetch_fold(vertex_path, observer=observer, retain_facts=False)

    # Resolve current observer identity for trigger-prefix stripping.
    # ``observer`` kwarg may be None for unscoped vertices (fold shows all),
    # but the display layer still wants to recognize "me" to strip the
    # redundant self-prefix from boundary triggers. Fall back to identity
    # resolution rather than to "" so single-observer vertices clean up.
    self_id = observer
    if not self_id:
        try:
            from loops.commands.identity import resolve_observer
            self_id = resolve_observer()
        except Exception:
            self_id = ""

    # Compute stale_keys: open work items not touched in >7d.
    # Clock-derived: same store, different time → different result.
    # Structural check (status + ts), not configured per-kind — any kind
    # carrying a status field participates.
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - _STALE_THRESHOLD_SECS
    stale: set[tuple[str, str]] = set()
    for section in fold.sections:
        key_field = section.key_field
        if not key_field:
            continue
        for item in section.items:
            status = item.payload.get("status")
            if not status or status in _STALE_INACTIVE:
                continue
            if item.ts is None or item.ts >= cutoff:
                continue
            key = str(item.payload.get(key_field, ""))
            if not key:
                continue
            stale.add((section.kind, key))

    # Compute cite_keys: refs carried by cite items in the landing window.
    # Stored as raw ref strings (the form they were emitted in). Dual-form
    # matching happens at mark-resolution time (see _compute_marks).
    # Window range: [window.since, window.ts]. Falls back to all-time when
    # no window exists (fresh vertex), which is a no-op since cite_keys is
    # only consulted to mark items.
    cite_keys: set[str] = set()
    landing_window = windows[0] if windows else None
    win_since = landing_window.since if landing_window else None
    win_ts = landing_window.ts if landing_window else None
    for section in fold.sections:
        if section.kind != "cite":
            continue
        for item in section.items:
            if item.ts is None:
                continue
            if win_since is not None and item.ts < win_since:
                continue
            if win_ts is not None and item.ts > win_ts:
                continue
            for ref in item.refs:
                if ref:
                    cite_keys.add(ref)

    return LandingData(
        windows=windows,
        fold=fold,
        observer=self_id or "",
        stale_keys=frozenset(stale),
        cite_keys=frozenset(cite_keys),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fold_view(data: LandingData, zoom: Zoom, width: int | None, **kwargs) -> Block:
    """Render the landing view: window header + history + focus-filtered body."""
    fp = _default_fold_palette()
    windows = data.windows
    fold = data.fold
    observer = data.observer

    blocks: list[Block] = []

    # --- 1. Window header (landing window) ---
    if windows:
        current: "TickWindow" = windows[0]
        blocks.append(_render_window_header(current, observer, fp, width))

    # --- 2. History strip (prior windows) ---
    if len(windows) > 1:
        blocks.append(Block.text("", Style(), width=width))
        blocks.append(_render_history_strip(windows[1:], observer, zoom, fp, width))

    # --- 3. Accumulated body, focus-filtered by window deltas + stale ---
    current_window = windows[0] if windows else None
    marks = _compute_marks(current_window, data.stale_keys, data.cite_keys, fold)
    body = _render_accumulated(fold, marks, zoom, fp, width)
    if body is not None:
        if blocks:
            blocks.append(Block.text("", Style(), width=width))
        blocks.append(body)

    if not blocks:
        return Block.text("(empty)", Style(dim=True), width=width)
    return join_vertical(*blocks)


# ---------------------------------------------------------------------------
# Block 1 — window header
# ---------------------------------------------------------------------------

def _render_window_header(
    window: "TickWindow", observer: str, fp: FoldPalette, width: int | None,
) -> Block:
    """Single window as dashboard: trigger, bar, counts, per-kind chips."""
    rows: list[Block] = [_section_header("WINDOW", fp, width)]

    # Line 1: trigger · recency · duration
    trigger = _compact_trigger(window.boundary_trigger or window.name, observer)
    since_dt = _fmt_ts(window.since) if window.since else "—"
    ts_dt = _fmt_ts(window.ts)
    recency = _recency_tag(window.ts) or ""
    dur = _fmt_duration(window.duration_secs) if window.duration_secs else ""

    header_parts: list[Block] = [
        Block.text("  ", fp.collapse),
        Block.text(trigger, fp.key),
    ]
    if recency:
        header_parts.append(Block.text(f" · {recency}", fp.collapse))
    if dur:
        header_parts.append(Block.text(f" · {dur}", fp.collapse))
    header_parts.append(Block.text(f"  ({since_dt} → {ts_dt})", fp.collapse))
    rows.append(join_horizontal(*header_parts))

    # Line 2: compression bar + totals + deltas
    bar = _compression_bar(window, _BAR_WIDTH)
    parts: list[Block] = [
        Block.text("  ", fp.collapse),
        Block.text(bar, fp.body),
        Block.text(f"  {window.total_items}i / {window.total_facts}f", fp.body),
    ]
    if window.delta_added:
        parts.append(Block.text(f"   +{window.delta_added} new", fp.ref_indicator))
    if window.delta_updated:
        parts.append(Block.text(f"   ↑{window.delta_updated} touched", fp.n_indicator))
    rows.append(join_horizontal(*parts))

    # Line 3: per-kind chips (count ×compression)
    # Filter hook-mechanical kinds — they crowd out signal in the chip strip.
    # Total counts on Line 2 still reflect raw window shape.
    chip_kinds = [
        (k, c) for k, c in window.kind_summary.items()
        if k not in _HEADER_SKIP_KINDS
    ]
    if chip_kinds:
        kinds_sorted = sorted(chip_kinds, key=lambda kv: kv[1], reverse=True)
        chip_parts: list[Block] = [Block.text("  ", fp.collapse)]
        for i, (kind, count) in enumerate(kinds_sorted):
            if i > 0:
                chip_parts.append(Block.text("   ", fp.collapse))
            comp = window.kind_compression.get(kind, 1.0)
            chip_parts.append(Block.text(kind, fp.group_header))
            chip_parts.append(Block.text(f" {count}", fp.key))
            if comp > 1.05:
                chip_parts.append(Block.text(f" ×{comp:.1f}", fp.collapse))
        rows.append(join_horizontal(*chip_parts))

    return join_vertical(*rows)


def _compression_bar(window: "TickWindow", bar_width: int) -> str:
    """Filled/empty bar showing compression ratio (items/facts → fill)."""
    if window.total_facts <= 0:
        return "░" * bar_width
    # Ratio of items to facts: 1.0 = no compression, → 0 = high compression.
    ratio = min(1.0, window.total_items / window.total_facts)
    # Invert: more compression → more filled.
    filled = int(round((1.0 - ratio) * bar_width))
    return "▓" * filled + "░" * (bar_width - filled)


# ---------------------------------------------------------------------------
# Block 2 — history strip
# ---------------------------------------------------------------------------

def _render_history_strip(
    windows: tuple, observer: str, zoom: "Zoom",
    fp: FoldPalette, width: int | None,
) -> Block:
    """Row-per-window for prior ticks. Orientation signal, not decoration."""
    rows: list[Block] = [_section_header("HISTORY", fp, width)]

    shown = windows[:_cap(_HISTORY_CAP, zoom)]
    for w in shown:
        recency = _recency_tag(w.ts) or "—"
        trigger = _compact_trigger(w.boundary_trigger or w.name, observer)
        # Truncate-then-pad so long triggers don't collide with the next column.
        if len(trigger) > _TRIGGER_WIDTH:
            trigger_cell = trigger[: _TRIGGER_WIDTH - 1] + "…"
        else:
            trigger_cell = trigger.ljust(_TRIGGER_WIDTH)
        counts = f"{w.total_items}i/{w.total_facts}f"
        deltas = []
        if w.delta_added:
            deltas.append(f"+{w.delta_added}")
        if w.delta_updated:
            deltas.append(f"↑{w.delta_updated}")
        delta_str = "  ".join(deltas) if deltas else ""

        parts: list[Block] = [
            Block.text(f"  {recency:>10}", fp.collapse),
            Block.text(f"  {trigger_cell}  ", fp.key),
            Block.text(counts, fp.body),
        ]
        if delta_str:
            parts.append(Block.text(f"   {delta_str}", fp.n_indicator))
        rows.append(join_horizontal(*parts))

    remaining = len(windows) - len(shown)
    if remaining > 0:
        rows.append(Block.text(f"  ({remaining} more)", fp.collapse, width=width))
    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Block 3 — accumulated, focus-filtered
# ---------------------------------------------------------------------------

def _render_accumulated(
    data: "FoldState", marks: dict[tuple[str, str], str],
    zoom: Zoom, fp: FoldPalette, width: int | None,
) -> Block | None:
    """Tiered body (tasks, threads, decisions) with focus-filter salience marks."""
    populated = [s for s in data.sections if s.items]
    if not populated:
        return None

    inbound = _compute_inbound_refs(data)
    section_map = {s.kind: s for s in populated}
    blocks: list[Block] = []

    # --- Tier 0: Orchestration in flight (plans) ---
    # Plans are multi-step orchestration substrate (instance #4 of
    # bounded-fact-substrate, peer to thread/task/decision). Surfaced first
    # because an open plan is the strongest "what we're executing now"
    # signal — answers landing's primary question before tasks/threads.
    if "plan" in section_map:
        b = _render_plans(section_map["plan"], marks, zoom, fp, width)
        if b:
            blocks.append(b)

    # --- Tier 1: Working context (tasks) ---
    if "task" in section_map:
        b = _render_tasks(section_map["task"], marks, zoom, fp, width)
        if b:
            if blocks:
                blocks.append(Block.text("", Style(), width=width))
            blocks.append(b)

    # --- Tier 2: Orientation (threads) ---
    if "thread" in section_map:
        b = _render_threads(section_map["thread"], marks, zoom, fp, width)
        if b:
            if blocks:
                blocks.append(Block.text("", Style(), width=width))
            blocks.append(b)

    # --- Tier 3: Knowledge landscape (decisions + other by-folds) ---
    for kind in ("decision", "dissolution", "vision"):
        if kind in section_map:
            b = _render_decisions(
                section_map[kind], kind, marks, inbound, zoom, fp, width,
            )
            if b:
                if blocks:
                    blocks.append(Block.text("", Style(), width=width))
                blocks.append(b)

    return join_vertical(*blocks) if blocks else None


# ---------------------------------------------------------------------------
# Body helpers — tasks / threads / decisions (with focus-filter integration)
# ---------------------------------------------------------------------------

def _render_tasks(
    section: "FoldSection", marks: dict, zoom: "Zoom",
    fp: FoldPalette, width: int | None,
) -> Block | None:
    """Active tasks. Marked items sort first; others follow by recency."""
    inactive = RESOLVED_STATUSES | {"parked"}
    active = [i for i in section.items if i.payload.get("status") not in inactive]
    if not active:
        return None

    sorted_items = sorted(
        active,
        key=lambda i: (
            -_mark_priority(section.kind, i, section.key_field, marks),
            -(i.ts or 0),
        ),
    )
    shown = sorted_items[:_cap(_TASK_CAP, zoom)]
    remaining = len(sorted_items) - len(shown)

    rows: list[Block] = [_section_header("TASK", fp, width)]
    for item in shown:
        rows.append(_item_line(
            item, section.kind, section.key_field, marks, fp, width, indent=2,
        ))

    if remaining > 0:
        rows.append(Block.text(f"  ({remaining} more)", fp.collapse, width=width))
    return join_vertical(*rows)


def _render_plans(
    section: "FoldSection", marks: dict, zoom: "Zoom",
    fp: FoldPalette, width: int | None,
) -> Block | None:
    """Active plans — multi-step orchestration. Heavier than tasks, fewer expected.

    Filter: status not in RESOLVED_STATUSES. Plans use ``drafted`` /
    ``in_progress`` / etc. as pre-completion states; all are surfaced.

    Body shape: plan messages are structured (headline paragraph, then
    FILES TOUCHED, SEQUENCE, OPEN QUESTIONS). Truncate at first paragraph
    break (``\\n\\n``) when present so the headline stands alone — the
    structured sections become visible at -v / DETAILED+ via the default
    fold lens. ``_BODY_LIMIT`` caps single-paragraph bodies as a fallback.
    """
    active = [i for i in section.items if i.payload.get("status") not in RESOLVED_STATUSES]
    if not active:
        return None

    sorted_items = sorted(
        active,
        key=lambda i: (
            -_mark_priority(section.kind, i, section.key_field, marks),
            -(i.ts or 0),
        ),
    )
    shown = sorted_items[:_cap(_PLAN_CAP, zoom)]
    remaining = len(sorted_items) - len(shown)

    rows: list[Block] = [_section_header("PLAN", fp, width)]
    for item in shown:
        lbl = _label(item, section.key_field)
        recency = _recency_tag(item.ts)
        bdy = _item_body(item, section.key_field)
        mark = _item_mark(section.kind, item, section.key_field, marks)
        status = str(item.payload.get("status") or "").strip()

        header_parts: list[Block] = [Block.text("  ", fp.collapse)]
        if mark:
            header_parts.append(Block.text(f"{_MARK_GLYPH[mark]} ", _mark_style(mark, fp)))
        header_parts.append(Block.text(lbl, fp.key))
        if status:
            header_parts.append(Block.text(f" [{status}]", fp.collapse))
        if recency:
            header_parts.append(Block.text(f" ({recency})", fp.collapse))
        rows.append(join_horizontal(*header_parts))

        if bdy:
            # Prefer paragraph-bounded headline; fall back to char cap.
            if "\n\n" in bdy:
                bdy = bdy.split("\n\n", 1)[0]
            if len(bdy) > _BODY_LIMIT:
                bdy = bdy[:_BODY_LIMIT] + "…"
            rows.append(Block.text(f"    {bdy}", fp.body, width=width))

    if remaining > 0:
        rows.append(Block.text(f"  ({remaining} more)", fp.collapse, width=width))
    return join_vertical(*rows)


def _render_threads(
    section: "FoldSection", marks: dict, zoom: "Zoom",
    fp: FoldPalette, width: int | None,
) -> Block | None:
    """Open threads with body; parked as compact name list; focus marks applied."""
    active = [i for i in section.items if i.payload.get("status") not in RESOLVED_STATUSES]
    if not active:
        return None

    mine = [i for i in active if not i.payload.get("delegate")]
    delegated = [i for i in active if i.payload.get("delegate")]

    open_items = [i for i in mine if i.payload.get("status") != "parked"]
    open_items.sort(
        key=lambda i: (
            -_mark_priority(section.kind, i, section.key_field, marks),
            -(i.ts or 0),
        ),
    )
    parked_items = [i for i in mine if i.payload.get("status") == "parked"]

    rows: list[Block] = [_section_header("THREAD", fp, width)]

    for item in open_items:
        lbl = _label(item, section.key_field)
        recency = _recency_tag(item.ts)
        bdy = _item_body(item, section.key_field)
        mark = _item_mark(section.kind, item, section.key_field, marks)

        header_parts: list[Block] = [Block.text("  open: ", fp.collapse)]
        if mark:
            header_parts.append(Block.text(f"{_MARK_GLYPH[mark]} ", _mark_style(mark, fp)))
        header_parts.append(Block.text(lbl, fp.key))
        if recency:
            header_parts.append(Block.text(f" ({recency})", fp.collapse))
        rows.append(join_horizontal(*header_parts))

        if bdy:
            if len(bdy) > _BODY_LIMIT:
                bdy = bdy[:_BODY_LIMIT] + "…"
            rows.append(Block.text(f"    {bdy}", fp.body, width=width))

    if parked_items:
        names = [_label(i, section.key_field) for i in parked_items]
        parked_cap = _cap(_PARKED_CAP, zoom)
        if len(names) > parked_cap:
            text = ", ".join(names[:parked_cap]) + f", ({len(names) - parked_cap} more)"
        else:
            text = ", ".join(names)
        rows.append(join_horizontal(
            Block.text("  parked: ", fp.collapse),
            Block.text(text, fp.collapse),
        ))

    if delegated:
        by_delegate: dict[str, list[str]] = {}
        for item in delegated:
            d = item.payload["delegate"]
            by_delegate.setdefault(d, []).append(_label(item, section.key_field))
        for d_kind, d_names in by_delegate.items():
            rows.append(Block.text(
                f"  delegate {d_kind}: {', '.join(d_names)}", fp.collapse, width=width,
            ))

    return join_vertical(*rows)


def _render_decisions(
    section: "FoldSection", kind: str, marks: dict,
    inbound: Counter, zoom: Zoom, fp: FoldPalette, width: int | None,
) -> Block | None:
    """Namespace-grouped decisions. Focus-marked items get body; un-marked dim unless DETAILED+."""
    items = list(section.items)
    if not items:
        return None

    key_field = section.key_field
    has_ns = any("/" in str(i.payload.get(key_field, "")) for i in items)
    if not has_ns:
        return _render_decisions_flat(items, key_field, kind, marks, inbound, zoom, fp, width)

    groups: dict[str, list["FoldItem"]] = defaultdict(list)
    for item in items:
        key = str(item.payload.get(key_field, ""))
        ns = key.split("/", 1)[0] if "/" in key else ""
        groups[ns].append(item)

    # Sort groups by: max focus-mark in group, then max salience, then recency.
    def _group_sort_key(ns_items):
        _, its = ns_items
        return (
            max((_mark_priority(kind, i, key_field, marks) for i in its), default=0),
            max((_salience(i, key_field, inbound) for i in its), default=0),
            max((i.ts or 0 for i in its), default=0),
        )
    sorted_groups = sorted(groups.items(), key=_group_sort_key, reverse=True)

    rows: list[Block] = [_section_header(kind.upper(), fp, width)]
    groups_shown = 0
    show_all_bodies = int(zoom) >= 2  # DETAILED/FULL: no de-emphasis
    group_cap = _cap(_DECISION_GROUP_CAP, zoom)
    body_cap = _cap(_DECISION_BODY_CAP, zoom)

    for ns, group_items in sorted_groups:
        if groups_shown >= group_cap:
            remaining_groups = len(sorted_groups) - groups_shown
            remaining_items = sum(len(g) for _, g in sorted_groups[groups_shown:])
            rows.append(Block.text(
                f"  ({remaining_groups} more namespaces, {remaining_items} items)",
                fp.collapse, width=width,
            ))
            break

        sorted_items = sorted(
            group_items,
            key=lambda i: (
                -_mark_priority(kind, i, key_field, marks),
                -_salience(i, key_field, inbound),
            ),
        )

        group_label = f"{ns}/" if ns else "(ungrouped)"
        rows.append(Block.text(
            f"  {group_label} ({len(sorted_items)})", fp.group_header, width=width,
        ))

        body_shown = 0
        name_only: list[str] = []

        for item in sorted_items:
            raw_key = str(item.payload.get(key_field, ""))
            lbl = _strip_namespace(raw_key)
            sal = _salience(item, key_field, inbound)
            mark = _item_mark(kind, item, key_field, marks)

            # Show body when: focus-marked (always), or salient enough AND
            # body budget remaining, or DETAILED+ zoom.
            show_body = (
                mark is not None
                or show_all_bodies
                or (sal >= _SALIENCE_BODY_THRESHOLD and body_shown < body_cap)
            )

            if show_body:
                parts: list[Block] = [Block.text("    ", fp.collapse)]
                if mark:
                    parts.append(Block.text(f"{_MARK_GLYPH[mark]} ", _mark_style(mark, fp)))
                parts.append(Block.text(lbl, fp.key))
                badge = _salience_badge(item, key_field, inbound, fp)
                if badge:
                    parts.append(badge)
                bdy = _item_body(item, key_field)
                if bdy:
                    if len(bdy) > 150:
                        bdy = bdy[:150] + "…"
                    parts.append(Block.text(": ", fp.body))
                    parts.append(Block.text(bdy, fp.body))
                rows.append(join_horizontal(*parts))
                body_shown += 1
            else:
                name_only.append(lbl)

        if name_only:
            if len(name_only) <= 5:
                rows.append(Block.text(f"    {', '.join(name_only)}", fp.collapse, width=width))
            else:
                rows.append(Block.text(f"    ({len(name_only)} more)", fp.collapse, width=width))

        groups_shown += 1

    return join_vertical(*rows)


def _render_decisions_flat(
    items: list["FoldItem"], key_field: str | None, kind: str,
    marks: dict, inbound: Counter, zoom: Zoom, fp: FoldPalette, width: int | None,
) -> Block:
    """Flat decisions list — mark-boosted, salience-sorted."""
    sorted_items = sorted(
        items,
        key=lambda i: (
            -_mark_priority(kind, i, key_field, marks),
            -_salience(i, key_field, inbound),
        ),
    )

    rows: list[Block] = [_section_header(kind.upper(), fp, width)]
    body_shown = 0
    name_only: list[str] = []
    show_all_bodies = int(zoom) >= 2
    flat_body_cap = _cap(_DECISION_BODY_CAP * 2, zoom)

    for item in sorted_items:
        lbl = _label(item, key_field)
        sal = _salience(item, key_field, inbound)
        mark = _item_mark(kind, item, key_field, marks)

        show_body = (
            mark is not None
            or show_all_bodies
            or (sal >= _SALIENCE_BODY_THRESHOLD and body_shown < flat_body_cap)
        )

        if show_body:
            parts: list[Block] = [Block.text("  ", fp.collapse)]
            if mark:
                parts.append(Block.text(f"{_MARK_GLYPH[mark]} ", _mark_style(mark, fp)))
            parts.append(Block.text(lbl, fp.key))
            badge = _salience_badge(item, key_field, inbound, fp)
            if badge:
                parts.append(badge)
            bdy = _item_body(item, key_field)
            if bdy:
                if len(bdy) > 150:
                    bdy = bdy[:150] + "…"
                parts.append(Block.text(": ", fp.body))
                parts.append(Block.text(bdy, fp.body))
            rows.append(join_horizontal(*parts))
            body_shown += 1
        else:
            name_only.append(lbl)

    if name_only:
        if len(name_only) <= 10:
            rows.append(Block.text(f"  {', '.join(name_only)}", fp.collapse, width=width))
        else:
            rows.append(Block.text(f"  ({len(name_only)} more in store)", fp.collapse, width=width))

    return join_vertical(*rows)


# ---------------------------------------------------------------------------
# Focus-filter — derived-keys-as-focus-filter pattern
# ---------------------------------------------------------------------------

def _compute_marks(
    window: "TickWindow | None",
    stale_keys: frozenset[tuple[str, str]],
    cite_keys: frozenset[str] = frozenset(),
    fold: "FoldState | None" = None,
) -> dict[tuple[str, str], str]:
    """(kind, key) → 'added' | 'updated' | 'cited' | 'stale'. Drives salience marks.

    Five derived key sets composed by precedence (added > updated > cited > stale):
    - TickWindow.added_keys: items new in the closed landing window.
    - TickWindow.updated_keys: items touched in the closed landing window.
    - cite_keys: items targeted by cites in the closed landing window
      (dual-form matched against fold items, kind-qualified or bare).
    - fresh-since-close: items with ts > window.ts — post-boundary emits
      that haven't yet been captured in any closed window's deltas.
      Marked _MARK_UPDATED so mid-session emissions don't fall into the
      truncation tail. Instance #5 of derived-keys-as-focus-filter;
      bridges the open-window gap (current-open-window-semantics).
    - stale_keys: items open but untouched in >7d (clock-derived).

    Each is an instance of derived-keys-as-focus-filter — bounded sets that
    mark the accumulated view by membership. Composition order is
    intentional: direct touches (added/updated) outrank inbound attention
    (cited) which outranks staleness — a stale item that just got cited
    displays as ⊙, dissolving the ⊘ in real time. Closed-window deltas
    outrank fresh-since-close so a re-emit's prior closed-window mark wins
    (avoids marking the same item twice across boundaries).
    """
    marks: dict[tuple[str, str], str] = {}
    if window is not None:
        for kind, keys in window.added_keys.items():
            for k in keys:
                marks[(kind, k)] = _MARK_ADDED
        for kind, keys in window.updated_keys.items():
            for k in keys:
                marks.setdefault((kind, k), _MARK_UPDATED)
    if cite_keys and fold is not None:
        # Dual-form match: cite refs may be emitted as 'kind/key' or bare 'key'.
        # Walk fold items and check both forms against cite_keys.
        for section in fold.sections:
            kf = section.key_field
            if not kf:
                continue
            for item in section.items:
                key = str(item.payload.get(kf, ""))
                if not key:
                    continue
                full = f"{section.kind}/{key}"
                if full in cite_keys or key in cite_keys:
                    marks.setdefault((section.kind, key), _MARK_CITED)
    if window is not None and window.ts and fold is not None:
        # Fresh-since-close: items emitted after the landing window's
        # boundary are mid-session and have no mark from window deltas yet.
        # Mark as UPDATED (not ADDED) — we can't distinguish brand-new from
        # re-emit without prior fold state. The next boundary will refine.
        boundary_ts = window.ts
        for section in fold.sections:
            kf = section.key_field
            if not kf:
                continue
            for item in section.items:
                if item.ts is None or item.ts <= boundary_ts:
                    continue
                key = str(item.payload.get(kf, ""))
                if not key:
                    continue
                marks.setdefault((section.kind, key), _MARK_UPDATED)
    for key_tuple in stale_keys:
        marks.setdefault(key_tuple, _MARK_STALE)  # higher-priority marks win
    return marks


def _item_mark(
    kind: str, item: "FoldItem", key_field: str | None, marks: dict,
) -> str | None:
    """Look up the focus mark for an item, if any."""
    if not key_field or not marks:
        return None
    key = str(item.payload.get(key_field, ""))
    if not key:
        return None
    return marks.get((kind, key))


def _mark_priority(
    kind: str, item: "FoldItem", key_field: str | None, marks: dict,
) -> int:
    """Sort weight: added=4, updated=3, cited=2, stale=1, unmarked=0.

    Direct touches (added/updated) outrank inbound attention (cited) which
    outranks staleness. New/touched items pull to the top of their section;
    cited items pull above stale (just got attention); stale-open pulls
    above untouched. All four are salience signals, not escalations.
    """
    m = _item_mark(kind, item, key_field, marks)
    if m == _MARK_ADDED:
        return 4
    if m == _MARK_UPDATED:
        return 3
    if m == _MARK_CITED:
        return 2
    if m == _MARK_STALE:
        return 1
    return 0


def _mark_style(mark: str, fp: FoldPalette) -> Style:
    """Palette role for each mark kind.

    cited shares ref_outbound's role since cite-count is structurally
    inbound-ref count of kind=cite — same family of signal as outbound
    ref edges in the fold lens, just routed through the cite primitive.
    """
    if mark == _MARK_ADDED:
        return fp.ref_indicator
    if mark == _MARK_CITED:
        return fp.ref_outbound
    if mark == _MARK_STALE:
        return fp.stale_indicator
    return fp.n_indicator


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

def _section_header(kind_upper: str, fp: FoldPalette, width: int | None) -> Block:
    return Block.text(f"## {kind_upper}", fp.section_header, width=width)


def _item_line(
    item: "FoldItem", kind: str, key_field: str | None, marks: dict,
    fp: FoldPalette, width: int | None, *, indent: int = 2,
) -> Block:
    """Key + recency + body, with optional focus glyph."""
    lbl = _label(item, key_field)
    recency = _recency_tag(item.ts)
    bdy = _item_body(item, key_field)
    mark = _item_mark(kind, item, key_field, marks)

    parts: list[Block] = [Block.text(" " * indent, fp.collapse)]
    if mark:
        parts.append(Block.text(f"{_MARK_GLYPH[mark]} ", _mark_style(mark, fp)))
    parts.append(Block.text(lbl, fp.key))
    if recency:
        parts.append(Block.text(f" ({recency})", fp.collapse))
    if bdy:
        if len(bdy) > _BODY_LIMIT:
            bdy = bdy[:_BODY_LIMIT] + "…"
        parts.append(Block.text(": ", fp.body))
        parts.append(Block.text(bdy, fp.body))
    return join_horizontal(*parts)


def _item_body(item: "FoldItem", key_field: str | None) -> str:
    label_val = _label(item, key_field)
    skip = {"status", "weight", "delegate", "priority"}
    for k, v in item.payload.items():
        if not v or str(v) == label_val or k in skip:
            continue
        return str(v)
    return ""


def _compute_inbound_refs(data: "FoldState") -> Counter:
    inbound: Counter = Counter()
    for section in data.sections:
        for item in section.items:
            for ref in item.refs:
                inbound[ref] += 1
    return inbound


def _salience(item: "FoldItem", key_field: str | None, inbound: Counter) -> int:
    return item.n + _inbound_count(item, key_field, inbound)


def _inbound_count(item: "FoldItem", key_field: str | None, inbound: Counter) -> int:
    """Sum inbound references to an item by its fold-key value.

    Matches both forms a ref may take:
    * Kind-qualified — ``<kind>/<key>``, e.g. ``decision/design/foo``
    * Bare — the key_field value itself, e.g. ``design/foo``
      (this case matters when the key contains a namespace slash —
      ``endswith("/foo")`` alone misses it)
    """
    if not key_field:
        return 0
    key = item.payload.get(key_field, "")
    if not key:
        return 0
    count = 0
    suffix = f"/{key}"
    for ref_key, ref_count in inbound.items():
        if ref_key == key or ref_key.endswith(suffix):
            count += ref_count
    return count


def _salience_badge(
    item: "FoldItem", key_field: str | None, inbound: Counter, fp: FoldPalette,
) -> Block | None:
    parts: list[Block] = []
    if item.n > 1:
        parts.append(Block.text(f"×{item.n}", fp.n_indicator))
    ref_in = _inbound_count(item, key_field, inbound)
    if ref_in > 0:
        if parts:
            parts.append(Block.text(" ", fp.collapse))
        parts.append(Block.text(f"←{ref_in}", fp.ref_indicator))
    if item.refs:
        if parts:
            parts.append(Block.text(" ", fp.collapse))
        parts.append(Block.text(f"→{len(item.refs)}", fp.ref_outbound))
    if not parts:
        return None
    return join_horizontal(
        Block.text(" [", fp.collapse),
        *parts,
        Block.text("]", fp.collapse),
    )


def _strip_namespace(key: str) -> str:
    return key.split("/", 1)[1] if "/" in key else key


def _compact_trigger(trigger: str, observer: str) -> str:
    """Strip the current observer's prefix from a boundary trigger.

    Boundary triggers are emitted as ``"{observer} {action}"`` (e.g.
    ``"kyle/loops-claude closed"``). In a single-observer vertex the
    observer prefix is the same on every row — no signal, just column
    bloat. Stripping it leaves just the action verb (``closed``,
    ``opened``, or a custom trigger name).

    Multi-observer vertices preserve other observers' prefixes intact —
    the prefix only strips when it matches ``observer``, so peer
    activity stays distinguishable.
    """
    if not observer or not trigger:
        return trigger
    prefix = f"{observer} "
    if trigger.startswith(prefix):
        return trigger[len(prefix):]
    return trigger


def _fmt_ts(ts_epoch: float) -> str:
    """Short date: 'Apr 18' or 'Apr 18 03:43' if same day as now."""
    dt = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).astimezone()
    now = datetime.now().astimezone()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if dt.year == now.year:
        return dt.strftime("%b %-d")
    return dt.strftime("%Y-%m-%d")


def _fmt_duration(secs: float) -> str:
    """Compact duration: '5d14h', '9h23m', '12m', '45s'."""
    s = int(secs)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h{m}m" if m else f"{h}h"
    d = s // 86400
    h = (s % 86400) // 3600
    return f"{d}d{h}h" if h else f"{d}d"
