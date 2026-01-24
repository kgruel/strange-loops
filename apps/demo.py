"""Progressive interactive demo: a walkthrough of the render framework.

Run: uv run python -m apps.demo
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace, field

from render.app import RenderApp
from render.block import Block
from render.cell import Style, Cell
from render.compose import join_horizontal, join_vertical, pad, border, Align
from render.borders import ROUNDED, HEAVY, DOUBLE, LIGHT
from render.components import (
    ListState, SpinnerState, SpinnerFrames,
    DOTS, BRAILLE, LINE,
    Column, TableState,
    list_view, spinner, table,
)
from render.region import Region
from render.span import Span, Line
from render.theme import (
    HEADER_BG, FOOTER_BG,
    HEADER_BASE, HEADER_DIM, HEADER_TARGET, HEADER_CONNECTED, HEADER_SPINNER,
    FOOTER_BASE, FOOTER_KEY, FOOTER_SEPARATOR,
    LEVEL_STYLES, LEVEL_NAMES,
    SELECTION_CURSOR, SELECTION_HIGHLIGHT, SOURCE_DIM,
)


# -- Constants --

STAGE_TITLES = [
    "Welcome",
    "Spans",
    "Lines",
    "Theme",
    "Blocks",
    "Components",
    "Finale",
]

NUM_STAGES = len(STAGE_TITLES)

# Demo-specific styles (only what theme.py doesn't provide)
TITLE_STYLE = Style(fg="cyan", bold=True)
SUBTITLE_STYLE = Style(fg="white", dim=True)
ACCENT = Style(fg="magenta", bold=True)
DIM = Style(dim=True)
CAPTION_STYLE = Style(fg="white", italic=True)
NAV_KEY = Style(fg="cyan", bold=True)
NAV_TEXT = Style(dim=True)
STAGE_DOT_ACTIVE = Style(fg="cyan", bold=True)
STAGE_DOT_INACTIVE = Style(dim=True)


# -- State --

@dataclass(frozen=True)
class DemoState:
    """Application state for the demo walkthrough."""
    stage: int = 0
    list_state: ListState = field(default_factory=lambda: ListState(item_count=5))
    table_state: TableState = field(default_factory=lambda: TableState(row_count=5))
    spinner_state: SpinnerState = field(default_factory=SpinnerState)
    spinner_braille: SpinnerState = field(default_factory=lambda: SpinnerState(frames=BRAILLE))
    spinner_line: SpinnerState = field(default_factory=lambda: SpinnerState(frames=LINE))


# -- Stage Renderers --

def _render_title(width: int, height: int) -> Block:
    """Stage 0: Welcome screen."""
    lines: list[Block] = []

    lines.append(Block.empty(width, 2))

    # ASCII art-ish title
    title_text = "~ r e n d e r ~"
    lines.append(_centered_text(title_text, width, TITLE_STYLE))
    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("A cell-buffer terminal UI framework", width, SUBTITLE_STYLE))
    lines.append(Block.empty(width, 2))
    lines.append(_centered_text("You're looking at a demo built entirely with the thing it demos.", width, CAPTION_STYLE))
    lines.append(_centered_text("Spans, Lines, Blocks, Borders, Components — all the way down.", width, CAPTION_STYLE))
    lines.append(Block.empty(width, 2))
    lines.append(_centered_text("→  to begin", width, NAV_TEXT))

    return join_vertical(*lines, align=Align.CENTER)


def _render_spans(width: int, height: int) -> Block:
    """Stage 1: Styled text atoms."""
    lines: list[Block] = []

    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("Spans: styled text atoms", width, TITLE_STYLE))
    lines.append(Block.empty(width, 1))

    # Show various styles
    demos = [
        ("Bold", Style(bold=True)),
        ("Dim", Style(dim=True)),
        ("Italic", Style(italic=True)),
        ("Underline", Style(underline=True)),
        ("Reverse", Style(reverse=True)),
        ("Red", Style(fg="red")),
        ("Green", Style(fg="green")),
        ("Blue", Style(fg="blue")),
        ("Cyan", Style(fg="cyan")),
        ("Magenta", Style(fg="magenta")),
        ("Yellow", Style(fg="yellow")),
        ("#ff6b35", Style(fg="#ff6b35")),
        ("#7b68ee", Style(fg="#7b68ee")),
        ("Bold+Cyan", Style(fg="cyan", bold=True)),
        ("Dim+Italic", Style(dim=True, italic=True)),
    ]

    # Lay them out in rows of ~4
    row_blocks: list[Block] = []
    for label, style in demos:
        span_block = Block.text(f" {label} ", style)
        row_blocks.append(span_block)

    # Chunk into rows
    per_row = 5
    for i in range(0, len(row_blocks), per_row):
        chunk = row_blocks[i:i + per_row]
        row = join_horizontal(*chunk, gap=2)
        lines.append(pad(row, left=(width - row.width) // 2, top=0))

    lines.append(Block.empty(width, 2))
    lines.append(_centered_text("Each Span is a run of text + a Style.", width, CAPTION_STYLE))
    lines.append(_centered_text("Style: fg, bg, bold, dim, italic, underline, reverse.", width, DIM))

    return join_vertical(*lines, align=Align.START)


def _render_lines(width: int, height: int) -> Block:
    """Stage 2: Line composition."""
    lines: list[Block] = []

    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("Lines: composing spans", width, TITLE_STYLE))
    lines.append(Block.empty(width, 1))

    # Line.plain()
    lines.append(_left_text("  Line.plain(\"Hello, world!\")", width, DIM))
    plain_line = Line.plain("Hello, world!")
    lines.append(_line_to_block(plain_line, width, indent=4))
    lines.append(Block.empty(width, 1))

    # Multi-span Line
    lines.append(_left_text("  Line with multiple styled Spans:", width, DIM))
    multi_line = Line(spans=(
        Span("status", Style(fg="cyan", bold=True)),
        Span(": ", Style(dim=True)),
        Span("running", Style(fg="green")),
        Span(" | ", Style(dim=True)),
        Span("pid", Style(fg="cyan", bold=True)),
        Span(": ", Style(dim=True)),
        Span("42069", Style(fg="yellow")),
    ))
    lines.append(_line_to_block(multi_line, width, indent=4))
    lines.append(Block.empty(width, 1))

    # Another multi-span example
    lines.append(_left_text("  Styled log line:", width, DIM))
    log_line = Line(spans=(
        Span("12:34:56 ", Style(dim=True)),
        Span("ERROR", Style(fg="red", bold=True)),
        Span(" ", Style()),
        Span("connection refused", Style(fg="white")),
        Span(" (attempt 3/5)", Style(dim=True, italic=True)),
    ))
    lines.append(_line_to_block(log_line, width, indent=4))
    lines.append(Block.empty(width, 2))

    lines.append(_centered_text("A Line is a tuple of Spans. One style per Span, one line per Line.", width, CAPTION_STYLE))

    return join_vertical(*lines, align=Align.START)


def _render_theme(width: int, height: int) -> Block:
    """Stage 3: Theme palette sampler."""
    lines: list[Block] = []

    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("Theme: named styles from render/theme.py", width, TITLE_STYLE))
    lines.append(Block.empty(width, 1))

    # Show theme categories
    categories = [
        ("Header", [
            ("HEADER_BASE", HEADER_BASE),
            ("HEADER_DIM", HEADER_DIM),
            ("HEADER_TARGET", HEADER_TARGET),
            ("HEADER_CONNECTED", HEADER_CONNECTED),
            ("HEADER_SPINNER", HEADER_SPINNER),
        ]),
        ("Footer", [
            ("FOOTER_BASE", FOOTER_BASE),
            ("FOOTER_KEY", FOOTER_KEY),
            ("FOOTER_SEPARATOR", FOOTER_SEPARATOR),
        ]),
        ("Levels", [
            ("error", LEVEL_STYLES["error"]),
            ("warn", LEVEL_STYLES["warn"]),
            ("info", LEVEL_STYLES["info"]),
            ("debug", LEVEL_STYLES["debug"]),
            ("trace", LEVEL_STYLES["trace"]),
        ]),
        ("Selection", [
            ("CURSOR", SELECTION_CURSOR),
            ("HIGHLIGHT", SELECTION_HIGHLIGHT),
            ("SOURCE_DIM", SOURCE_DIM),
        ]),
    ]

    for cat_name, styles in categories:
        cat_label = Block.text(f"  {cat_name}: ", Style(bold=True))
        swatches: list[Block] = [cat_label]
        for name, style in styles:
            swatch = Block.text(f" {name} ", style)
            swatches.append(swatch)
        row = join_horizontal(*swatches, gap=1)
        lines.append(row)
        lines.append(Block.empty(width, 1))

    lines.append(_centered_text("No inline Style(...) needed — import named constants from theme.py.", width, CAPTION_STYLE))

    return join_vertical(*lines, align=Align.START)


def _render_blocks(width: int, height: int) -> Block:
    """Stage 4: Borders, padding, joins."""
    lines: list[Block] = []

    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("Blocks: spatial composition", width, TITLE_STYLE))
    lines.append(Block.empty(width, 1))

    # Simple bordered blocks
    box_a = border(
        Block.text("rounded", Style(fg="cyan")),
        ROUNDED, Style(fg="cyan"),
        title="box A", title_style=Style(fg="cyan", bold=True),
    )
    box_b = border(
        Block.text("heavy", Style(fg="magenta")),
        HEAVY, Style(fg="magenta"),
        title="box B", title_style=Style(fg="magenta", bold=True),
    )
    box_c = border(
        Block.text("double", Style(fg="yellow")),
        DOUBLE, Style(fg="yellow"),
        title="box C", title_style=Style(fg="yellow", bold=True),
    )
    box_d = border(
        Block.text("light", Style(fg="green")),
        LIGHT, Style(fg="green"),
    )

    # join_horizontal
    row1 = join_horizontal(box_a, box_b, box_c, box_d, gap=2)
    lines.append(pad(row1, left=4))
    lines.append(Block.empty(width, 1))
    lines.append(_left_text("    ↑ join_horizontal(box_a, box_b, box_c, box_d, gap=2)", width, DIM))
    lines.append(Block.empty(width, 1))

    # join_vertical with padding
    inner = Block.text("padded content", Style(fg="white"))
    padded = pad(inner, left=2, right=2, top=1, bottom=1)
    padded_box = border(padded, ROUNDED, Style(fg="cyan"), title="pad()", title_style=Style(fg="cyan", bold=True))

    tall_a = border(
        join_vertical(
            Block.text("top", Style(fg="green")),
            Block.text("mid", Style(fg="yellow")),
            Block.text("bot", Style(fg="red")),
        ),
        LIGHT, Style(dim=True),
        title="vertical", title_style=Style(bold=True),
    )

    row2 = join_horizontal(padded_box, tall_a, gap=3)
    lines.append(pad(row2, left=4))
    lines.append(Block.empty(width, 1))
    lines.append(_left_text("    ↑ join_vertical + pad + border", width, DIM))

    return join_vertical(*lines, align=Align.START)


def _render_components(state: DemoState, width: int, height: int) -> Block:
    """Stage 5: Interactive components."""
    lines: list[Block] = []

    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("Components: interactive primitives", width, TITLE_STYLE))
    lines.append(Block.empty(width, 1))

    # List view
    list_items = [
        Line(spans=(Span("Apples", Style(fg="red")),)),
        Line(spans=(Span("Bananas", Style(fg="yellow")),)),
        Line(spans=(Span("Cherries", Style(fg="magenta")),)),
        Line(spans=(Span("Dates", Style(fg="#cc8800")),)),
        Line(spans=(Span("Elderberries", Style(fg="blue")),)),
    ]
    lv = list_view(state.list_state, list_items, 5, cursor_char="▸")
    lv_bordered = border(lv, ROUNDED, Style(fg="cyan"), title="list_view", title_style=Style(fg="cyan", bold=True))

    # Table
    cols = [
        Column(header=Line.plain("Name"), width=12),
        Column(header=Line.plain("Lang"), width=8),
        Column(header=Line.plain("Stars"), width=7, align=Align.END),
    ]
    table_rows = [
        [Line.plain("render"), Line.plain("Python"), Line.plain("42")],
        [Line.plain("react"), Line.plain("JS"), Line.plain("220k")],
        [Line.plain("vue"), Line.plain("JS"), Line.plain("207k")],
        [Line.plain("svelte"), Line.plain("JS"), Line.plain("78k")],
        [Line.plain("htmx"), Line.plain("JS"), Line.plain("35k")],
    ]
    tbl = table(state.table_state, cols, table_rows, 5)
    tbl_bordered = border(tbl, ROUNDED, Style(fg="magenta"), title="table", title_style=Style(fg="magenta", bold=True))

    # Spinners
    spin_dots = spinner(state.spinner_state, style=Style(fg="cyan"))
    spin_braille = spinner(state.spinner_braille, style=Style(fg="magenta"))
    spin_line = spinner(state.spinner_line, style=Style(fg="yellow"))

    spinner_col = join_vertical(
        Block.text("dots:    ", Style(dim=True)),
        Block.text("braille: ", Style(dim=True)),
        Block.text("line:    ", Style(dim=True)),
    )
    spinner_vals = join_vertical(spin_dots, spin_braille, spin_line)
    spinner_block = join_horizontal(spinner_col, spinner_vals, gap=0)
    spinner_bordered = border(
        pad(spinner_block, left=1, right=1, top=0, bottom=0),
        ROUNDED, Style(fg="yellow"),
        title="spinner", title_style=Style(fg="yellow", bold=True),
    )

    # Compose: list + table side by side, spinners to the right
    top_row = join_horizontal(lv_bordered, tbl_bordered, spinner_bordered, gap=2)
    lines.append(pad(top_row, left=2))
    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("↑/↓ navigate the list    Spinners tick in real-time", width, DIM))

    return join_vertical(*lines, align=Align.START)


def _render_finale(state: DemoState, width: int, height: int) -> Block:
    """Stage 6: All concepts together."""
    lines: list[Block] = []

    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("Finale: everything composed", width, TITLE_STYLE))
    lines.append(Block.empty(width, 1))

    # Mini status bar (Spans + Lines + Theme)
    status_line = Line(spans=(
        Span(" ● ", Style(fg="green")),
        Span("render-demo", Style(fg="white", bold=True)),
        Span("  ", Style()),
        Span(f"stage {state.stage + 1}/{NUM_STAGES}", Style(dim=True)),
        Span("  ", Style()),
        Span("fps:60", Style(fg="cyan", dim=True)),
    ))
    status_block = _line_to_block(status_line, width, indent=0)
    status_bordered = border(
        pad(status_block, left=0, right=max(0, width - status_line.width - 4)),
        LIGHT, Style(dim=True),
    )

    # Compose a mini dashboard
    # Left panel: list
    list_items = [
        Line(spans=(Span("Buffers", Style(fg="cyan")),)),
        Line(spans=(Span("Cells", Style(fg="green")),)),
        Line(spans=(Span("Writers", Style(fg="yellow")),)),
        Line(spans=(Span("Regions", Style(fg="magenta")),)),
    ]
    lv = list_view(
        ListState(item_count=4, selected=1),
        list_items, 4,
    )
    left_panel = border(lv, ROUNDED, Style(fg="cyan"), title="modules", title_style=Style(fg="cyan", bold=True))

    # Center: metrics block
    metrics_lines = [
        Block.text("Cells rendered:  2,400", Style(fg="white")),
        Block.text("Diff writes:       127", Style(fg="white")),
        Block.text("Frame time:      1.2ms", Style(fg="green")),
        Block.text("Memory:          48 KB", Style(fg="yellow")),
    ]
    metrics_col = join_vertical(*metrics_lines)
    center_panel = border(
        pad(metrics_col, left=1, right=1),
        ROUNDED, Style(fg="green"),
        title="metrics", title_style=Style(fg="green", bold=True),
    )

    # Right: spinner + a styled message
    spin = spinner(state.spinner_state, style=Style(fg="cyan", bold=True))
    spin_label = Block.text(" working... ", Style(fg="cyan", italic=True))
    spin_row = join_horizontal(spin, spin_label, gap=0)

    flavor_lines = [
        Block.text("Span → Line → Block", Style(fg="white", dim=True)),
        Block.text("Block → border/pad/join", Style(fg="white", dim=True)),
        Block.text("Block → Buffer → Terminal", Style(fg="white", dim=True)),
    ]
    flavor_col = join_vertical(*flavor_lines)

    right_content = join_vertical(spin_row, Block.empty(1, 1), flavor_col)
    right_panel = border(
        pad(right_content, left=1, right=1, top=0, bottom=0),
        ROUNDED, Style(fg="magenta"),
        title="pipeline", title_style=Style(fg="magenta", bold=True),
    )

    dashboard = join_horizontal(left_panel, center_panel, right_panel, gap=1)

    lines.append(status_bordered)
    lines.append(Block.empty(width, 1))
    lines.append(pad(dashboard, left=2))
    lines.append(Block.empty(width, 1))
    lines.append(_centered_text("That's the whole stack. Go build something.", width, ACCENT))

    return join_vertical(*lines, align=Align.START)


# -- Helpers --

def _centered_text(text: str, width: int, style: Style) -> Block:
    """Create a full-width block with centered text."""
    padding = max(0, (width - len(text)) // 2)
    cells = [Cell(" ", style)] * padding
    cells.extend(Cell(ch, style) for ch in text)
    remaining = width - len(cells)
    if remaining > 0:
        cells.extend([Cell(" ", style)] * remaining)
    return Block([cells[:width]], width)


def _left_text(text: str, width: int, style: Style) -> Block:
    """Create a full-width block with left-aligned text."""
    cells = [Cell(ch, style) for ch in text[:width]]
    remaining = width - len(cells)
    if remaining > 0:
        cells.extend([Cell(" ", style)] * remaining)
    return Block([cells], width)


def _line_to_block(line: Line, width: int, indent: int = 0) -> Block:
    """Convert a Line into a Block by painting it into a temporary buffer."""
    from render.buffer import Buffer
    buf = Buffer(width, 1)
    view = buf.region(0, 0, width, 1)
    line.paint(view, indent, 0)
    cells = [buf.get(x, 0) for x in range(width)]
    return Block([cells], width)


# -- App --

class DemoApp(RenderApp):
    """Progressive demo walkthrough app."""

    def __init__(self):
        super().__init__(fps_cap=30)
        self._state = DemoState()
        self._last_tick = time.monotonic()

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def update(self) -> None:
        now = time.monotonic()
        if now - self._last_tick >= 0.1:
            self._state = replace(
                self._state,
                spinner_state=self._state.spinner_state.tick(),
                spinner_braille=self._state.spinner_braille.tick(),
                spinner_line=self._state.spinner_line.tick(),
            )
            self._last_tick = now
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        width = self._buf.width
        height = self._buf.height

        # Clear
        self._buf.fill(0, 0, width, height, " ", Style())

        # Render current stage content
        content = self._render_stage(width, height - 2)  # Reserve 2 rows for footer

        # Paint content
        content.paint(self._buf, 0, 0)

        # Paint footer
        footer = self._render_footer(width)
        footer.paint(self._buf, 0, height - 1)

    def _render_stage(self, width: int, height: int) -> Block:
        stage = self._state.stage
        if stage == 0:
            return _render_title(width, height)
        elif stage == 1:
            return _render_spans(width, height)
        elif stage == 2:
            return _render_lines(width, height)
        elif stage == 3:
            return _render_theme(width, height)
        elif stage == 4:
            return _render_blocks(width, height)
        elif stage == 5:
            return _render_components(self._state, width, height)
        elif stage == 6:
            return _render_finale(self._state, width, height)
        return Block.empty(width, height)

    def _render_footer(self, width: int) -> Block:
        """Navigation footer with stage dots and hints."""
        parts: list[Cell] = []

        # Left: nav hints
        parts.append(Cell(" ", FOOTER_BASE))
        for ch in "←→":
            parts.append(Cell(ch, NAV_KEY))
        for ch in " navigate":
            parts.append(Cell(ch, NAV_TEXT))

        parts.append(Cell(" ", FOOTER_BASE))
        parts.append(Cell(" ", FOOTER_BASE))

        # Stage dots
        for i in range(NUM_STAGES):
            if i == self._state.stage:
                parts.append(Cell("●", STAGE_DOT_ACTIVE))
            else:
                parts.append(Cell("○", STAGE_DOT_INACTIVE))
            parts.append(Cell(" ", FOOTER_BASE))

        parts.append(Cell(" ", FOOTER_BASE))

        # Stage title
        title = STAGE_TITLES[self._state.stage]
        for ch in title:
            parts.append(Cell(ch, Style(fg="white", bold=True, bg=FOOTER_BG)))
        parts.append(Cell(" ", FOOTER_BASE))

        # Right: stage number + quit hint
        right = f" {self._state.stage + 1}/{NUM_STAGES}  q:quit "
        right_start = width - len(right)
        # Fill gap
        while len(parts) < right_start:
            parts.append(Cell(" ", FOOTER_BASE))
        for ch in right:
            parts.append(Cell(ch, NAV_TEXT))

        # Pad/truncate to width
        while len(parts) < width:
            parts.append(Cell(" ", FOOTER_BASE))
        parts = parts[:width]

        return Block([parts], width)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self.quit()
            return

        if key == "right":
            if self._state.stage < NUM_STAGES - 1:
                self._state = replace(self._state, stage=self._state.stage + 1)
            return

        if key == "left":
            if self._state.stage > 0:
                self._state = replace(self._state, stage=self._state.stage - 1)
            return

        # Stage-specific keys (Components stage)
        if self._state.stage == 5:
            if key in ("up", "k"):
                self._state = replace(
                    self._state,
                    list_state=self._state.list_state.move_up(),
                )
                return
            if key in ("down", "j"):
                self._state = replace(
                    self._state,
                    list_state=self._state.list_state.move_down(),
                )
                return


# -- Entry point --

async def main():
    app = DemoApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
