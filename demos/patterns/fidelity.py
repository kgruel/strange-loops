#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Fidelity spectrum — same data, four presentations.

Disk usage rendered at every zoom level through run_cli.
The flags drive the output — the code doesn't switch on modes.

    uv run demos/patterns/fidelity.py -q        # one line
    uv run demos/patterns/fidelity.py           # directory list
    uv run demos/patterns/fidelity.py -v        # styled bars
    uv run demos/patterns/fidelity.py -vv       # full detail
    uv run demos/patterns/fidelity.py -vv -i    # interactive tree
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from painted import (
    Block,
    Style,
    CliContext,
    Zoom,
    OutputMode,
    Format,
    border,
    join_vertical,
    join_horizontal,
    pad,
    ROUNDED,
    print_block,
    run_cli,
)
from painted.tui import Surface


# --- Data model ---


def _human_size(n: int) -> str:
    """Format byte count as human-readable string."""
    size: float = n
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}P"


@dataclass(frozen=True)
class DirEntry:
    """A directory or file with its size."""

    name: str
    size_bytes: int
    is_dir: bool = True
    children: tuple["DirEntry", ...] = ()

    @property
    def size_human(self) -> str:
        return _human_size(self.size_bytes)


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


# --- Sample data ---

SAMPLE_DISK = DiskData(
    mount="/home",
    total_bytes=200 * 1024**3,
    used_bytes=134 * 1024**3,
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


# --- Zoom 0: one-line summary ---


def render_minimal(data: DiskData) -> Block:
    return Block.text(
        f"{data.used_percent:.0f}% used ({data.used_human}/{data.total_human})",
        Style(),
    )


# --- Zoom 1: directory list ---


def render_standard(data: DiskData) -> Block:
    rows: list[Block] = [
        Block.text(f"Disk usage: {data.mount}", Style(bold=True)),
        Block.text(
            f"  {data.used_human} / {data.total_human} ({data.used_percent:.1f}% used)",
            Style(),
        ),
        Block.text("", Style()),
        Block.text("Top directories:", Style()),
    ]

    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)
    for entry in sorted_entries[:8]:
        pct = (entry.size_bytes / data.used_bytes) * 100 if data.used_bytes > 0 else 0
        rows.append(Block.text(
            f"  {entry.size_human:>6}  {pct:4.1f}%  {entry.name}", Style(),
        ))

    rows.append(Block.text("", Style()))
    rows.append(Block.text(f"Free: {data.free_human}", Style()))
    return join_vertical(*rows)


# --- Zoom 2: styled bars ---


def _usage_bar(data: DiskData, bar_width: int) -> Block:
    """Overall disk usage bar."""
    filled = int(data.used_percent / 100 * bar_width)

    if data.used_percent > 90:
        bar_style = Style(fg="red", bold=True)
    elif data.used_percent > 75:
        bar_style = Style(fg="yellow")
    else:
        bar_style = Style(fg="green")

    bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
    return join_horizontal(
        Block.text(f"{data.used_percent:5.1f}% ", bar_style),
        Block.text(bar, bar_style),
        Block.text(f" {data.used_human}/{data.total_human}", Style(dim=True)),
    )


def _dir_row(entry: DirEntry, parent_bytes: int, bar_width: int, indent: int = 0) -> Block:
    """Single directory row with size bar."""
    pct = (entry.size_bytes / parent_bytes) * 100 if parent_bytes > 0 else 0

    size_block = Block.text(entry.size_human.rjust(6), Style(bold=True if indent == 0 else False))

    filled = int(pct / 100 * bar_width)
    bar_style = Style(fg="yellow") if pct > 20 else Style(fg="cyan")
    bar = "\u2593" * filled + "\u2591" * (bar_width - filled)

    name_prefix = "  " + "  " * indent
    name_style = Style() if indent == 0 else Style(dim=True)

    return join_horizontal(
        size_block,
        Block.text(" ", Style()),
        Block.text(bar, bar_style),
        Block.text(" ", Style()),
        Block.text(f"{pct:5.1f}%", Style(dim=True)),
        Block.text(f"{name_prefix}{entry.name}", name_style),
    )


