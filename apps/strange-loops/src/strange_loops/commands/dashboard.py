"""Dashboard command — fetch/render/fetch_stream wired through painted run_cli.

Static mode prints and exits. Live mode polls the store and repaints in place.
Zoom controls detail: -q for one-liner, default for table, -v/-vv reserved.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from painted import CliContext
    from painted.block import Block

from strange_loops.lifecycle import fold_all_tasks
from strange_loops.store import require_store, store_path

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


# -- Helpers --


def _status_style(status: str, palette):
    """Map task status to a painted Style."""
    if status in ("completed", "merged"):
        return palette.success
    if status in ("working", "assigned"):
        return palette.warning
    if status in ("errored",):
        return palette.error
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
    """Read project store, return summary. None if unavailable."""
    try:
        from strange_loops.store import store_path_for

        sp = store_path_for("project")
        if not sp.exists():
            return None

        from engine import StoreReader

        with StoreReader(sp) as reader:
            total = reader.fact_total
            all_facts = reader.facts_between(0, float("inf"))

        counts: dict[str, int] = {}
        for f in all_facts:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1

        return ProjectSummary(
            total=total,
            decisions=counts.get("decision", 0),
            threads=counts.get("thread", 0),
            plans=counts.get("plan", 0),
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
    """Read task store and project store, return frozen snapshot."""
    sp = store_path()
    require_store(sp)

    from engine import StoreReader

    with StoreReader(sp) as reader:
        tasks = fold_all_tasks(reader)
        all_facts = reader.facts_between(0, float("inf"))
        fact_total = reader.fact_total

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

    visible = _sort_recent_first(
        [t for t in state.tasks if t.status not in _CLOSED_STATUSES]
    )
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

    visible = _sort_recent_first(
        [t for t in state.tasks if t.status not in _CLOSED_STATUSES]
    )
    closed = _sort_recent_first(
        [t for t in state.tasks if t.status in _CLOSED_STATUSES]
    )

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


# -- Entry --


def run_dashboard(argv: list[str]) -> int:
    """Entry point — delegates to painted run_cli.

    Default is static (print and quit). Pass --live for persistent view.
    """
    from painted import run_cli

    # Default to static — dashboard is a status command, not a TUI.
    # --live must be explicit.
    effective = list(argv)
    if "--live" not in effective and "--static" not in effective:
        effective.append("--static")

    return run_cli(
        effective,
        render=_render,
        fetch=_fetch,
        fetch_stream=_fetch_stream,
        description="Task dashboard",
        prog="strange-loops dashboard",
    )
