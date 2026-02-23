#!/usr/bin/env python3
"""Lenses — tree and chart data visualization.

Interactive demo showing tree_lens and chart_lens at different zoom levels.
Switch between data sets and adjust zoom to see how the lenses adapt.

Run: uv run python demos/apps/lenses.py

Controls:
  Tab       Toggle between Tree and Chart lens
  +/-       Adjust zoom level
  1-4       Switch data sets
  q         Quit
"""

import asyncio
from dataclasses import dataclass, replace

from fidelis import (
    Block,
    Style,
    join_vertical,
    join_horizontal,
    pad,
    border,
    ROUNDED,
)
from fidelis.tui import Surface
from fidelis.lens import tree_lens, chart_lens, TREE_LENS, CHART_LENS


# ---------------------------------------------------------------------------
# Sample Data Sets
# ---------------------------------------------------------------------------

TREE_DATA = [
    # 1. File system
    {
        "src": {
            "main.py": None,
            "utils": {
                "helpers.py": None,
                "config.py": None,
                "validators.py": None,
            },
            "models": {
                "user.py": None,
                "post.py": None,
            },
        },
        "tests": {
            "test_main.py": None,
            "test_utils.py": None,
        },
        "README.md": None,
    },
    # 2. Organization chart
    ("CEO", {
        "CTO": ("CTO", {
            "Engineering": ("Engineering", ["Alice", "Bob", "Carol"]),
            "DevOps": ("DevOps", ["Dave"]),
        }),
        "CFO": ("CFO", {
            "Finance": ("Finance", ["Eve", "Frank"]),
        }),
        "CMO": ("CMO", {
            "Marketing": ("Marketing", ["Grace", "Henry"]),
            "Sales": ("Sales", ["Ivy", "Jack", "Kate"]),
        }),
    }),
    # 3. Menu structure
    {
        "File": {
            "New": None,
            "Open": None,
            "Save": None,
            "Export": {
                "PDF": None,
                "HTML": None,
                "Markdown": None,
            },
        },
        "Edit": {
            "Undo": None,
            "Redo": None,
            "Cut": None,
            "Copy": None,
            "Paste": None,
        },
        "View": {
            "Zoom In": None,
            "Zoom Out": None,
            "Full Screen": None,
        },
    },
    # 4. AST-like
    ("expr", {
        "binary_op": ("binary_op", {
            "op": "+",
            "left": ("literal", {"value": 42}),
            "right": ("call", {
                "func": "sqrt",
                "args": ("args", [("literal", {"value": 16})]),
            }),
        }),
    }),
]

TREE_LABELS = [
    "File System",
    "Org Chart",
    "Menu Structure",
    "AST Expression",
]

CHART_DATA = [
    # 1. System metrics (percentages)
    {"cpu": 67, "memory": 82, "disk": 45, "network": 23, "gpu": 91},
    # 2. Monthly sales
    {"Jan": 120, "Feb": 145, "Mar": 132, "Apr": 178, "May": 156, "Jun": 189},
    # 3. Response times (ms)
    {"auth": 23, "db": 156, "cache": 3, "api": 89, "render": 45},
    # 4. Sparkline-friendly: hourly traffic
    [12, 15, 23, 45, 67, 89, 95, 87, 76, 65, 54, 48, 52, 61, 73, 82, 78, 65, 43, 32, 25, 18, 14, 11],
]

CHART_LABELS = [
    "System Metrics",
    "Monthly Sales",
    "Response Times",
    "Hourly Traffic",
]


@dataclass(frozen=True)
class AppState:
    """Application state."""

    mode: str = "tree"  # "tree" or "chart"
    zoom: int = 2
    data_index: int = 0
    width: int = 80
    height: int = 24


