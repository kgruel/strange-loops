"""Dashboard command — fetch/render/fetch_stream wired through painted run_cli.

Static mode prints and exits. Live mode polls the store and repaints in place.
Interactive mode (-i) runs a persistent alt-screen TUI via painted Surface.
Zoom controls detail: -q for one-liner, default for table, -v/-vv reserved.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from painted import CliContext
    from painted.block import Block

from strange_loops.lifecycle import fold_all_tasks, project_vertex_path, tasks_vertex_path
from strange_loops.store import filter_task_facts

# Column widths
_COL_TASK = 26
_COL_STATUS = 14
_COL_CHANGES = 12
_COL_ACTIVITY = 12

# Poll interval for live mode (seconds)
_POLL_INTERVAL = 2.0


# -- State --


@dataclass(frozen=True)
class TaskRow:
    """One task in the dashboard snapshot."""

    name: str
    title: str
    status: str
    worktree: str | None = None
    activity: datetime | None = None
    changes: str = ""


@dataclass(frozen=True)
class ProjectSummary:
    """Project store counts."""

    total: int
    decisions: int
    threads: int
    plans: int


@dataclass(frozen=True)
class DashboardState:
    """Frozen snapshot passed to render."""

    tasks: tuple[TaskRow, ...]
    project: ProjectSummary | None = None
    fact_total: int = 0
    session_active: bool = False
    session_fact_count: int = 0
    detail_facts: tuple[dict, ...] = ()
    last_fetched: float = 0.0


# -- Helpers --


def _status_style(status: str, palette):
    """Map task status to a painted Style."""
    if status in ("completed", "merged"):
        return palette.success
    if status in ("working", "assigned"):
        return palette.warning
    if status in ("errored",):
        return palette.error
    if status in ("exhausted",):
        return palette.warning  # TODO: needs its own semantic token (amber/yellow)
    # created, closed, unknown
    return palette.muted


def _relative_time(dt: datetime | None) -> str:
    """Format datetime as relative time string."""
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return ""
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _changes_summary(worktree_path: str | None) -> str:
    """Get +N -N from git diff --shortstat in worktree. Empty if unavailable."""
    if not worktree_path:
        return ""
    path = Path(worktree_path)
    if not path.exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "diff", "--shortstat"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        text = result.stdout.strip()
        insertions = 0
        deletions = 0
        m = re.search(r"(\d+) insertion", text)
        if m:
            insertions = int(m.group(1))
        m = re.search(r"(\d+) deletion", text)
        if m:
            deletions = int(m.group(1))
        parts = []
        if insertions:
            parts.append(f"+{insertions}")
        if deletions:
            parts.append(f"-{deletions}")
        return " ".join(parts)
    except (subprocess.SubprocessError, OSError):
        return ""


def _task_activity(all_facts: list[dict], task_name: str) -> datetime | None:
    """Find the latest fact timestamp for a task."""
    latest: datetime | None = None
    for f in all_facts:
        name = f.get("payload", {}).get("name")
        if name != task_name:
            continue
        ts = f["ts"]
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        elif isinstance(ts, datetime):
            dt = ts
        else:
            continue
        if latest is None or dt > latest:
            latest = dt
    return latest


def _project_summary() -> ProjectSummary | None:
    """Read project vertex, return summary. None if unavailable."""
    try:
        from engine import vertex_summary

        summary = vertex_summary(project_vertex_path())
        total = summary["facts"]["total"]
        if total == 0:
            return None

        kinds = summary["facts"]["kinds"]
        return ProjectSummary(
            total=total,
            decisions=kinds.get("decision", {}).get("count", 0),
            threads=kinds.get("thread", {}).get("count", 0),
            plans=kinds.get("plan", {}).get("count", 0),
        )
    except Exception:
        return None


def _project_header(summary: ProjectSummary) -> str:
    """Format project summary as header string."""
    parts = [f"{summary.total} facts"]
    if summary.decisions:
        parts.append(f"{summary.decisions} decisions")
    if summary.threads:
        parts.append(f"{summary.threads} threads")
    if summary.plans:
        parts.append(f"{summary.plans} plans")
    return "Project \u2014 " + " | ".join(parts)


# -- Fetch --


def _fetch() -> DashboardState:
    """Read task vertex and project vertex, return frozen snapshot."""
    from engine import vertex_facts, vertex_summary

    vp = tasks_vertex_path()
    tasks = fold_all_tasks(vp)
    all_facts = vertex_facts(vp, 0, float("inf"))
    fact_total = vertex_summary(vp)["facts"]["total"]

    rows: list[TaskRow] = []
    for task in tasks:
        activity_dt = _task_activity(all_facts, task["name"])
        changes = _changes_summary(task.get("worktree"))
        rows.append(
            TaskRow(
                name=task["name"],
                title=task.get("title", ""),
                status=task.get("status", "unknown"),
                worktree=task.get("worktree"),
                activity=activity_dt,
                changes=changes,
            )
        )

    return DashboardState(
        tasks=tuple(rows),
        project=_project_summary(),
        fact_total=fact_total,
    )


def _fetch_with_detail(selected_name: str | None) -> DashboardState:
    """Extended fetch: task list + detail facts for selected task + session status."""
    from engine import vertex_facts, vertex_summary

    vp = tasks_vertex_path()
    tasks = fold_all_tasks(vp)
    all_facts = vertex_facts(vp, 0, float("inf"))
    fact_total = vertex_summary(vp)["facts"]["total"]

    # Session status
    session_facts = [f for f in all_facts if f["kind"] in ("session.start", "session.end")]
    session_facts.sort(key=lambda f: f["ts"])
    session_active = False
    if session_facts:
        session_active = session_facts[-1]["kind"] == "session.start"

    # Detail facts for selected task
    detail_facts: tuple[dict, ...] = ()
    if selected_name:
        task_facts = filter_task_facts(all_facts, selected_name)
        task_facts.sort(key=lambda f: f["ts"])
        detail_facts = tuple(task_facts)

    rows: list[TaskRow] = []
    for task in tasks:
        rows.append(
            TaskRow(
                name=task["name"],
                title=task.get("title", ""),
                status=task.get("status", "unknown"),
                worktree=task.get("worktree"),
                activity=_task_activity(all_facts, task["name"]),
                changes=_changes_summary(task.get("worktree")),
            )
        )

    return DashboardState(
        tasks=tuple(rows),
        project=_project_summary(),
        fact_total=fact_total,
        session_active=session_active,
        session_fact_count=fact_total,
        detail_facts=detail_facts,
        last_fetched=time.monotonic(),
    )


async def _fetch_stream() -> AsyncIterator[DashboardState]:
    """Poll store, yield snapshots for live rendering."""
    import asyncio

    while True:
        try:
            yield _fetch()
        except FileNotFoundError:
            pass
        await asyncio.sleep(_POLL_INTERVAL)


# -- Render --


def _render(ctx: CliContext, state: DashboardState) -> Block:
    """Render dashboard state to Block — zoom-aware."""
    from painted import Zoom

    if ctx.zoom == Zoom.MINIMAL:
        return _render_minimal(state, ctx.width)
    if ctx.zoom == Zoom.SUMMARY:
        return _render_summary(state, ctx.width)
    if ctx.zoom == Zoom.DETAILED:
        return _render_detailed(state, ctx.width)
    return _render_full(state, ctx.width)


def _render_minimal(state: DashboardState, width: int) -> Block:
    """Zoom 0: one-line status counts."""
    from painted import truncate
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    counts: dict[str, int] = {}
    for t in state.tasks:
        counts[t.status] = counts.get(t.status, 0) + 1

    parts = [f"{len(state.tasks)} tasks"]
    for status, n in sorted(counts.items()):
        parts.append(f"{n} {status}")

    return truncate(Block.text(", ".join(parts), p.muted), width)


_CLOSED_STATUSES = {"closed"}

# Column width for closed task name alignment
_COL_CLOSED_NAME = 22


def _sort_recent_first(tasks: list[TaskRow]) -> list[TaskRow]:
    """Sort tasks by activity, most recent first. No-activity sorts last."""
    from datetime import datetime, timezone

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return sorted(tasks, key=lambda t: t.activity or epoch, reverse=True)


def _separator(p) -> "Block":
    """Horizontal rule spanning the table width."""
    from painted.block import Block

    total_width = _COL_TASK + _COL_STATUS + _COL_CHANGES + _COL_ACTIVITY
    return Block.text("  " + "\u2500" * (total_width - 2), p.muted)


def _render_task_table(
    tasks: list[TaskRow],
    blocks: list["Block"],
    p,
    *,
    show_metadata: bool = False,
    row_gap: bool = False,
) -> None:
    """Render tasks as a columnar table. Mutates blocks list."""
    from painted import Style
    from painted.block import Block
    from painted.compose import join_horizontal

    if not tasks:
        return

    header_style = Style(bold=True)
    header = join_horizontal(
        Block.text("  Task", header_style, width=_COL_TASK),
        Block.text("Status", header_style, width=_COL_STATUS),
        Block.text("Changes", header_style, width=_COL_CHANGES),
        Block.text("Activity", header_style, width=_COL_ACTIVITY),
    )
    blocks.append(header)
    blocks.append(_separator(p))

    for task in tasks:
        name_style = p.muted if task.status in _CLOSED_STATUSES else p.accent
        status_style = _status_style(task.status, p)
        activity = _relative_time(task.activity)

        row = join_horizontal(
            Block.text(f"  {task.name}", name_style, width=_COL_TASK),
            Block.text(task.status, status_style, width=_COL_STATUS),
            Block.text(task.changes, p.muted, width=_COL_CHANGES),
            Block.text(activity, p.muted, width=_COL_ACTIVITY),
        )
        blocks.append(row)

        if task.title:
            title_style = p.muted if task.status in _CLOSED_STATUSES else p.muted
            blocks.append(Block.text(f"  \u2514 {task.title}", title_style))
        if show_metadata and task.worktree:
            blocks.append(Block.text(f"    worktree: {task.worktree}", p.muted))
        if row_gap:
            blocks.append(Block.text("", p.muted, width=1))


def _render_summary(state: DashboardState, width: int) -> Block:
    """Zoom 1 (default): table for visible tasks, closed collapsed."""
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    blocks: list[Block] = []

    if state.project:
        blocks.append(Block.text(_project_header(state.project), p.accent))
        blocks.append(Block.text("", p.muted, width=1))

    visible = _sort_recent_first([t for t in state.tasks if t.status not in _CLOSED_STATUSES])
    closed = [t for t in state.tasks if t.status in _CLOSED_STATUSES]

    if not visible and not closed:
        blocks.append(Block.text("No tasks.", p.muted))
        return join_vertical(*blocks)

    _render_task_table(visible, blocks, p)

    if closed:
        blocks.append(_separator(p))
        blocks.append(Block.text(f"  {len(closed)} closed", p.muted))

    return join_vertical(*blocks)


def _render_detailed(state: DashboardState, width: int) -> Block:
    """Zoom 2 (-v): table with metadata, closed listed individually."""
    from painted.block import Block
    from painted.compose import join_horizontal, join_vertical
    from painted.palette import current_palette

    p = current_palette()
    blocks: list[Block] = []

    if state.project:
        blocks.append(Block.text(_project_header(state.project), p.accent))
        blocks.append(Block.text("", p.muted, width=1))

    visible = _sort_recent_first([t for t in state.tasks if t.status not in _CLOSED_STATUSES])
    closed = _sort_recent_first([t for t in state.tasks if t.status in _CLOSED_STATUSES])

    if not visible and not closed:
        blocks.append(Block.text("No tasks.", p.muted))
        return join_vertical(*blocks)

    _render_task_table(visible, blocks, p, show_metadata=True)

    if closed:
        blocks.append(_separator(p))
        for task in closed:
            activity = _relative_time(task.activity)
            row = join_horizontal(
                Block.text(f"  {task.name}", p.muted, width=_COL_CLOSED_NAME),
                Block.text(activity, p.muted),
            )
            blocks.append(row)

    return join_vertical(*blocks)


def _render_full(state: DashboardState, width: int) -> Block:
    """Zoom 3 (-vv): all tasks in table with metadata + store stats."""
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()
    blocks: list[Block] = []

    if state.project:
        blocks.append(Block.text(_project_header(state.project), p.accent))
        blocks.append(Block.text("", p.muted, width=1))

    all_tasks = _sort_recent_first(list(state.tasks))

    if not all_tasks:
        blocks.append(Block.text("No tasks.", p.muted))
        return join_vertical(*blocks)

    _render_task_table(all_tasks, blocks, p, show_metadata=True, row_gap=True)

    blocks.append(Block.text(f"  Task store: {state.fact_total} facts", p.muted))
    if state.project:
        blocks.append(Block.text(f"  Project store: {state.project.total} facts", p.muted))

    return join_vertical(*blocks)


# -- Interactive TUI --

_MIN_INTERACTIVE_WIDTH = 80


def _render_header_block(state: DashboardState, w: int) -> "Block":
    """Header row: session status + fact count + key hints + clock."""
    from painted import Style
    from painted.block import Block
    from painted.compose import join_horizontal
    from painted.palette import current_palette

    p = current_palette()
    session_label = "session: active" if state.session_active else "session: ended"
    facts_label = f"{state.session_fact_count} facts"
    hint = "j/k select  r refresh  q quit"
    clock = datetime.now().strftime("%H:%M:%S")

    left = Block.text(f" strange-loops  {session_label}  {facts_label}", p.accent, width=w // 2)
    right = Block.text(f"{hint}  {clock} ", Style(dim=True), width=w - w // 2)
    return join_horizontal(left, right)


def _render_tasks_pane_block(
    state: DashboardState,
    selected: int,
    scroll: int,
    focus: str,
    w: int,
    h: int,
) -> "Block":
    """Left pane: scrollable task table with selection highlight."""
    from painted import Style
    from painted.block import Block
    from painted.compose import join_horizontal, join_vertical
    from painted.palette import current_palette

    p = current_palette()

    # Pane header
    header_style = Style(bold=True) if focus == "tasks" else Style(dim=True)
    pane_header = Block.text(f" Tasks ({len(state.tasks)})", header_style, width=w)
    pane_sep = Block.text(" " + "\u2500" * (w - 2), Style(dim=True), width=w)

    # Column headers
    col_header_style = Style(bold=True)
    # Adaptive columns based on width
    if w >= 64:
        col_header = join_horizontal(
            Block.text("  Task", col_header_style, width=_COL_TASK),
            Block.text("Status", col_header_style, width=_COL_STATUS),
            Block.text("Chg", col_header_style, width=_COL_CHANGES),
            Block.text("Age", col_header_style, width=_COL_ACTIVITY),
        )
    elif w >= 52:
        col_header = join_horizontal(
            Block.text("  Task", col_header_style, width=_COL_TASK),
            Block.text("Status", col_header_style, width=_COL_STATUS),
            Block.text("Age", col_header_style, width=_COL_ACTIVITY),
        )
    else:
        col_header = join_horizontal(
            Block.text("  Task", col_header_style, width=_COL_TASK),
            Block.text("Status", col_header_style, width=_COL_STATUS),
        )
    col_sep = Block.text("  " + "\u2500" * (w - 4), Style(dim=True), width=w)

    # Available height for task rows (subtract pane header + sep + col header + col sep)
    avail_h = h - 4
    rows_per_task = 2
    visible_tasks = max(1, avail_h // rows_per_task)

    # Build task rows with scroll
    task_rows: list[Block] = []
    end = min(scroll + visible_tasks, len(state.tasks))
    for i in range(scroll, end):
        task = state.tasks[i]
        is_selected = i == selected
        name_style = (
            Style(reverse=True)
            if is_selected
            else (p.muted if task.status in _CLOSED_STATUSES else p.accent)
        )
        status_style = Style(reverse=True) if is_selected else _status_style(task.status, p)
        activity = _relative_time(task.activity)

        if w >= 64:
            row = join_horizontal(
                Block.text(f"  {task.name}", name_style, width=_COL_TASK),
                Block.text(task.status, status_style, width=_COL_STATUS),
                Block.text(
                    task.changes,
                    Style(reverse=True) if is_selected else p.muted,
                    width=_COL_CHANGES,
                ),
                Block.text(
                    activity, Style(reverse=True) if is_selected else p.muted, width=_COL_ACTIVITY
                ),
            )
        elif w >= 52:
            row = join_horizontal(
                Block.text(f"  {task.name}", name_style, width=_COL_TASK),
                Block.text(task.status, status_style, width=_COL_STATUS),
                Block.text(
                    activity, Style(reverse=True) if is_selected else p.muted, width=_COL_ACTIVITY
                ),
            )
        else:
            row = join_horizontal(
                Block.text(f"  {task.name}", name_style, width=_COL_TASK),
                Block.text(task.status, status_style, width=_COL_STATUS),
            )
        task_rows.append(row)
        if task.title:
            title_style = Style(reverse=True) if is_selected else p.muted
            task_rows.append(Block.text(f"    \u2514 {task.title}", title_style, width=w))
        else:
            task_rows.append(Block.text("", p.muted, width=w))

    # Fill remaining height
    while len(task_rows) < avail_h:
        task_rows.append(Block.text("", p.muted, width=w))

    return join_vertical(pane_header, pane_sep, col_header, col_sep, *task_rows[:avail_h])


def _render_fact_row_block(fact: dict, w: int) -> "Block":
    """Render a single fact as a Block row for the detail pane."""
    from painted import Style
    from painted.block import Block

    ts = fact["ts"]
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        dt = None

    time_str = dt.strftime("%H:%M") if dt else "??:??"
    kind = fact["kind"]
    payload = fact.get("payload", {})
    parts = [f"{k}={v}" for k, v in payload.items() if v is not None and v != ""]
    summary = " ".join(parts)

    text = f" {time_str} [{kind}] {summary}"
    if len(text) > w:
        text = text[: w - 1] + "\u2026"
    return Block.text(text, Style(dim=True), width=w)


def _render_detail_pane_block(
    state: DashboardState,
    selected: int,
    scroll: int,
    focus: str,
    w: int,
    h: int,
) -> "Block":
    """Right pane: selected task detail with fact log."""
    from painted import Style
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    p = current_palette()

    if not state.tasks:
        header_style = Style(dim=True)
        pane_header = Block.text(" No task selected", header_style, width=w)
        rows = [Block.text("", p.muted, width=w) for _ in range(h - 1)]
        return join_vertical(pane_header, *rows)

    idx = max(0, min(selected, len(state.tasks) - 1))
    task = state.tasks[idx]

    # Pane header
    header_style = Style(bold=True) if focus == "detail" else Style(dim=True)
    pane_header = Block.text(f" {task.name} \u2014 {task.status}", header_style, width=w)
    pane_sep = Block.text(" " + "\u2500" * (w - 2), Style(dim=True), width=w)

    # Log lines
    avail_h = h - 2  # subtract header + sep
    facts = list(state.detail_facts)
    # Clamp scroll
    max_scroll = max(0, len(facts) - avail_h)
    clamped_scroll = max(0, min(scroll, max_scroll))
    visible = facts[clamped_scroll : clamped_scroll + avail_h]

    log_rows: list[Block] = []
    for f in visible:
        log_rows.append(_render_fact_row_block(f, w))

    while len(log_rows) < avail_h:
        log_rows.append(Block.text("", p.muted, width=w))

    return join_vertical(pane_header, pane_sep, *log_rows[:avail_h])


def _render_status_block(state: DashboardState, w: int) -> "Block":
    """Bottom status bar: project summary + last-updated."""
    from painted import Style
    from painted.block import Block
    from painted.compose import join_horizontal

    proj = state.project
    proj_str = _project_header(proj) if proj else "No project store"
    age = int(time.monotonic() - state.last_fetched) if state.last_fetched else 0
    updated = f"updated {age}s ago"
    left = Block.text(f" {proj_str}", Style(dim=True), width=w - len(updated) - 1)
    right = Block.text(updated + " ", Style(dim=True), width=len(updated) + 1)
    return join_horizontal(left, right)


class DashboardSurface:
    """Alt-screen persistent dashboard for strange-loops.

    Subclasses painted.tui.Surface. Import is deferred to avoid loading
    the full TUI stack for non-interactive modes.
    """

    def __init__(self, ctx: "CliContext"):
        from painted.tui import Surface

        self._surface_cls = Surface
        self._ctx = ctx
        self._state: DashboardState = _fetch_with_detail(None)
        self._selected: int = 0
        self._task_scroll: int = 0
        self._detail_scroll: int = 0
        self._focus: str = "tasks"
        self._last_poll: float = time.monotonic()
        self._last_clock_tick: float = time.monotonic()
        self._tasks_w: int = 0
        self._main_h: int = 0

    def _selected_name(self) -> str | None:
        if not self._state.tasks:
            return None
        idx = max(0, min(self._selected, len(self._state.tasks) - 1))
        return self._state.tasks[idx].name

    def _move_selection(self, delta: int) -> None:
        n = len(self._state.tasks)
        if n == 0:
            return
        old = self._selected
        self._selected = max(0, min(n - 1, self._selected + delta))
        if self._selected != old:
            # Reset detail scroll on selection change
            self._detail_scroll = 0
            # Refetch detail facts
            self._state = _fetch_with_detail(self._selected_name())
        # Keep selected task in view
        avail_h = self._main_h - 4
        rows_per_task = 2
        visible_tasks = max(1, avail_h // rows_per_task)
        if self._selected < self._task_scroll:
            self._task_scroll = self._selected
        elif self._selected >= self._task_scroll + visible_tasks:
            self._task_scroll = self._selected - visible_tasks + 1

    def run(self) -> None:
        """Build a Surface dynamically, run it."""
        import asyncio

        from painted.tui import Surface

        dashboard = self  # capture for closures

        class _Surface(Surface):
            def layout(self, width: int, height: int) -> None:
                dashboard._tasks_w = max(38, width * 2 // 5)
                dashboard._main_h = height - 4

            def update(self) -> None:
                now = time.monotonic()
                if now - dashboard._last_poll >= _POLL_INTERVAL:
                    dashboard._last_poll = now
                    new_state = _fetch_with_detail(dashboard._selected_name())
                    if (
                        new_state.fact_total != dashboard._state.fact_total
                        or new_state.detail_facts != dashboard._state.detail_facts
                    ):
                        dashboard._state = new_state
                        self.mark_dirty()
                if int(now) != int(dashboard._last_clock_tick):
                    dashboard._last_clock_tick = now
                    self.mark_dirty()

            def render(self) -> None:
                from painted import Style

                if self._buf is None:
                    return
                w, h = self._buf.width, self._buf.height

                # Below minimum width: can't render interactive
                if w < _MIN_INTERACTIVE_WIDTH:
                    self._buf.fill(0, 0, w, h, " ", Style())
                    from painted.block import Block

                    msg = Block.text(
                        "Terminal too narrow for interactive mode.", Style(dim=True), width=w
                    )
                    msg.paint(self._buf.region(0, 0, w, 1), 0, 0)
                    return

                self._buf.fill(0, 0, w, h, " ", Style())
                tasks_w = dashboard._tasks_w
                main_h = dashboard._main_h

                # Header (row 0)
                _render_header_block(dashboard._state, w).paint(self._buf.region(0, 0, w, 1), 0, 0)

                # HSep (row 1)
                from painted.block import Block

                Block.text("\u2500" * w, Style(dim=True), width=w).paint(
                    self._buf.region(0, 1, w, 1), 0, 0
                )

                # Tasks pane (rows 2..h-3)
                if main_h > 0:
                    _render_tasks_pane_block(
                        dashboard._state,
                        dashboard._selected,
                        dashboard._task_scroll,
                        dashboard._focus,
                        tasks_w,
                        main_h,
                    ).paint(self._buf.region(0, 2, tasks_w, main_h), 0, 0)

                # VSep
                for y in range(2, 2 + main_h):
                    self._buf.put(tasks_w, y, "\u2502", Style(dim=True))

                # Detail pane (rows 2..h-3)
                detail_w = w - tasks_w - 1
                if detail_w > 0 and main_h > 0:
                    _render_detail_pane_block(
                        dashboard._state,
                        dashboard._selected,
                        dashboard._detail_scroll,
                        dashboard._focus,
                        detail_w,
                        main_h,
                    ).paint(self._buf.region(tasks_w + 1, 2, detail_w, main_h), 0, 0)

                # BSep (row h-2)
                Block.text("\u2500" * w, Style(dim=True), width=w).paint(
                    self._buf.region(0, h - 2, w, 1), 0, 0
                )

                # Status bar (row h-1)
                _render_status_block(dashboard._state, w).paint(
                    self._buf.region(0, h - 1, w, 1), 0, 0
                )

            def on_key(self, key: str) -> None:
                if key in ("q", "\x03", "escape"):
                    self.quit()
                    return
                if key in ("j", "down"):
                    dashboard._move_selection(1)
                elif key in ("k", "up"):
                    dashboard._move_selection(-1)
                elif key == "r":
                    dashboard._state = _fetch_with_detail(dashboard._selected_name())
                elif key == "tab":
                    dashboard._focus = "detail" if dashboard._focus == "tasks" else "tasks"
                elif key in ("[", "page_up"):
                    if dashboard._focus == "detail":
                        dashboard._detail_scroll = max(0, dashboard._detail_scroll - 1)
                elif key in ("]", "page_down"):
                    if dashboard._focus == "detail":
                        max_scroll = max(
                            0, len(dashboard._state.detail_facts) - (dashboard._main_h - 2)
                        )
                        dashboard._detail_scroll = min(max_scroll, dashboard._detail_scroll + 1)
                elif key == "home":
                    if dashboard._state.tasks:
                        dashboard._selected = 0
                        dashboard._task_scroll = 0
                        dashboard._detail_scroll = 0
                        dashboard._state = _fetch_with_detail(dashboard._selected_name())
                elif key == "end":
                    if dashboard._state.tasks:
                        dashboard._selected = len(dashboard._state.tasks) - 1
                        dashboard._detail_scroll = 0
                        dashboard._state = _fetch_with_detail(dashboard._selected_name())
                        avail_h = dashboard._main_h - 4
                        rows_per_task = 2
                        visible_tasks = max(1, avail_h // rows_per_task)
                        if dashboard._selected >= visible_tasks:
                            dashboard._task_scroll = dashboard._selected - visible_tasks + 1
                elif key == "G":
                    if dashboard._state.tasks:
                        dashboard._selected = len(dashboard._state.tasks) - 1
                        dashboard._detail_scroll = 0
                        dashboard._state = _fetch_with_detail(dashboard._selected_name())
                        avail_h = dashboard._main_h - 4
                        rows_per_task = 2
                        visible_tasks = max(1, avail_h // rows_per_task)
                        if dashboard._selected >= visible_tasks:
                            dashboard._task_scroll = dashboard._selected - visible_tasks + 1
                self.mark_dirty()

        surface = _Surface(fps_cap=60)
        asyncio.run(surface.run())


def _run_interactive(ctx: "CliContext") -> int:
    """Handler for INTERACTIVE output mode — alt-screen TUI."""
    surface = DashboardSurface(ctx)
    surface.run()
    return 0


# -- Entry --


def run_dashboard(argv: list[str]) -> int:
    """Entry point — delegates to painted run_cli.

    Default is static (print and quit). Pass --live for persistent view.
    Pass -i for interactive alt-screen TUI.
    """
    from painted import OutputMode, run_cli

    # Default to static — dashboard is a status command, not a TUI.
    # --live must be explicit. -i triggers interactive mode.
    effective = list(argv)
    if (
        "--live" not in effective
        and "--static" not in effective
        and "-i" not in effective
        and "--interactive" not in effective
    ):
        effective.append("--static")

    return run_cli(
        effective,
        render=_render,
        fetch=_fetch,
        fetch_stream=_fetch_stream,
        handlers={OutputMode.INTERACTIVE: _run_interactive},
        description="Task dashboard",
        prog="strange-loops dashboard",
    )
