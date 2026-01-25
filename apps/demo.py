"""Progressive interactive demo: a walkthrough of the render framework.

Run: uv run python -m apps.demo
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, replace, field

from wcwidth import wcwidth as _wcw

from render.app import RenderApp
from render.block import Block
from render.cell import Style, Cell
from render.compose import join_horizontal, join_vertical, pad, border, Align
from render.borders import BorderChars, ROUNDED, HEAVY, DOUBLE, LIGHT, ASCII
from render.components import (
    ListState, SpinnerState,
    DOTS, BRAILLE, LINE,
    Column, TableState,
    list_view, spinner, table,
    TextInputState, text_input,
)
from render.span import Span, Line
from render.theme import (
    HEADER_BG,
    HEADER_BASE, HEADER_DIM, HEADER_CONNECTED, HEADER_SPINNER,
    FOOTER_KEY, FOOTER_DIM,
    LEVEL_STYLES,
    SELECTION_CURSOR, SELECTION_HIGHLIGHT, SOURCE_DIM,
)

# Footer uses same bg as header
FOOTER_BG = HEADER_BG
FOOTER_BASE = Style(bg=FOOTER_BG)


# -- Constants --

STAGE_TITLES = [
    "Hello",
    "Spans",
    "Lines",
    "Theme",
    "Blocks",
    "Components",
    "Fin",
]

NUM_STAGES = len(STAGE_TITLES)

# Border presets for cycling
BORDER_PRESETS = [
    ("rounded", ROUNDED, Style(fg="cyan")),
    ("heavy", HEAVY, Style(fg="magenta")),
    ("double", DOUBLE, Style(fg="yellow")),
    ("light", LIGHT, Style(fg="green")),
    ("ascii", ASCII, Style(fg="white")),
]

# Styles the user's typed text gets rendered in
TYPING_STYLES = [
    ("bold", Style(bold=True)),
    ("cyan", Style(fg="cyan")),
    ("magenta + italic", Style(fg="magenta", italic=True)),
    ("reverse", Style(reverse=True)),
    ("green + bold", Style(fg="green", bold=True)),
    ("#ff6b35", Style(fg="#ff6b35")),
    ("dim + underline", Style(dim=True, underline=True)),
    ("#7b68ee + bold", Style(fg="#7b68ee", bold=True)),
]

# Demo styles
TITLE_STYLE = Style(fg="cyan", bold=True)
DIM = Style(dim=True)
ACCENT = Style(fg="magenta", bold=True)
CAPTION = Style(fg="white", dim=True, italic=True)
HINT = Style(fg="cyan", dim=True)
NAV_KEY = Style(fg="cyan", bold=True)
NAV_TEXT = Style(dim=True)
DOT_ACTIVE = Style(fg="cyan", bold=True)
DOT_INACTIVE = Style(dim=True)


# -- Theme Palettes --

# Each palette maps token names to colors/styles
# This demonstrates the concept: same tokens, different values
THEME_PALETTES = [
    {
        "name": "default",
        "error": "#ff5555",
        "warn": "#ffff55",
        "info": "#ffffff",
        "debug": "#888888",
        "connected": "#55ff55",
        "accent": "#55ffff",
        "bg": 236,
    },
    {
        "name": "ocean",
        "error": "#ff6b6b",
        "warn": "#ffd93d",
        "info": "#a8d8ea",
        "debug": "#6b8e9f",
        "connected": "#6bffb8",
        "accent": "#6bb5ff",
        "bg": 17,
    },
    {
        "name": "forest",
        "error": "#e57373",
        "warn": "#dce775",
        "info": "#c8e6c9",
        "debug": "#81976c",
        "connected": "#aed581",
        "accent": "#81c784",
        "bg": 22,
    },
    {
        "name": "high-contrast",
        "error": "#ff0000",
        "warn": "#ffff00",
        "info": "#ffffff",
        "debug": "#aaaaaa",
        "connected": "#00ff00",
        "accent": "#00ffff",
        "bg": 16,
    },
]


# -- State --

# Named colors for the spans color picker
SPAN_COLORS = [
    ("red", "red"),
    ("green", "green"),
    ("blue", "blue"),
    ("cyan", "cyan"),
    ("magenta", "magenta"),
    ("yellow", "yellow"),
    ("#ff6b35", "#ff6b35"),
    ("#7b68ee", "#7b68ee"),
]


@dataclass(frozen=True)
class DemoState:
    stage: int = 0
    # Title: reveal animation
    reveal_chars: int = 0
    # Spans: user typing + style toggles
    input_state: TextInputState = field(default_factory=lambda: TextInputState(text="the quick fox"))
    span_bold: bool = False
    span_dim: bool = False
    span_italic: bool = False
    span_underline: bool = False
    span_reverse: bool = False
    span_color_index: int = 0
    # Theme: palette selection
    theme_index: int = 0
    # Blocks: border cycling
    border_index: int = 0
    # Components: list + spinners
    list_state: ListState = field(default_factory=lambda: ListState(item_count=6))
    table_state: TableState = field(default_factory=lambda: TableState(row_count=5))
    spinner_state: SpinnerState = field(default_factory=SpinnerState)
    spinner_braille: SpinnerState = field(default_factory=lambda: SpinnerState(frames=BRAILLE))
    spinner_line: SpinnerState = field(default_factory=lambda: SpinnerState(frames=LINE))
    # Finale: animation start time
    finale_start: float = 0.0


# -- Stage Renderers --

TITLE_LINES = [
    "hello. i'm render.",
    "",
    "a cell-buffer terminal UI framework.",
    "python's answer to ratatui + lip gloss + bubbles.",
    "",
    "everything you see right now? that's me.",
    "this whole demo is built with the thing it's demoing.",
    "",
    "let me show you how it works.",
]


def _render_title(state: DemoState, width: int, height: int) -> Block:
    rows: list[Block] = []
    rows.append(Block.empty(width, 2))

    # Reveal text character by character
    chars_left = state.reveal_chars
    for line_text in TITLE_LINES:
        if chars_left <= 0:
            break
        visible = line_text[:chars_left]
        chars_left -= len(line_text)

        if not line_text:
            rows.append(Block.empty(width, 1))
            chars_left -= 1  # count the "newline"
            continue

        # First line gets title style, rest get caption style
        style = TITLE_STYLE if line_text == TITLE_LINES[0] else CAPTION
        rows.append(_centered_text(visible, width, style))

    # Show nav hint after full reveal
    total = sum(len(l) for l in TITLE_LINES) + len(TITLE_LINES)
    if state.reveal_chars >= total:
        rows.append(Block.empty(width, 1))
        rows.append(_centered_text("→", width, HINT))

    return join_vertical(*rows, align=Align.CENTER)


def _render_spans(state: DemoState, width: int, height: int) -> Block:
    rows: list[Block] = []
    rows.append(Block.empty(width, 1))
    rows.append(_centered_text("spans: the atoms", width, TITLE_STYLE))
    rows.append(Block.empty(width, 1))

    # -- Top section: Attributes + Colors reference cards side by side --

    # Attributes reference card
    attr_rows: list[Block] = []
    attr_samples = [
        ("bold", Style(bold=True)),
        ("dim", Style(dim=True)),
        ("italic", Style(italic=True)),
        ("underline", Style(underline=True)),
        ("reverse", Style(reverse=True)),
    ]
    for name, style in attr_samples:
        label = Block.text(f" {name:<10}", DIM)
        sample = Block.text("the quick fox", style)
        attr_rows.append(join_horizontal(label, sample, gap=1))
    attr_content = join_vertical(*attr_rows)
    attr_card = border(attr_content, ROUNDED, Style(fg="cyan", dim=True),
                       title="attributes", title_style=Style(fg="cyan", bold=True))

    # Colors reference card
    color_rows: list[Block] = []

    # Named colors row
    named_colors = ["red", "green", "blue", "cyan", "magenta", "yellow"]
    named_row: list[Block] = [Block.text(" named ", DIM)]
    for color in named_colors:
        named_row.append(Block.text(f" {color[:3]} ", Style(fg=color)))
    color_rows.append(join_horizontal(*named_row, gap=0))

    # 256-palette sample row
    palette_row: list[Block] = [Block.text(" 256   ", DIM)]
    palette_samples = [196, 208, 226, 46, 51, 21, 129, 201]  # rainbow selection
    for code in palette_samples:
        palette_row.append(Block.text(" ■ ", Style(fg=code)))
    color_rows.append(join_horizontal(*palette_row, gap=0))

    # Hex colors row
    hex_row: list[Block] = [Block.text(" hex   ", DIM)]
    hex_samples = ["#ff6b35", "#7b68ee", "#00d4aa", "#ff1493"]
    for hex_color in hex_samples:
        hex_row.append(Block.text(f" {hex_color[:4]} ", Style(fg=hex_color)))
    color_rows.append(join_horizontal(*hex_row, gap=0))

    color_content = join_vertical(*color_rows)
    color_card = border(color_content, ROUNDED, Style(fg="magenta", dim=True),
                        title="colors", title_style=Style(fg="magenta", bold=True))

    # Join the two cards horizontally
    top_section = join_horizontal(attr_card, color_card, gap=2)
    rows.append(pad(top_section, left=max(0, (width - top_section.width) // 2)))
    rows.append(Block.empty(width, 1))

    # -- Bottom section: Interactive span builder --

    builder_rows: list[Block] = []

    # Toggle row showing current attribute states
    toggle_parts: list[Block] = []
    toggles = [
        ("b", "bold", state.span_bold),
        ("d", "dim", state.span_dim),
        ("i", "italic", state.span_italic),
        ("u", "underline", state.span_underline),
        ("r", "reverse", state.span_reverse),
    ]
    for key, name, active in toggles:
        if active:
            toggle_parts.append(Block.text(f" [{key}] {name} ", Style(fg="cyan", bold=True, reverse=True)))
        else:
            toggle_parts.append(Block.text(f" [{key}] {name} ", DIM))
    toggle_row = join_horizontal(*toggle_parts, gap=0)
    builder_rows.append(toggle_row)
    builder_rows.append(Block.empty(1, 1))

    # Color selector row
    color_parts: list[Block] = [Block.text(" color: ", DIM)]
    for i, (name, color) in enumerate(SPAN_COLORS):
        if i == state.span_color_index:
            color_parts.append(Block.text(f" {name} ", Style(fg=color, bold=True, reverse=True)))
        else:
            color_parts.append(Block.text(f" {name} ", Style(fg=color, dim=True)))
    color_parts.append(Block.text("  (c: cycle)", HINT))
    color_row = join_horizontal(*color_parts, gap=0)
    builder_rows.append(color_row)
    builder_rows.append(Block.empty(1, 1))

    # Build the composed style
    _, current_color = SPAN_COLORS[state.span_color_index]
    composed_style = Style(
        fg=current_color,
        bold=state.span_bold,
        dim=state.span_dim,
        italic=state.span_italic,
        underline=state.span_underline,
        reverse=state.span_reverse,
    )

    # Preview text with composed style
    preview_text = state.input_state.text or "the quick fox"
    preview_label = Block.text(" preview: ", DIM)
    preview_sample = Block.text(preview_text[:30], composed_style)
    preview_row = join_horizontal(preview_label, preview_sample, gap=0)
    builder_rows.append(preview_row)
    builder_rows.append(Block.empty(1, 1))

    # Text input for customizing preview
    input_label = Block.text(" text: ", DIM)
    input_width = min(30, width - 20)
    inp = text_input(state.input_state, input_width, focused=True,
                     style=Style(fg="white"), placeholder="type here...")
    input_row = join_horizontal(input_label, inp, gap=0)
    builder_rows.append(input_row)

    builder_content = join_vertical(*builder_rows)
    builder_card = border(builder_content, ROUNDED, Style(fg="yellow", dim=True),
                          title="composer", title_style=Style(fg="yellow", bold=True))
    rows.append(pad(builder_card, left=max(0, (width - builder_card.width) // 2)))
    rows.append(Block.empty(width, 1))

    rows.append(_centered_text("one Span = one run of text + one Style. compose them freely.", width, CAPTION))

    return join_vertical(*rows, align=Align.START)


def _render_lines(width: int, height: int) -> Block:
    rows: list[Block] = []
    rows.append(Block.empty(width, 1))
    rows.append(_centered_text("lines: spans holding hands", width, TITLE_STYLE))
    rows.append(Block.empty(width, 1))

    examples = [
        ("plain text", Line.plain("just a string. nothing fancy.")),
        ("status line", Line(spans=(
            Span("●", Style(fg="green")),
            Span(" connected", Style(fg="white", bold=True)),
            Span("  ", Style()),
            Span("latency:", Style(dim=True)),
            Span(" 2ms", Style(fg="cyan")),
        ))),
        ("log entry", Line(spans=(
            Span("14:23:07 ", Style(dim=True)),
            Span("WARN", Style(fg="yellow", bold=True)),
            Span(" ", Style()),
            Span("disk usage 89%", Style(fg="white")),
            Span(" /dev/sda1", Style(dim=True, italic=True)),
        ))),
        ("error", Line(spans=(
            Span("14:23:09 ", Style(dim=True)),
            Span("ERROR", Style(fg="red", bold=True)),
            Span(" ", Style()),
            Span("connection refused", Style(fg="white")),
            Span(" (retry 3/5)", Style(dim=True)),
        ))),
        ("key=value", Line(spans=(
            Span("host", Style(fg="cyan", bold=True)),
            Span("=", Style(dim=True)),
            Span("prod-3", Style(fg="white")),
            Span("  ", Style()),
            Span("region", Style(fg="cyan", bold=True)),
            Span("=", Style(dim=True)),
            Span("us-east-1", Style(fg="white")),
            Span("  ", Style()),
            Span("load", Style(fg="cyan", bold=True)),
            Span("=", Style(dim=True)),
            Span("0.42", Style(fg="green")),
        ))),
    ]

    for label, line in examples:
        label_block = Block.text(f"  {label:>12}  ", DIM)
        line_block = _line_to_block(line, width - 16, indent=0)
        row = join_horizontal(label_block, line_block, gap=0)
        rows.append(row)
        rows.append(Block.empty(width, 1))

    rows.append(_centered_text("same data, different vibes. a Line is a tuple of Spans.", width, CAPTION))
    rows.append(_centered_text("Line.paint() is where Cells get born.", width, CAPTION))

    return join_vertical(*rows, align=Align.START)


def _render_theme(state: DemoState, width: int, height: int) -> Block:
    rows: list[Block] = []
    rows.append(Block.empty(width, 1))
    rows.append(_centered_text("theme: swap the palette, keep the names", width, TITLE_STYLE))
    rows.append(Block.empty(width, 1))
    rows.append(_centered_text("same tokens, different colors. the UI updates instantly.", width, CAPTION))
    rows.append(Block.empty(width, 2))

    palette = THEME_PALETTES[state.theme_index]

    # -- Left side: theme picker --
    picker_lines: list[Block] = []
    for i, p in enumerate(THEME_PALETTES):
        cursor = "▸ " if i == state.theme_index else "  "
        name = p["name"]
        if i == state.theme_index:
            line_style = Style(fg="cyan", bold=True)
        else:
            line_style = Style(dim=True)
        picker_lines.append(Block.text(f"{cursor}{name:<14}", line_style))
    picker_content = join_vertical(*picker_lines)
    picker_box = border(picker_content, ROUNDED, Style(fg="cyan", dim=True),
                        title="theme", title_style=Style(fg="cyan", bold=True))

    # -- Right side: live preview --
    preview_lines: list[Block] = []

    # Log entries using palette colors
    log_entries = [
        ("14:23:07", "ERROR", "disk full", "error"),
        ("14:23:08", "WARN", "quota 89%", "warn"),
        ("14:23:09", "INFO", "backup done", "info"),
        ("14:23:10", "DEBUG", "cache hit", "debug"),
    ]
    for ts, level, msg, level_key in log_entries:
        ts_block = Block.text(f"{ts} ", Style(dim=True))
        level_color = palette[level_key]
        level_block = Block.text(f"{level:<5} ", Style(fg=level_color, bold=(level_key == "error")))
        msg_block = Block.text(msg, Style(fg=palette["info"]))
        entry = join_horizontal(ts_block, level_block, msg_block, gap=0)
        preview_lines.append(entry)

    # Status line
    preview_lines.append(Block.empty(1, 1))
    dot = Block.text("● ", Style(fg=palette["connected"]))
    status = Block.text("connected", Style(fg=palette["info"], bold=True))
    sep = Block.text("  ", Style())
    latency_label = Block.text("latency: ", Style(dim=True))
    latency_val = Block.text("2ms", Style(fg=palette["accent"]))
    status_line = join_horizontal(dot, status, sep, latency_label, latency_val, gap=0)
    preview_lines.append(status_line)

    preview_content = join_vertical(*preview_lines)
    preview_box = border(preview_content, ROUNDED, Style(fg=palette["accent"], dim=True),
                         title="preview", title_style=Style(fg=palette["accent"], bold=True))

    # Combine picker and preview side by side
    main_row = join_horizontal(picker_box, preview_box, gap=3)
    rows.append(pad(main_row, left=4))
    rows.append(Block.empty(width, 1))

    # -- Token mappings --
    tokens = [
        ("error", palette["error"]),
        ("warn", palette["warn"]),
        ("connected", palette["connected"]),
        ("accent", palette["accent"]),
    ]
    token_parts: list[Block] = []
    for name, color in tokens:
        token_parts.append(Block.text(f"{name}", Style(dim=True)))
        token_parts.append(Block.text("→", Style(dim=True)))
        token_parts.append(Block.text(f"{color}", Style(fg=color, bold=True)))
        token_parts.append(Block.text("  ", Style()))
    token_row = join_horizontal(*token_parts, gap=1)
    rows.append(pad(token_row, left=4))

    rows.append(Block.empty(width, 2))
    rows.append(_centered_text("↑/↓ switch themes    same code, different palette", width, HINT))

    return join_vertical(*rows, align=Align.START)


def _render_blocks(state: DemoState, width: int, height: int) -> Block:
    rows: list[Block] = []
    rows.append(Block.empty(width, 1))
    rows.append(_centered_text("blocks: the spatial escape hatch", width, TITLE_STYLE))
    rows.append(Block.empty(width, 1))
    rows.append(_centered_text("when left-to-right text isn't enough.", width, CAPTION))
    rows.append(Block.empty(width, 2))

    # The content we're framing
    content_lines = [
        Block.text("  i'm the same content  ", Style(fg="white")),
        Block.text("  in different frames.   ", Style(dim=True)),
    ]
    content = join_vertical(*content_lines)

    # Current border style
    name, chars, style = BORDER_PRESETS[state.border_index]
    framed = border(content, chars, style, title=name, title_style=Style(fg=style.fg, bold=True))

    # Show all border names, highlight current
    names_row: list[Block] = []
    for i, (n, _, s) in enumerate(BORDER_PRESETS):
        if i == state.border_index:
            names_row.append(Block.text(f" {n} ", Style(fg=s.fg, bold=True, reverse=True)))
        else:
            names_row.append(Block.text(f" {n} ", DIM))
    selector = join_horizontal(*names_row, gap=1)

    rows.append(pad(framed, left=(width - framed.width) // 2))
    rows.append(Block.empty(width, 1))
    rows.append(pad(selector, left=(width - selector.width) // 2))
    rows.append(Block.empty(width, 2))

    # Show join operations
    box_a = border(Block.text(" left ", Style(fg="cyan")), ROUNDED, Style(fg="cyan"))
    box_b = border(Block.text(" right ", Style(fg="magenta")), ROUNDED, Style(fg="magenta"))
    joined = join_horizontal(box_a, box_b, gap=1)

    box_top = border(Block.text(" top ", Style(fg="green")), LIGHT, Style(fg="green"))
    box_bot = border(Block.text(" bot ", Style(fg="yellow")), LIGHT, Style(fg="yellow"))
    stacked = join_vertical(box_top, box_bot)

    composition = join_horizontal(joined, Block.empty(3, 1), stacked, gap=0)
    rows.append(pad(composition, left=(width - composition.width) // 2))
    rows.append(Block.empty(width, 1))

    rows.append(_centered_text("space to cycle borders    join, pad, border — that's the whole API", width, HINT))

    return join_vertical(*rows, align=Align.START)


def _render_components(state: DemoState, width: int, height: int) -> Block:
    rows: list[Block] = []
    rows.append(Block.empty(width, 1))
    rows.append(_centered_text("components: real widgets", width, TITLE_STYLE))
    rows.append(Block.empty(width, 1))

    # List view
    list_items = [
        Line(spans=(Span("Apples", Style(fg="red")),)),
        Line(spans=(Span("Bananas", Style(fg="yellow")),)),
        Line(spans=(Span("Cherries", Style(fg="magenta")),)),
        Line(spans=(Span("Dates", Style(fg="#cc8800")),)),
        Line(spans=(Span("Elderberries", Style(fg="blue")),)),
        Line(spans=(Span("Figs", Style(fg="green")),)),
    ]
    lv = list_view(state.list_state, list_items, 6, cursor_char="▸")
    lv_bordered = border(lv, ROUNDED, Style(fg="cyan"),
                         title="list", title_style=Style(fg="cyan", bold=True))

    # Table
    cols = [
        Column(header=Line.plain("name"), width=10),
        Column(header=Line.plain("role"), width=10),
        Column(header=Line.plain("status"), width=8),
    ]
    table_rows = [
        [Line.plain("Buffer"), Line.plain("grid"), Line(spans=(Span("ok", Style(fg="green")),))],
        [Line.plain("Writer"), Line.plain("output"), Line(spans=(Span("ok", Style(fg="green")),))],
        [Line.plain("Block"), Line.plain("compose"), Line(spans=(Span("ok", Style(fg="green")),))],
        [Line.plain("Line"), Line.plain("describe"), Line(spans=(Span("ok", Style(fg="green")),))],
        [Line.plain("Span"), Line.plain("atom"), Line(spans=(Span("ok", Style(fg="green")),))],
    ]
    tbl = table(state.table_state, cols, table_rows, 5)
    tbl_bordered = border(tbl, ROUNDED, Style(fg="magenta"),
                          title="table", title_style=Style(fg="magenta", bold=True))

    # Spinners
    spin_dots = spinner(state.spinner_state, style=Style(fg="cyan"))
    spin_braille = spinner(state.spinner_braille, style=Style(fg="magenta"))
    spin_line = spinner(state.spinner_line, style=Style(fg="yellow"))

    spinner_col = join_vertical(
        Block.text(" dots    ", DIM),
        Block.text(" braille ", DIM),
        Block.text(" line    ", DIM),
    )
    spinner_vals = join_vertical(spin_dots, spin_braille, spin_line)
    spinner_block = join_horizontal(spinner_col, spinner_vals, gap=0)
    spinner_bordered = border(
        pad(spinner_block, left=1, right=1),
        ROUNDED, Style(fg="yellow"),
        title="spinner", title_style=Style(fg="yellow", bold=True),
    )

    top_row = join_horizontal(lv_bordered, tbl_bordered, spinner_bordered, gap=2)
    rows.append(pad(top_row, left=2))
    rows.append(Block.empty(width, 1))
    rows.append(_centered_text("↑/↓ navigate the list.  spinners are just showing off.", width, HINT))

    return join_vertical(*rows, align=Align.START)


# -- Finale animation --

PIPELINE = [
    ("Span", "cyan", "text + style"),
    ("Line", "green", "spans in a row"),
    ("Block", "yellow", "2D cell grid"),
    ("Buffer", "magenta", "the frame"),
    ("Writer", "white", "to terminal"),
]

# Animation schedule: (start_time, duration) for each box
FINALE_SCHEDULE = [
    (0.0, 0.7),    # Span: scan
    (0.9, 0.8),    # Line: trace
    (1.9, 0.25),   # Block: thud
    (2.3, 0.7),    # Buffer: fill
    (3.2, 0.6),    # Writer: type
]
# Arrows appear after preceding box finishes
ARROW_TIMES = [0.8, 1.8, 2.2, 3.1]
# Bottom section
TITLE_START = 4.0
BOTTOM_START = 5.0
FINALE_DURATION = 7.0

# Confetti characters and colors
CONFETTI_CHARS = "✦✧◆◇★☆·∙•°◦⊹"
CONFETTI_COLORS = ["#ff6b6b", "#ffd93d", "#6bff6b", "#6bb5ff",
                   "#d66bff", "#ff6bd6", "#6bffd9", "#ffb86b"]

# The celebration ASCII art (lines, painted character by character)
CELEBRATION_ART = [
    r"        .  ✦      ★    .        ",
    r"    ★        .        ✦    .    ",
    r"  .    ✧  ╭──────────────╮  .   ",
    r"       .  │              │  ★   ",
    r"   ✦      │  just cells  │      ",
    r"       .  │              │  .   ",
    r"  .    ★  ╰──────────────╯  ✧   ",
    r"    .        ✦        .    ★    ",
    r"        ★  .      ✦    .        ",
]

# The joy emojis for the wave
WAVE_EMOJIS = "🎉✨🎊⭐🚀💫🌟🎆🎇💥"

# The taglines
TAGLINES = [
    ("🎉", "no dependencies", "#ff6b6b"),
    ("✨", "no runtime magic", "#ffd93d"),
    ("🚀", "just cells", "#6bff6b"),
]


def _progress(elapsed: float, start: float, duration: float) -> float:
    if elapsed < start:
        return 0.0
    if elapsed >= start + duration:
        return 1.0
    return (elapsed - start) / duration


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _scan_reveal(block: Block, progress: float) -> Block:
    """CRT scan: reveal cells left→right, top→bottom."""
    total = block.width * block.height
    revealed = int(_ease_out_cubic(progress) * total)
    empty = Cell(" ", Style())
    rows = []
    count = 0
    for y in range(block.height):
        row = []
        for x in range(block.width):
            if count < revealed:
                row.append(block._rows[y][x])
            else:
                row.append(empty)
            count += 1
        rows.append(row)
    return Block(rows, block.width)


def _trace_border(content: Block, chars: BorderChars, style: Style,
                  progress: float, title: str = "") -> Block:
    """Border races clockwise, then content fills in."""
    w = content.width + 2
    h = content.height + 2

    # Build perimeter path clockwise from top-left
    perimeter: list[tuple[int, int, str]] = []
    perimeter.append((0, 0, chars.top_left))
    for x in range(1, w - 1):
        perimeter.append((0, x, chars.horizontal))
    perimeter.append((0, w - 1, chars.top_right))
    for y in range(1, h - 1):
        perimeter.append((y, w - 1, chars.vertical))
    perimeter.append((h - 1, w - 1, chars.bottom_right))
    for x in range(w - 2, 0, -1):
        perimeter.append((h - 1, x, chars.horizontal))
    perimeter.append((h - 1, 0, chars.bottom_left))
    for y in range(h - 2, 0, -1):
        perimeter.append((y, 0, chars.vertical))

    # 0-0.6: border trace, 0.6-1.0: content reveal
    border_p = min(1.0, progress / 0.6)
    content_p = max(0.0, (progress - 0.6) / 0.4)

    empty = Cell(" ", Style())
    rows = [[empty] * w for _ in range(h)]

    # Reveal border chars
    revealed = int(_ease_out_cubic(border_p) * len(perimeter))
    for i in range(revealed):
        py, px, ch = perimeter[i]
        rows[py][px] = Cell(ch, style)

    # Title after top edge is drawn
    if title and border_p > 0.4:
        title_style = Style(fg=style.fg, bold=True)
        for i, ch in enumerate(title):
            tx = 2 + i
            if tx < w - 1:
                rows[0][tx] = Cell(ch, title_style)

    # Content reveal
    if content_p > 0:
        total_c = content.width * content.height
        shown = int(_ease_out_cubic(content_p) * total_c)
        count = 0
        for y in range(content.height):
            for x in range(content.width):
                if count < shown:
                    rows[y + 1][x + 1] = content._rows[y][x]
                count += 1

    return Block(rows, w)


def _thud_y_offset(progress: float) -> int:
    """Drop from above, brief bounce."""
    if progress <= 0:
        return -4
    if progress < 0.4:
        # Falling
        return int((1.0 - progress / 0.4) * -4)
    if progress < 0.7:
        # Overshoot down
        return 1
    return 0


def _fill_reveal(block: Block, progress: float) -> Block:
    """Cells appear in a scattered pattern (deterministic pseudo-random)."""
    total = block.width * block.height
    # Build a shuffled index order (deterministic from position hash)
    indices = list(range(total))
    # Simple deterministic shuffle using position-based ordering
    indices.sort(key=lambda i: ((i * 7919 + 104729) % total))
    revealed_count = int(_ease_out_cubic(progress) * total)
    revealed_set = set(indices[:revealed_count])

    empty = Cell(" ", Style())
    rows = []
    idx = 0
    for y in range(block.height):
        row = []
        for x in range(block.width):
            if idx in revealed_set:
                row.append(block._rows[y][x])
            else:
                row.append(empty)
            idx += 1
        rows.append(row)
    return Block(rows, block.width)


def _type_reveal(content: Block, chars: BorderChars, style: Style,
                 progress: float, title: str = "") -> Block:
    """Border appears first, then content types in character by character."""
    w = content.width + 2
    h = content.height + 2

    # 0-0.3: border instant, 0.3-1.0: content types
    border_p = min(1.0, progress / 0.3)
    content_p = max(0.0, (progress - 0.3) / 0.7)

    empty = Cell(" ", Style())
    rows = [[empty] * w for _ in range(h)]

    # Border (appears quickly)
    if border_p > 0:
        # Top
        rows[0][0] = Cell(chars.top_left, style)
        rows[0][w - 1] = Cell(chars.top_right, style)
        for x in range(1, w - 1):
            rows[0][x] = Cell(chars.horizontal, style)
        # Bottom
        rows[h - 1][0] = Cell(chars.bottom_left, style)
        rows[h - 1][w - 1] = Cell(chars.bottom_right, style)
        for x in range(1, w - 1):
            rows[h - 1][x] = Cell(chars.horizontal, style)
        # Sides
        for y in range(1, h - 1):
            rows[y][0] = Cell(chars.vertical, style)
            rows[y][w - 1] = Cell(chars.vertical, style)
        # Title
        if title:
            title_style = Style(fg=style.fg, bold=True)
            for i, ch in enumerate(title):
                tx = 2 + i
                if tx < w - 1:
                    rows[0][tx] = Cell(ch, title_style)

    # Content types in left→right, top→bottom
    if content_p > 0:
        total_c = content.width * content.height
        shown = int(content_p * total_c)
        count = 0
        for y in range(content.height):
            for x in range(content.width):
                if count < shown:
                    rows[y + 1][x + 1] = content._rows[y][x]
                count += 1

    return Block(rows, w)


def _hue_to_rgb(h: float) -> str:
    """Convert hue (0-1) to a hex color string. Full saturation, 70% lightness."""
    h = h % 1.0
    s, l = 0.85, 0.65
    # HSL to RGB
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h * 6) % 2 - 1))
    m = l - c / 2
    if h < 1/6:
        r, g, b = c, x, 0
    elif h < 2/6:
        r, g, b = x, c, 0
    elif h < 3/6:
        r, g, b = 0, c, x
    elif h < 4/6:
        r, g, b = 0, x, c
    elif h < 5/6:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    ri, gi, bi = int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
    return f"#{ri:02x}{gi:02x}{bi:02x}"


def _render_finale(state: DemoState, width: int, height: int) -> Block:
    from render.buffer import Buffer

    buf = Buffer(width, height)
    elapsed = time.monotonic() - state.finale_start if state.finale_start > 0 else 99.0
    now = time.monotonic()

    # Build pipeline boxes and compute positions
    boxes: list[Block] = []
    for name, color, desc in PIPELINE:
        inner = join_vertical(
            Block.text(f" {name} ", Style(fg=color, bold=True)),
            Block.text(f" {desc} ", Style(dim=True)),
        )
        boxes.append(inner)

    # Compute x positions for centered pipeline
    box_widths = [b.width + 2 for b in boxes]  # +2 for border
    arrow_width = 3  # " → "
    total_pipe_w = sum(box_widths) + arrow_width * 4
    pipe_start_x = max(0, (width - total_pipe_w) // 2)
    box_height = 4  # 2 content rows + 2 border rows
    pipe_y = 3  # row where pipeline boxes start
    arrow_y = pipe_y + box_height // 2  # vertically centered

    # Paint each box with its animation
    x_cursor = pipe_start_x
    for i, (inner, (start, dur)) in enumerate(zip(boxes, FINALE_SCHEDULE)):
        p = _progress(elapsed, start, dur)
        bw = inner.width + 2
        _, color, _ = PIPELINE[i]
        box_style = Style(fg=color, dim=True)

        if p > 0:
            if i == 0:
                # Span: scan reveal
                full_box = border(inner, ROUNDED, box_style)
                animated = _scan_reveal(full_box, p)
                animated.paint(buf, x_cursor, pipe_y)
            elif i == 1:
                # Line: trace border
                animated = _trace_border(inner, ROUNDED, box_style, p)
                animated.paint(buf, x_cursor, pipe_y)
            elif i == 2:
                # Block: thud (drop from above)
                full_box = border(inner, ROUNDED, box_style)
                y_off = _thud_y_offset(p)
                full_box.paint(buf, x_cursor, pipe_y + y_off)
            elif i == 3:
                # Buffer: scattered fill
                full_box = border(inner, ROUNDED, box_style)
                animated = _fill_reveal(full_box, p)
                animated.paint(buf, x_cursor, pipe_y)
            elif i == 4:
                # Writer: border first, then content types
                animated = _type_reveal(inner, ROUNDED, box_style, p)
                animated.paint(buf, x_cursor, pipe_y)

        x_cursor += bw

        # Arrow after this box
        if i < 4:
            arrow_time = ARROW_TIMES[i]
            if elapsed >= arrow_time:
                arrow_p = min(1.0, (elapsed - arrow_time) / 0.15)
                arrow_style = Style(dim=arrow_p < 0.5)
                buf.put_text(x_cursor, arrow_y, " → ", arrow_style)
            x_cursor += arrow_width

    # "that's the whole stack." — rainbow dancing letters with confetti
    title_text = "that's the whole stack."
    title_p = _progress(elapsed, TITLE_START, 0.6)
    title_y = pipe_y + box_height + 2

    if title_p > 0:
        # How many characters revealed so far
        visible_count = int(_ease_out_cubic(title_p) * len(title_text))
        title_start_x = max(0, (width - len(title_text)) // 2)

        # After fully revealed, letters dance and rainbow
        fully_revealed = title_p >= 1.0
        dance_time = elapsed - (TITLE_START + 0.6) if fully_revealed else 0

        for ci in range(min(visible_count, len(title_text))):
            ch = title_text[ci]
            if ch == " ":
                continue

            # Rainbow: hue shifts over time and by position
            hue = (ci * 0.08 + now * 0.4) % 1.0
            color = _hue_to_rgb(hue)

            # Vertical wave: sine offset per character (only after fully revealed)
            y_off = 0
            if fully_revealed and dance_time > 0:
                wave_amp = min(1.0, dance_time * 2)  # ramp up amplitude
                y_off = round(math.sin(now * 3.0 + ci * 0.5) * wave_amp)

            char_style = Style(fg=color, bold=True)
            bx = title_start_x + ci
            by = title_y + y_off
            if 0 <= by < height and 0 <= bx < width:
                buf.put(bx, by, ch, char_style)

        # Confetti: sparkle around the title area
        if fully_revealed and dance_time > 0.3:
            confetti_intensity = min(1.0, (dance_time - 0.3) * 1.5)
            num_confetti = int(confetti_intensity * 20)
            for ci in range(num_confetti):
                # Deterministic but time-varying positions
                seed = ci * 7919 + int(now * 5) * 104729
                cx = (seed % width)
                cy_range = 3  # confetti zone: a few rows around title
                cy = title_y - 1 + ((seed // width) % (cy_range * 2 + 1)) - cy_range
                if 0 <= cy < height and 0 <= cx < width:
                    confetti_ch = CONFETTI_CHARS[seed % len(CONFETTI_CHARS)]
                    confetti_color = CONFETTI_COLORS[seed % len(CONFETTI_COLORS)]
                    # Flicker: some confetti dim, some bright
                    dim = ((seed + int(now * 8)) % 3) == 0
                    buf.put(cx, cy, confetti_ch, Style(fg=confetti_color, dim=dim))

    # Bottom section: the celebration
    bottom_y = title_y + 3
    bottom_elapsed = elapsed - BOTTOM_START

    if bottom_elapsed > 0:
        # Phase 1: ASCII art celebration explodes in (scan reveal)
        art_p = _progress(elapsed, BOTTOM_START, 0.8)
        if art_p > 0:
            art_h = len(CELEBRATION_ART)
            art_w = max(len(l) for l in CELEBRATION_ART)
            art_x = max(0, (width - art_w) // 2)

            total_chars = sum(len(l) for l in CELEBRATION_ART)
            revealed = int(_ease_out_cubic(art_p) * total_chars)
            count = 0

            for row_i, line in enumerate(CELEBRATION_ART):
                for col_i, ch in enumerate(line):
                    if count >= revealed:
                        break
                    count += 1
                    if ch == " ":
                        continue
                    bx = art_x + col_i
                    by = bottom_y + row_i
                    if 0 <= by < height and 0 <= bx < width:
                        # Stars/symbols get rainbow colors, box chars get cyan
                        if ch in "╭╮╰╯─│":
                            buf.put(bx, by, ch, Style(fg="cyan", dim=True))
                        elif ch in "✦✧★◆◇":
                            hue = (col_i * 0.1 + now * 0.6) % 1.0
                            buf.put(bx, by, ch, Style(fg=_hue_to_rgb(hue)))
                        elif ch == "." or ch == "*":
                            dim = ((int(now * 4) + col_i) % 3) == 0
                            buf.put(bx, by, ch, Style(fg="#ffd93d", dim=dim))
                        else:
                            # "just cells" text inside the box
                            buf.put(bx, by, ch, Style(fg="white", bold=True))

        # Phase 2: Taglines appear below the art, one by one
        tagline_base_y = bottom_y + len(CELEBRATION_ART) + 1
        for i, (emoji, text, color) in enumerate(TAGLINES):
            tag_start = BOTTOM_START + 1.0 + i * 0.4
            tag_p = _progress(elapsed, tag_start, 0.3)
            if tag_p > 0:
                full_text = f"  {emoji} {text} {emoji}  "
                visible = int(tag_p * len(full_text))
                display = full_text[:visible]
                tx = max(0, (width - len(full_text)) // 2)
                ty = tagline_base_y + i

                if ty < height:
                    # After fully revealed, rainbow cycle the text
                    if tag_p >= 1.0:
                        col = tx
                        for ci, ch in enumerate(display):
                            cw = max(1, _wcw(ch))
                            if ch.strip():
                                hue = (ci * 0.06 + now * 0.3 + i * 0.33) % 1.0
                                buf.put(col, ty, ch, Style(fg=_hue_to_rgb(hue), bold=True))
                            col += cw
                    else:
                        buf.put_text(tx, ty, display, Style(fg=color, bold=True))

        # Phase 3: Emoji wave row
        wave_start = BOTTOM_START + 2.5
        wave_p = _progress(elapsed, wave_start, 0.3)
        if wave_p > 0:
            wave_y = tagline_base_y + len(TAGLINES) + 1
            if wave_y < height - 2:
                # Fill a row with wave emojis, each bouncing with phase offset
                wave_width = min(width - 4, 50)
                wave_x = max(0, (width - wave_width) // 2)
                wave_chars = CONFETTI_CHARS + "★✦✧"
                for wi in range(wave_width):
                    if wi >= int(wave_p * wave_width):
                        break
                    ch = wave_chars[wi % len(wave_chars)]
                    y_off = round(math.sin(now * 4.0 + wi * 0.4) * 0.7)
                    wy = wave_y + y_off
                    hue = (wi * 0.05 + now * 0.5) % 1.0
                    if 0 <= wy < height:
                        buf.put(wave_x + wi, wy, ch, Style(fg=_hue_to_rgb(hue), bold=True))

        # Phase 4: "go build something." — the calm after the storm
        closer_start = BOTTOM_START + 3.0
        if elapsed >= closer_start:
            closer_y = tagline_base_y + len(TAGLINES) + 3
            if closer_y < height:
                closer_text = "go build something. 🚀"
                closer_p = min(1.0, (elapsed - closer_start) / 0.4)
                visible = closer_text[:int(closer_p * len(closer_text))]
                cx = max(0, (width - len(closer_text)) // 2)
                buf.put_text(cx, closer_y, visible, ACCENT)

    # Convert buffer to Block
    rows = []
    for y in range(height):
        row = [buf.get(x, y) for x in range(width)]
        rows.append(row)
    return Block(rows, width)


# -- Helpers --

def _centered_text(text: str, width: int, style: Style) -> Block:
    padding = max(0, (width - len(text)) // 2)
    cells = [Cell(" ", Style())] * padding
    cells.extend(Cell(ch, style) for ch in text)
    remaining = width - len(cells)
    if remaining > 0:
        cells.extend([Cell(" ", Style())] * remaining)
    return Block([cells[:width]], width)


def _line_to_block(line: Line, width: int, indent: int = 0) -> Block:
    from render.buffer import Buffer
    buf = Buffer(width, 1)
    view = buf.region(0, 0, width, 1)
    line.paint(view, indent, 0)
    cells = [buf.get(x, 0) for x in range(width)]
    return Block([cells], width)


# -- App --

class DemoApp(RenderApp):

    def __init__(self):
        super().__init__(fps_cap=30)
        self._state = DemoState()
        self._last_tick = time.monotonic()
        self._reveal_tick = time.monotonic()

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def update(self) -> None:
        now = time.monotonic()

        # Spinner ticks (100ms)
        if now - self._last_tick >= 0.1:
            self._state = replace(
                self._state,
                spinner_state=self._state.spinner_state.tick(),
                spinner_braille=self._state.spinner_braille.tick(),
                spinner_line=self._state.spinner_line.tick(),
            )
            self._last_tick = now
            self.mark_dirty()

        # Title reveal animation (30ms per char for a typing feel)
        if self._state.stage == 0:
            total = sum(len(l) for l in TITLE_LINES) + len(TITLE_LINES)
            if self._state.reveal_chars < total:
                if now - self._reveal_tick >= 0.03:
                    self._state = replace(
                        self._state,
                        reveal_chars=self._state.reveal_chars + 1,
                    )
                    self._reveal_tick = now
                    self.mark_dirty()

        # Finale: always redraw (rainbow + wave + confetti are perpetual)
        if self._state.stage == 6 and self._state.finale_start > 0:
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        width = self._buf.width
        height = self._buf.height

        self._buf.fill(0, 0, width, height, " ", Style())

        content = self._render_stage(width, height - 1)
        content.paint(self._buf, 0, 0)

        footer = self._render_footer(width)
        footer.paint(self._buf, 0, height - 1)

    def _render_stage(self, width: int, height: int) -> Block:
        s = self._state.stage
        if s == 0:
            return _render_title(self._state, width, height)
        elif s == 1:
            return _render_spans(self._state, width, height)
        elif s == 2:
            return _render_lines(width, height)
        elif s == 3:
            return _render_theme(self._state, width, height)
        elif s == 4:
            return _render_blocks(self._state, width, height)
        elif s == 5:
            return _render_components(self._state, width, height)
        elif s == 6:
            return _render_finale(self._state, width, height)
        return Block.empty(width, height)

    def _render_footer(self, width: int) -> Block:
        parts: list[Cell] = []

        # Nav hints
        parts.append(Cell(" ", FOOTER_BASE))
        for ch in "← →":
            parts.append(Cell(ch, NAV_KEY))
        for ch in " pages":
            parts.append(Cell(ch, NAV_TEXT))
        parts.append(Cell(" ", FOOTER_BASE))
        parts.append(Cell(" ", FOOTER_BASE))

        # Stage dots
        for i in range(NUM_STAGES):
            ch = "●" if i == self._state.stage else "·"
            style = DOT_ACTIVE if i == self._state.stage else DOT_INACTIVE
            parts.append(Cell(ch, style))
            if i < NUM_STAGES - 1:
                parts.append(Cell(" ", FOOTER_BASE))

        parts.append(Cell(" ", FOOTER_BASE))
        parts.append(Cell(" ", FOOTER_BASE))

        # Stage title
        title = STAGE_TITLES[self._state.stage]
        for ch in title:
            parts.append(Cell(ch, Style(bold=True, bg=FOOTER_BG)))

        # Right side
        right = f" q:quit "
        right_start = width - len(right)
        while len(parts) < right_start:
            parts.append(Cell(" ", FOOTER_BASE))
        for ch in right:
            parts.append(Cell(ch, NAV_TEXT))

        while len(parts) < width:
            parts.append(Cell(" ", FOOTER_BASE))
        return Block([parts[:width]], width)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self.quit()
            return

        if key == "right":
            if self._state.stage < NUM_STAGES - 1:
                new_stage = self._state.stage + 1
                updates = {"stage": new_stage}
                if new_stage == 6:
                    updates["finale_start"] = time.monotonic()
                self._state = replace(self._state, **updates)
            return

        if key == "left":
            if self._state.stage > 0:
                new_stage = self._state.stage - 1
                self._state = replace(self._state, stage=new_stage)
            return

        # Stage-specific input
        stage = self._state.stage

        # Spans: typing + style toggles
        if stage == 1:
            if key == "b":
                self._state = replace(self._state, span_bold=not self._state.span_bold)
            elif key == "d":
                self._state = replace(self._state, span_dim=not self._state.span_dim)
            elif key == "i":
                self._state = replace(self._state, span_italic=not self._state.span_italic)
            elif key == "u":
                self._state = replace(self._state, span_underline=not self._state.span_underline)
            elif key == "r":
                self._state = replace(self._state, span_reverse=not self._state.span_reverse)
            elif key == "c":
                self._state = replace(
                    self._state,
                    span_color_index=(self._state.span_color_index + 1) % len(SPAN_COLORS),
                )
            elif key == "backspace":
                self._state = replace(self._state, input_state=self._state.input_state.delete_back())
            elif len(key) == 1 and key.isprintable() and key not in "bdiurc":
                self._state = replace(self._state, input_state=self._state.input_state.insert(key))
            return

        # Theme: palette selection
        if stage == 3:
            if key in ("up", "k"):
                new_idx = (self._state.theme_index - 1) % len(THEME_PALETTES)
                self._state = replace(self._state, theme_index=new_idx)
            elif key in ("down", "j"):
                new_idx = (self._state.theme_index + 1) % len(THEME_PALETTES)
                self._state = replace(self._state, theme_index=new_idx)
            return

        # Blocks: cycle borders
        if stage == 4:
            if key == " ":
                self._state = replace(
                    self._state,
                    border_index=(self._state.border_index + 1) % len(BORDER_PRESETS),
                )
            return

        # Components: list navigation
        if stage == 5:
            if key in ("up", "k"):
                self._state = replace(self._state, list_state=self._state.list_state.move_up())
            elif key in ("down", "j"):
                self._state = replace(self._state, list_state=self._state.list_state.move_down())
            return


# -- Entry point --

async def main():
    app = DemoApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