def render_styled(data: DiskData, width: int) -> Block:
    """Zoom 2: styled bars, top-level directories only."""
    # Shared bar width for consistent alignment
    bar_width = min(30, width - 30)

    usage = _usage_bar(data, bar_width)
    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)
    rows = [_dir_row(e, data.used_bytes, bar_width) for e in sorted_entries]
    dir_table = join_vertical(*rows)

    # Pad narrower block so both boxes match width
    content_width = max(usage.width, dir_table.width)
    usage_padded = pad(usage, right=content_width - usage.width)
    dir_padded = pad(dir_table, right=content_width - dir_table.width)

    free_style = Style(fg="green" if data.used_percent < 75 else "yellow", bold=True)
    return join_vertical(
        border(usage_padded, title=f"Disk: {data.mount}", chars=ROUNDED),
        Block.text("", Style()),
        border(dir_padded, title="By Directory", chars=ROUNDED),
        Block.text("", Style()),
        Block.text(f"  Free: {data.free_human}  ", free_style),
    )


# --- Zoom 3: full detail with children ---


def render_full(data: DiskData, width: int) -> Block:
    """Zoom 3: styled bars with subdirectories expanded."""
    bar_width = min(30, width - 30)

    usage = _usage_bar(data, bar_width)
    sorted_entries = sorted(data.entries, key=lambda e: e.size_bytes, reverse=True)

    rows: list[Block] = []
    for entry in sorted_entries:
        rows.append(_dir_row(entry, data.used_bytes, bar_width))
        if entry.children:
            sorted_children = sorted(entry.children, key=lambda e: e.size_bytes, reverse=True)
            for child in sorted_children:
                rows.append(_dir_row(child, entry.size_bytes, bar_width, indent=1))

    dir_table = join_vertical(*rows)

    content_width = max(usage.width, dir_table.width)
    usage_padded = pad(usage, right=content_width - usage.width)
    dir_padded = pad(dir_table, right=content_width - dir_table.width)

    free_style = Style(fg="green" if data.used_percent < 75 else "yellow", bold=True)
    return join_vertical(
        border(usage_padded, title=f"Disk: {data.mount}", chars=ROUNDED),
        Block.text("", Style()),
        border(dir_padded, title="By Directory", chars=ROUNDED),
        Block.text("", Style()),
        Block.text(f"  Free: {data.free_human}  ", free_style),
    )


# --- Interactive: TUI tree browser ---


@dataclass
class TreeNode:
    """Mutable tree node for navigation state."""

    entry: DirEntry
    depth: int
    expanded: bool = False
    parent: "TreeNode | None" = None


