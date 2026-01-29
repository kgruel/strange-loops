#!/usr/bin/env python3
"""Disk usage at different verbosity levels.

Demonstrates the verbosity spectrum with hierarchical data:

    uv run python demos/cells/demo_verbosity_disk.py -q     # "67% used (134G/200G)"
    uv run python demos/cells/demo_verbosity_disk.py        # Top directories list
    uv run python demos/cells/demo_verbosity_disk.py -v     # Styled bars per directory
    uv run python demos/cells/demo_verbosity_disk.py -vv    # TUI file tree browser

The TUI mode shows a navigable tree with expandable directories.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

from cells import (
    Block,
    Style,
    Surface,
    border,
    join_vertical,
    join_horizontal,
    ROUNDED,
)
from cells.writer import print_block


@dataclass(frozen=True)
class DirEntry:
    """A directory or file with its size."""

    name: str
    size_bytes: int
    is_dir: bool = True
    children: tuple["DirEntry", ...] = ()

    @property
    def size_human(self) -> str:
        """Human-readable size."""
        size = self.size_bytes
        for unit in ("B", "K", "M", "G", "T"):
            if size < 1024:
                if unit == "B":
                    return f"{size}{unit}"
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}P"


@dataclass(frozen=True)
class DiskData:
    """Disk usage summary."""

    mount: str
    total_bytes: int
    used_bytes: int
    entries: tuple[DirEntry, ...]

    @property
    def free_bytes(self) -> int:
        return self.total_bytes - self.used_bytes

    @property
    def used_percent(self) -> float:
        return (self.used_bytes / self.total_bytes) * 100 if self.total_bytes > 0 else 0

    @property
    def total_human(self) -> str:
        return _human_size(self.total_bytes)

    @property
    def used_human(self) -> str:
        return _human_size(self.used_bytes)

    @property
    def free_human(self) -> str:
        return _human_size(self.free_bytes)


def _human_size(size: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            if unit == "B":
                return f"{size}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}P"


# Sample disk data (simulating /home)
SAMPLE_DISK = DiskData(
    mount="/home",
    total_bytes=200 * 1024**3,  # 200G
    used_bytes=134 * 1024**3,  # 134G
    entries=(
        DirEntry(
            "projects",
            45 * 1024**3,
            children=(
                DirEntry("prism", 12 * 1024**3, children=(
                    DirEntry("libs", 3 * 1024**3),
                    DirEntry("experiments", 2 * 1024**3),
                    DirEntry(".venv", 5 * 1024**3),
                    DirEntry("node_modules", 2 * 1024**3),
                )),
                DirEntry("website", 8 * 1024**3),
                DirEntry("ml-research", 15 * 1024**3),
                DirEntry("archive", 10 * 1024**3),
            ),
        ),
        DirEntry(
            "downloads",
            28 * 1024**3,
            children=(
                DirEntry("installers", 12 * 1024**3),
                DirEntry("datasets", 10 * 1024**3),
                DirEntry("misc", 6 * 1024**3),
            ),
        ),
        DirEntry(
            ".cache",
            22 * 1024**3,
            children=(
                DirEntry("pip", 8 * 1024**3),
                DirEntry("huggingface", 10 * 1024**3),
                DirEntry("uv", 4 * 1024**3),
            ),
        ),
        DirEntry("documents", 18 * 1024**3),
        DirEntry("pictures", 12 * 1024**3),
        DirEntry(".local", 9 * 1024**3),
    ),
)


def terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


# ============================================================================
# Level 0: Quiet — one line summary
# ============================================================================


def render_quiet(data: DiskData) -> str:
    """Level 0: Minimal one-line output."""
    return f"{data.used_percent:.0f}% used ({data.used_human}/{data.total_human})"


# ============================================================================
# Level 1: Standard — multi-line text output
# ============================================================================


def render_standard(data: DiskData) -> str:
    """Level 1: Standard CLI output."""
    lines = [
        f"Disk usage: {data.mount}",
        f"  {data.used_human} / {data.total_human} ({data.used_percent:.1f}% used)",
        "",
        "Top directories:",
    ]

    # Sort by size descending
    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)

    for entry in sorted_entries[:8]:
        pct = (entry.size_bytes / data.used_bytes) * 100 if data.used_bytes > 0 else 0
        lines.append(f"  {entry.size_human:>6}  {pct:4.1f}%  {entry.name}")

    lines.append("")
    lines.append(f"Free: {data.free_human}")

    return "\n".join(lines)


# ============================================================================
# Level 2: Verbose — styled Block output with bars
# ============================================================================


def render_verbose(data: DiskData, width: int) -> Block:
    """Level 2: Styled output with visual bars."""
    sections: list[Block] = []

    # Overall usage bar
    bar_width = min(40, width - 20)
    filled = int(data.used_percent / 100 * bar_width)

    if data.used_percent > 90:
        bar_style = Style(fg="red", bold=True)
    elif data.used_percent > 75:
        bar_style = Style(fg="yellow")
    else:
        bar_style = Style(fg="green")

    bar = "█" * filled + "░" * (bar_width - filled)
    usage_line = join_horizontal(
        Block.text(f"{data.used_percent:5.1f}% ", bar_style),
        Block.text(bar, bar_style),
        Block.text(f" {data.used_human}/{data.total_human}", Style(dim=True)),
    )
    usage_box = border(usage_line, title=f"Disk: {data.mount}", chars=ROUNDED)
    sections.append(usage_box)

    # Directory breakdown
    rows: list[Block] = []
    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)
    max_name_len = max(len(e.name) for e in sorted_entries)

    for entry in sorted_entries:
        pct = (entry.size_bytes / data.used_bytes) * 100 if data.used_bytes > 0 else 0

        # Size
        size_block = Block.text(entry.size_human.rjust(6), Style(bold=True))

        # Percentage bar
        entry_bar_width = 20
        entry_filled = int(pct / 100 * entry_bar_width)

        if pct > 20:
            entry_bar_style = Style(fg="yellow")
        else:
            entry_bar_style = Style(fg="cyan")

        entry_bar = "▓" * entry_filled + "░" * (entry_bar_width - entry_filled)
        bar_block = Block.text(entry_bar, entry_bar_style)

        # Percentage
        pct_block = Block.text(f"{pct:5.1f}%", Style(dim=True))

        # Name
        name_block = Block.text(f"  {entry.name}", Style())

        row = join_horizontal(size_block, Block.text(" ", Style()), bar_block, Block.text(" ", Style()), pct_block, name_block)
        rows.append(row)

    dir_table = join_vertical(*rows)
    dir_box = border(dir_table, title="By Directory", chars=ROUNDED)
    sections.append(dir_box)

    # Free space
    free_style = Style(fg="green" if data.used_percent < 75 else "yellow", bold=True)
    free_block = Block.text(f"  Free: {data.free_human}  ", free_style)
    sections.append(free_block)

    return join_vertical(*sections, gap=1)


# ============================================================================
# Level 3: Interactive — TUI file tree browser
# ============================================================================


@dataclass
class TreeNode:
    """Mutable tree node for navigation state."""

    entry: DirEntry
    depth: int
    expanded: bool = False
    parent: "TreeNode | None" = None


class DiskSurface(Surface):
    """Level 3: Interactive TUI with expandable tree."""

    def __init__(self, data: DiskData):
        super().__init__()
        self._data = data
        self._width = 80
        self._height = 24

        # Build flat list of visible nodes
        self._nodes: list[TreeNode] = []
        for entry in data.entries:
            self._nodes.append(TreeNode(entry=entry, depth=0))

        self._selected = 0
        self._scroll_offset = 0

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def _visible_nodes(self) -> list[TreeNode]:
        """Get flat list of currently visible nodes (respecting expand state)."""
        result: list[TreeNode] = []

        def visit(entries: tuple[DirEntry, ...], depth: int, parent: TreeNode | None = None) -> None:
            for entry in sorted(entries, key=lambda e: e.size_bytes, reverse=True):
                node = TreeNode(entry=entry, depth=depth, parent=parent)
                # Check if this node was previously expanded
                for n in self._nodes:
                    if n.entry.name == entry.name and n.depth == depth:
                        node.expanded = n.expanded
                        break
                result.append(node)
                if node.expanded and entry.children:
                    visit(entry.children, depth + 1, node)

        visit(self._data.entries, 0)
        self._nodes = result
        return result

    def render(self) -> None:
        if self._buf is None:
            return

        self._buf.fill(0, 0, self._width, self._height, " ", Style())

        # Header
        header_style = Style(bold=True, fg="cyan", reverse=True)
        header_text = f" Disk Usage: {self._data.mount} ".center(self._width)
        header = Block.text(header_text, header_style)
        header.paint(self._buf, 0, 0)

        # Overall usage bar (compact)
        bar_width = min(30, self._width - 30)
        filled = int(self._data.used_percent / 100 * bar_width)
        bar_style = Style(fg="green" if self._data.used_percent < 75 else "yellow" if self._data.used_percent < 90 else "red")
        bar = "█" * filled + "░" * (bar_width - filled)
        usage = join_horizontal(
            Block.text(f" {self._data.used_percent:.0f}% ", bar_style),
            Block.text(bar, bar_style),
            Block.text(f" {self._data.used_human}/{self._data.total_human} ", Style(dim=True)),
        )
        usage.paint(self._buf, 0, 1)

        # Tree view
        visible = self._visible_nodes()
        tree_height = self._height - 6
        tree_width = self._width - 2

        tree_block = self._render_tree(visible, tree_width, tree_height)
        tree_box = border(tree_block, title="Files", chars=ROUNDED)
        tree_box.paint(self._buf, 0, 3)

        # Footer
        footer_style = Style(dim=True)
        footer = Block.text(" j/k: navigate  Enter: expand/collapse  q: quit ", footer_style)
        footer.paint(self._buf, 0, self._height - 1)

    def _render_tree(self, nodes: list[TreeNode], width: int, height: int) -> Block:
        """Render the tree view."""
        if not nodes:
            return Block.text("(empty)", Style(dim=True))

        # Clamp selection
        if self._selected >= len(nodes):
            self._selected = len(nodes) - 1
        if self._selected < 0:
            self._selected = 0

        # Scroll into view
        if self._selected < self._scroll_offset:
            self._scroll_offset = self._selected
        elif self._selected >= self._scroll_offset + height:
            self._scroll_offset = self._selected - height + 1

        rows: list[Block] = []
        for i in range(self._scroll_offset, min(self._scroll_offset + height, len(nodes))):
            node = nodes[i]
            selected = i == self._selected

            # Indent
            indent = "  " * node.depth

            # Expand indicator
            if node.entry.children:
                if node.expanded:
                    expand = "▼ "
                else:
                    expand = "▶ "
            else:
                expand = "  "

            # Icon
            if node.entry.is_dir:
                icon = "📁" if not node.expanded else "📂"
            else:
                icon = "📄"

            # Size
            size = node.entry.size_human.rjust(6)

            # Percentage of parent or total
            if node.depth == 0:
                pct = (node.entry.size_bytes / self._data.used_bytes) * 100
            else:
                # Find parent size
                parent = node.parent
                if parent:
                    pct = (node.entry.size_bytes / parent.entry.size_bytes) * 100
                else:
                    pct = 0

            # Build row
            name_width = width - len(indent) - 2 - 2 - 6 - 8
            name = node.entry.name[:name_width].ljust(name_width)

            if selected:
                row_style = Style(reverse=True)
                size_style = Style(bold=True, reverse=True)
            else:
                row_style = Style()
                if pct > 30:
                    size_style = Style(fg="yellow", bold=True)
                elif pct > 10:
                    size_style = Style(bold=True)
                else:
                    size_style = Style()

            row = join_horizontal(
                Block.text(indent, row_style),
                Block.text(expand, row_style),
                Block.text(icon + " ", row_style),
                Block.text(name, row_style),
                Block.text(size, size_style if not selected else row_style),
                Block.text(f" {pct:4.1f}%", Style(dim=True) if not selected else row_style),
            )
            rows.append(row)

        return join_vertical(*rows)

    def on_key(self, key: str) -> None:
        visible = self._visible_nodes()

        if key == "q":
            self.quit()
        elif key in ("j", "down"):
            if self._selected < len(visible) - 1:
                self._selected += 1
            self.mark_dirty()
        elif key in ("k", "up"):
            if self._selected > 0:
                self._selected -= 1
            self.mark_dirty()
        elif key == "enter":
            if visible and self._selected < len(visible):
                node = visible[self._selected]
                if node.entry.children:
                    node.expanded = not node.expanded
            self.mark_dirty()
        elif key in ("l", "right"):
            # Expand
            if visible and self._selected < len(visible):
                node = visible[self._selected]
                if node.entry.children and not node.expanded:
                    node.expanded = True
            self.mark_dirty()
        elif key in ("h", "left"):
            # Collapse or go to parent
            if visible and self._selected < len(visible):
                node = visible[self._selected]
                if node.expanded:
                    node.expanded = False
                elif node.depth > 0:
                    # Find parent index
                    for i, n in enumerate(visible):
                        if n.entry == node.parent.entry if node.parent else False:
                            self._selected = i
                            break
            self.mark_dirty()


def run_interactive(data: DiskData) -> None:
    """Level 3: Launch the interactive TUI."""
    surface = DiskSurface(data)
    asyncio.run(surface.run())


# ============================================================================
# Main entry point
# ============================================================================


def parse_verbosity(args: list[str]) -> int:
    """Parse verbosity level from args."""
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

    verbosity = parse_verbosity(args)
    width = terminal_width()

    if verbosity == 0:
        print(render_quiet(SAMPLE_DISK))
    elif verbosity == 1:
        print(render_standard(SAMPLE_DISK))
    elif verbosity == 2:
        block = render_verbose(SAMPLE_DISK, width)
        print_block(block)
    else:
        if is_interactive():
            run_interactive(SAMPLE_DISK)
        else:
            block = render_verbose(SAMPLE_DISK, width)
            print_block(block)

    return 0


if __name__ == "__main__":
    sys.exit(main())
