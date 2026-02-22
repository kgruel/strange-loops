#!/usr/bin/env python3
"""Fidelity spectrum — same data, four presentations.

This demo shows how cells enables the CLI→TUI continuum. Run with different
fidelity flags to see the same task data rendered at each level:

    uv run python demos/cells/patterns/fidelity.py -q     # Level 0: one line
    uv run python demos/cells/patterns/fidelity.py        # Level 1: standard output
    uv run python demos/cells/patterns/fidelity.py -v     # Level 2: styled output
    uv run python demos/cells/patterns/fidelity.py -vv    # Level 3: interactive TUI

The demo simulates a task runner showing build status. The same underlying
TaskData structure drives all four presentations.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum

from fidelis import (
    Block,
    Style,
    border,
    join_vertical,
    join_horizontal,
    pad,
    ROUNDED,
    print_block,
)
from fidelis.tui import Surface
from fidelis.widgets import (
    ListState,
    SpinnerState,
    DOTS,
    spinner,
)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskData:
    """A single task in the build pipeline."""

    name: str
    status: TaskStatus
    duration_ms: int | None = None
    message: str | None = None


@dataclass(frozen=True)
class BuildData:
    """Complete build status."""

    name: str
    tasks: tuple[TaskData, ...]

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.SUCCESS)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)

    @property
    def running(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.RUNNING)

    @property
    def total_duration_ms(self) -> int:
        return sum(t.duration_ms or 0 for t in self.tasks)


# Sample build data
SAMPLE_BUILD = BuildData(
    name="loops",
    tasks=(
        TaskData("lint", TaskStatus.SUCCESS, 234),
        TaskData("typecheck", TaskStatus.SUCCESS, 1892),
        TaskData("test:unit", TaskStatus.SUCCESS, 3421),
        TaskData("test:integration", TaskStatus.FAILED, 8234, "Connection refused"),
        TaskData("build", TaskStatus.PENDING),
        TaskData("deploy", TaskStatus.PENDING),
    ),
)


def terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


# ============================================================================
# Level 0: Minimal — one line summary
# ============================================================================


def render_minimal(data: BuildData) -> str:
    """Level 0: Minimal one-line output."""
    if data.failed > 0:
        return f"{data.name}: {data.failed} failed, {data.passed} passed"
    return f"{data.name}: {data.passed} passed"


# ============================================================================
# Level 1: Standard — multi-line text output
# ============================================================================


def render_standard(data: BuildData) -> str:
    """Level 1: Standard CLI output."""
    lines = [f"Build: {data.name}", ""]

    for task in data.tasks:
        if task.status == TaskStatus.SUCCESS:
            mark = "✓"
        elif task.status == TaskStatus.FAILED:
            mark = "✗"
        elif task.status == TaskStatus.RUNNING:
            mark = "◐"
        else:
            mark = "○"

        line = f"  {mark} {task.name}"
        if task.duration_ms:
            line += f" ({task.duration_ms}ms)"
        if task.message:
            line += f" — {task.message}"
        lines.append(line)

    lines.append("")
    if data.failed > 0:
        lines.append(f"Failed: {data.failed}/{len(data.tasks)}")
    else:
        lines.append(f"Passed: {data.passed}/{len(data.tasks)}")

    return "\n".join(lines)


# ============================================================================
# Level 2: Styled — styled Block output
# ============================================================================


def render_styled(data: BuildData, width: int) -> Block:
    """Level 2: Styled output with borders and colors."""
    task_rows: list[Block] = []

    for task in data.tasks:
        # Status indicator
        if task.status == TaskStatus.SUCCESS:
            mark = Block.text("✓", Style(fg="green", bold=True))
        elif task.status == TaskStatus.FAILED:
            mark = Block.text("✗", Style(fg="red", bold=True))
        elif task.status == TaskStatus.RUNNING:
            mark = Block.text("◐", Style(fg="yellow", bold=True))
        else:
            mark = Block.text("○", Style(dim=True))

        # Task name
        name_style = Style(bold=True) if task.status == TaskStatus.RUNNING else Style()
        name = Block.text(f" {task.name}".ljust(20), name_style)

        # Duration
        if task.duration_ms:
            dur_text = f"{task.duration_ms}ms".rjust(8)
            dur = Block.text(dur_text, Style(dim=True))
        else:
            dur = Block.text(" " * 8, Style())

        # Message
        if task.message:
            msg = Block.text(f"  {task.message}", Style(fg="red", dim=True))
            row = join_horizontal(mark, name, dur, msg)
        else:
            row = join_horizontal(mark, name, dur)

        task_rows.append(row)

    tasks_block = join_vertical(*task_rows)
    tasks_box = border(tasks_block, title=f"Build: {data.name}", chars=ROUNDED)

    # Summary
    if data.failed > 0:
        summary_style = Style(fg="red", bold=True)
        summary_text = f"  {data.failed} failed, {data.passed} passed  "
    else:
        summary_style = Style(fg="green", bold=True)
        summary_text = f"  {data.passed} passed  "

    total_ms = data.total_duration_ms
    if total_ms > 1000:
        summary_text += f"({total_ms / 1000:.1f}s)"
    else:
        summary_text += f"({total_ms}ms)"

    summary = Block.text(summary_text, summary_style)

    return join_vertical(tasks_box, summary, gap=1)


# ============================================================================
# Level 3: Interactive — full TUI
# ============================================================================


class BuildSurface(Surface):
    """Level 3: Interactive TUI for exploring build results."""

    def __init__(self, data: BuildData):
        super().__init__()
        self._data = data
        self._list_state = ListState(
            selected=0,
            scroll_offset=0,
            item_count=len(data.tasks),
        )
        self._spinner = SpinnerState(frames=DOTS)
        self._width = 80
        self._height = 24

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def update(self) -> None:
        # Animate spinner for running tasks
        if self._data.running > 0:
            self._spinner = self._spinner.tick()
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        self._buf.fill(0, 0, self._width, self._height, " ", Style())

        # Header
        if self._data.failed > 0:
            header_style = Style(bold=True, fg="red", reverse=True)
        else:
            header_style = Style(bold=True, fg="green", reverse=True)

        header_text = f" Build: {self._data.name} ".center(self._width)
        header = Block.text(header_text, header_style)
        header.paint(self._buf, 0, 0)

        # Task list (left side)
        list_width = 40
        detail_width = self._width - list_width - 3

        tasks_block = self._render_task_list(list_width - 2)
        tasks_box = border(tasks_block, title="Tasks", chars=ROUNDED)
        tasks_box.paint(self._buf, 0, 2)

        # Detail panel (right side)
        detail_block = self._render_detail(detail_width - 2)
        detail_box = border(detail_block, title="Details", chars=ROUNDED)
        detail_box.paint(self._buf, list_width + 2, 2)

        # Summary bar
        summary = self._render_summary()
        summary.paint(self._buf, 0, self._height - 3)

        # Footer
        footer_style = Style(dim=True)
        footer = Block.text(" j/k: navigate  r: rerun  q: quit ", footer_style)
        footer.paint(self._buf, 0, self._height - 1)

    def _render_task_list(self, width: int) -> Block:
        """Render the task list with selection."""
        rows: list[Block] = []

        for i, task in enumerate(self._data.tasks):
            selected = i == self._list_state.selected

            # Status indicator
            if task.status == TaskStatus.SUCCESS:
                mark = "✓"
                mark_style = Style(fg="green", bold=True)
            elif task.status == TaskStatus.FAILED:
                mark = "✗"
                mark_style = Style(fg="red", bold=True)
            elif task.status == TaskStatus.RUNNING:
                # Use animated spinner
                mark = spinner(self._spinner).row(0)[0].char
                mark_style = Style(fg="yellow", bold=True)
            else:
                mark = "○"
                mark_style = Style(dim=True)

            if selected:
                row_style = Style(reverse=True)
                prefix = "▸ "
            else:
                row_style = Style()
                prefix = "  "

            # Build the row
            mark_block = Block.text(mark, mark_style)
            name_text = f" {task.name}".ljust(width - 4)
            name_block = Block.text(name_text, row_style)

            row = join_horizontal(
                Block.text(prefix, row_style),
                mark_block,
                name_block,
            )
            rows.append(row)

        return join_vertical(*rows)

    def _render_detail(self, width: int) -> Block:
        """Render details for the selected task."""
        task = self._data.tasks[self._list_state.selected]

        lines: list[Block] = []

        # Task name
        lines.append(Block.text(task.name, Style(bold=True, fg="cyan")))
        lines.append(Block.empty(width, 1))

        # Status
        if task.status == TaskStatus.SUCCESS:
            status_text = "Passed"
            status_style = Style(fg="green")
        elif task.status == TaskStatus.FAILED:
            status_text = "Failed"
            status_style = Style(fg="red")
        elif task.status == TaskStatus.RUNNING:
            status_text = "Running..."
            status_style = Style(fg="yellow")
        else:
            status_text = "Pending"
            status_style = Style(dim=True)

        lines.append(
            join_horizontal(
                Block.text("Status:   ", Style(bold=True)),
                Block.text(status_text, status_style),
            )
        )

        # Duration
        if task.duration_ms:
            dur = task.duration_ms
            if dur > 1000:
                dur_text = f"{dur / 1000:.2f}s"
            else:
                dur_text = f"{dur}ms"
            lines.append(
                join_horizontal(
                    Block.text("Duration: ", Style(bold=True)),
                    Block.text(dur_text, Style()),
                )
            )

        # Error message
        if task.message:
            lines.append(Block.empty(width, 1))
            lines.append(Block.text("Error:", Style(bold=True, fg="red")))
            lines.append(Block.text(f"  {task.message}", Style(fg="red")))

        return join_vertical(*lines)

    def _render_summary(self) -> Block:
        """Render the summary bar."""
        parts: list[Block] = []

        if self._data.passed > 0:
            parts.append(Block.text(f" {self._data.passed} passed ", Style(fg="green")))
        if self._data.failed > 0:
            parts.append(Block.text(f" {self._data.failed} failed ", Style(fg="red")))
        if self._data.running > 0:
            parts.append(Block.text(f" {self._data.running} running ", Style(fg="yellow")))

        pending = len(self._data.tasks) - self._data.passed - self._data.failed - self._data.running
        if pending > 0:
            parts.append(Block.text(f" {pending} pending ", Style(dim=True)))

        total_ms = self._data.total_duration_ms
        if total_ms > 1000:
            time_text = f" Total: {total_ms / 1000:.1f}s "
        else:
            time_text = f" Total: {total_ms}ms "
        parts.append(Block.text(time_text, Style(bold=True)))

        return join_horizontal(*parts)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key in ("j", "down"):
            self._list_state = self._list_state.move_down()
            self.mark_dirty()
        elif key in ("k", "up"):
            self._list_state = self._list_state.move_up()
            self.mark_dirty()
        elif key == "r":
            # Would trigger rerun in real app
            pass


def run_interactive(data: BuildData) -> None:
    """Level 3: Launch the interactive TUI."""
    surface = BuildSurface(data)
    asyncio.run(surface.run())


# ============================================================================
# Main entry point
# ============================================================================


def parse_fidelity(args: list[str]) -> int:
    """Parse fidelity level from args."""
    if "-q" in args or "--quiet" in args:
        return 0
    v_count = 0
    for arg in args:
        if arg == "-vv":
            return 3
        elif arg == "-v" or arg == "--verbose":
            v_count += 1
    return min(v_count + 1, 3)


def is_interactive() -> bool:
    return sys.stdout.isatty()


def main() -> int:
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0

    fidelity = parse_fidelity(args)
    width = terminal_width()

    if fidelity == 0:
        # Level 0: Minimal
        print(render_minimal(SAMPLE_BUILD))

    elif fidelity == 1:
        # Level 1: Standard multi-line
        print(render_standard(SAMPLE_BUILD))

    elif fidelity == 2:
        # Level 2: Styled blocks
        block = render_styled(SAMPLE_BUILD, width)
        print_block(block)

    else:
        # Level 3: Interactive TUI
        if is_interactive():
            run_interactive(SAMPLE_BUILD)
        else:
            # Fall back to styled if not a TTY
            block = render_styled(SAMPLE_BUILD, width)
            print_block(block)

    return 1 if SAMPLE_BUILD.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