class DiskSurface(Surface):
    """Interactive TUI with expandable file tree."""

    def __init__(self, data: DiskData):
        super().__init__()
        self._data = data
        self._width = 80
        self._height = 24
        self._nodes: list[TreeNode] = []
        for entry in data.entries:
            self._nodes.append(TreeNode(entry=entry, depth=0))
        self._selected = 0
        self._scroll_offset = 0

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def _visible_nodes(self) -> list[TreeNode]:
        result: list[TreeNode] = []

        def visit(entries: tuple[DirEntry, ...], depth: int, parent: TreeNode | None = None) -> None:
            for entry in sorted(entries, key=lambda e: e.size_bytes, reverse=True):
                node = TreeNode(entry=entry, depth=depth, parent=parent)
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
        header_text = f" Disk Usage: {self._data.mount} ".center(self._width)
        Block.text(header_text, Style(bold=True, fg="cyan", reverse=True)).paint(self._buf, 0, 0)

        # Usage bar
        bar_width = min(30, self._width - 30)
        filled = int(self._data.used_percent / 100 * bar_width)
        bar_style = Style(
            fg="green" if self._data.used_percent < 75
            else "yellow" if self._data.used_percent < 90
            else "red",
        )
        join_horizontal(
            Block.text(f" {self._data.used_percent:.0f}% ", bar_style),
            Block.text("\u2588" * filled + "\u2591" * (bar_width - filled), bar_style),
            Block.text(f" {self._data.used_human}/{self._data.total_human} ", Style(dim=True)),
        ).paint(self._buf, 0, 1)

        # Tree
        visible = self._visible_nodes()
        tree_height = self._height - 6
        tree_width = self._width - 2
        tree_box = border(
            self._render_tree(visible, tree_width, tree_height),
            title="Files", chars=ROUNDED,
        )
        tree_box.paint(self._buf, 0, 3)

        # Footer
        Block.text(
            " j/k: navigate  Enter: expand/collapse  q: quit ",
            Style(dim=True),
        ).paint(self._buf, 0, self._height - 1)

    def _render_tree(self, nodes: list[TreeNode], width: int, height: int) -> Block:
        if not nodes:
            return Block.text("(empty)", Style(dim=True))

        self._selected = max(0, min(self._selected, len(nodes) - 1))

        if self._selected < self._scroll_offset:
            self._scroll_offset = self._selected
        elif self._selected >= self._scroll_offset + height:
            self._scroll_offset = self._selected - height + 1

        rows: list[Block] = []
        for i in range(self._scroll_offset, min(self._scroll_offset + height, len(nodes))):
            node = nodes[i]
            selected = i == self._selected
            indent = "  " * node.depth

            if node.entry.children:
                expand = "\u25bc " if node.expanded else "\u25b6 "
            else:
                expand = "  "

            icon = ("\U0001f4c2" if node.expanded else "\U0001f4c1") if node.entry.is_dir else "\U0001f4c4"
            size = node.entry.size_human.rjust(6)

            if node.depth == 0:
                pct = (node.entry.size_bytes / self._data.used_bytes) * 100
            elif node.parent:
                pct = (node.entry.size_bytes / node.parent.entry.size_bytes) * 100
            else:
                pct = 0

            name_width = width - len(indent) - 2 - 2 - 6 - 8
            name = node.entry.name[:name_width].ljust(name_width)

            if selected:
                row_style = Style(reverse=True)
                row = join_horizontal(
                    Block.text(indent, row_style),
                    Block.text(expand, row_style),
                    Block.text(icon + " ", row_style),
                    Block.text(name, row_style),
                    Block.text(size, row_style),
                    Block.text(f" {pct:4.1f}%", row_style),
                )
            else:
                size_style = (
                    Style(fg="yellow", bold=True) if pct > 30
                    else Style(bold=True) if pct > 10
                    else Style()
                )
                row = join_horizontal(
                    Block.text(indent, Style()),
                    Block.text(expand, Style()),
                    Block.text(icon + " ", Style()),
                    Block.text(name, Style()),
                    Block.text(size, size_style),
                    Block.text(f" {pct:4.1f}%", Style(dim=True)),
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
            if visible and self._selected < len(visible):
                node = visible[self._selected]
                if node.entry.children and not node.expanded:
                    node.expanded = True
            self.mark_dirty()
        elif key in ("h", "left"):
            if visible and self._selected < len(visible):
                node = visible[self._selected]
                if node.expanded:
                    node.expanded = False
                elif node.depth > 0 and node.parent:
                    for i, n in enumerate(visible):
                        if n.entry == node.parent.entry:
                            self._selected = i
                            break
            self.mark_dirty()


# --- run_cli integration ---


def _fetch() -> DiskData:
    return SAMPLE_DISK


def _render(ctx: CliContext, data: DiskData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return render_minimal(data)
    if ctx.zoom == Zoom.SUMMARY:
        return render_standard(data)
    if ctx.zoom == Zoom.FULL:
        return render_full(data, ctx.width)
    return render_styled(data, ctx.width)


def _handle_interactive(ctx: CliContext) -> int:
    data = _fetch()
    if not ctx.is_tty:
        block = _render(ctx, data)
        print_block(block, use_ansi=(ctx.format == Format.ANSI))
        return 0
    surface = DiskSurface(data)
    asyncio.run(surface.run())
    return 0


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        handlers={OutputMode.INTERACTIVE: _handle_interactive},
        description=__doc__,
        prog="fidelity.py",
    )


if __name__ == "__main__":
    sys.exit(main())