class LensesApp(Surface):
    def __init__(self):
        super().__init__()
        self._state = AppState()

    def layout(self, width: int, height: int) -> None:
        self._state = replace(self._state, width=width, height=height)

    @property
    def _current_lens(self):
        return TREE_LENS if self._state.mode == "tree" else CHART_LENS

    @property
    def _current_data(self):
        if self._state.mode == "tree":
            return TREE_DATA[self._state.data_index % len(TREE_DATA)]
        return CHART_DATA[self._state.data_index % len(CHART_DATA)]

    @property
    def _current_label(self):
        if self._state.mode == "tree":
            return TREE_LABELS[self._state.data_index % len(TREE_LABELS)]
        return CHART_LABELS[self._state.data_index % len(CHART_LABELS)]

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())

        # Title bar
        mode_name = "Tree Lens" if self._state.mode == "tree" else "Chart Lens"
        title = Block.text(f" {mode_name} Demo ", Style(fg="cyan", bold=True))
        title.paint(self._buf, 2, 1)

        # Mode indicator (tabs)
        tree_style = Style(fg="green", bold=True) if self._state.mode == "tree" else Style(dim=True)
        chart_style = Style(fg="green", bold=True) if self._state.mode == "chart" else Style(dim=True)
        tab1 = Block.text("[Tree]", tree_style)
        tab2 = Block.text("[Chart]", chart_style)
        tabs = join_horizontal(tab1, Block.text("  ", Style()), tab2)
        tabs.paint(self._buf, self._state.width - 20, 1)

        # Zoom indicator
        lens = self._current_lens
        zoom_text = f"Zoom: {self._state.zoom}/{lens.max_zoom}"
        zoom_block = Block.text(zoom_text, Style(fg="yellow", bold=True))
        zoom_block.paint(self._buf, 2, 3)

        # Zoom bar
        bar_chars = []
        for i in range(lens.max_zoom + 1):
            if i == self._state.zoom:
                bar_chars.append("*")
            else:
                bar_chars.append("-")
        bar_text = "[" + "".join(bar_chars) + "]"
        bar_block = Block.text(bar_text, Style(fg="green"))
        bar_block.paint(self._buf, 16, 3)

        # Data set indicator
        data_label = self._current_label
        idx = self._state.data_index + 1
        total = len(TREE_DATA) if self._state.mode == "tree" else len(CHART_DATA)
        data_text = f"Data: {idx}/{total} - {data_label}"
        data_block = Block.text(data_text, Style(fg="magenta"))
        data_block.paint(self._buf, 2, 4)

        # Render content
        content_width = max(40, self._state.width - 10)
        content_height = self._state.height - 12

        render_fn = tree_lens if self._state.mode == "tree" else chart_lens
        content_block = render_fn(self._current_data, self._state.zoom, content_width)

        # Wrap in border with data label
        content_block = pad(content_block, left=1, right=1, top=0, bottom=0)
        content_block = border(content_block, ROUNDED, Style(fg="blue"), title=data_label)

        content_block.paint(self._buf, 4, 6)

        # Instructions
        instructions = [
            Block.text("Tab    toggle Tree/Chart", Style(dim=True)),
            Block.text("+/-    change zoom", Style(dim=True)),
            Block.text("1-4    switch data set", Style(dim=True)),
            Block.text("q      quit", Style(dim=True)),
        ]
        y = self._state.height - 5
        for inst in instructions:
            inst.paint(self._buf, 4, y)
            y += 1

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return

        # Toggle mode
        if key == "tab":
            new_mode = "chart" if self._state.mode == "tree" else "tree"
            # Reset zoom to reasonable default for new mode
            max_zoom = CHART_LENS.max_zoom if new_mode == "chart" else TREE_LENS.max_zoom
            new_zoom = min(self._state.zoom, max_zoom)
            self._state = replace(self._state, mode=new_mode, zoom=new_zoom, data_index=0)
            return

        # Zoom
        if key in ("+", "="):
            max_zoom = self._current_lens.max_zoom
            new_zoom = min(max_zoom, self._state.zoom + 1)
            self._state = replace(self._state, zoom=new_zoom)
            return

        if key in ("-", "_"):
            new_zoom = max(0, self._state.zoom - 1)
            self._state = replace(self._state, zoom=new_zoom)
            return

        # Data set selection
        if key in "1234":
            idx = int(key) - 1
            max_idx = len(TREE_DATA) if self._state.mode == "tree" else len(CHART_DATA)
            if idx < max_idx:
                self._state = replace(self._state, data_index=idx)
            return


if __name__ == "__main__":
    asyncio.run(LensesApp().run())
