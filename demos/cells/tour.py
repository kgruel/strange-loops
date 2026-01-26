#!/usr/bin/env python3
"""Tour: Spatial navigation through cells concepts.

Navigation model — three axes:
  Left/Right (←→): Core concept chain
    Cell → Style → Span → Line → Block → Buffer → Lens → Surface
  Down (↓): Detail / implementation / internals
  Up (↑): Visual demos / compositions / fun

Run: uv run python demos/cells/tour.py
"""

from __future__ import annotations

import argparse
import asyncio
import textwrap
import time
from dataclasses import dataclass, field, replace
from typing import Callable

from cells import (
    Surface, Block, Style, Span, Line,
    join_horizontal, join_vertical, pad, border, truncate,
    ROUNDED, HEAVY,
    Focus,
    Layer, Stay, Pop, Push, Quit, process_key, render_layers,
    BufferView,
    SpinnerState, spinner, DOTS, BRAILLE, LINE,
    ProgressState, progress_bar,
    ListState, list_view,
    TextInputState, text_input,
    Column, TableState, table,
    print_block,
)


# ── Styles ──────────────────────────────────────────────────────────

TITLE_STYLE = Style(fg="cyan", bold=True)
SUBTITLE_STYLE = Style(fg="white", dim=True)
CODE_BORDER_STYLE = Style(fg="yellow", dim=True)
CODE_TITLE_STYLE = Style(fg="yellow", bold=True)
HINT_STYLE = Style(fg="white", dim=True, italic=True)
KEYWORD = Style(fg="cyan", bold=True)
EMPH = Style(fg="white", bold=True)

# Code highlighting
CODE_KEYWORD = Style(fg="magenta", bold=True)
CODE_BUILTIN = Style(fg="cyan")
CODE_STRING = Style(fg="green")
CODE_COMMENT = Style(fg="white", dim=True, italic=True)
CODE_NUMBER = Style(fg="yellow")
CODE_DECORATOR = Style(fg="yellow")
CODE_DEFAULT = Style(fg="white")

PY_KEYWORDS = {
    "def", "class", "return", "if", "else", "elif", "for", "while", "in",
    "import", "from", "as", "try", "except", "finally", "with", "yield",
    "lambda", "and", "or", "not", "is", "None", "True", "False", "async", "await",
}
PY_BUILTINS = {
    "print", "len", "range", "str", "int", "float", "list", "dict", "tuple",
    "set", "bool", "type", "isinstance", "hasattr", "getattr", "setattr",
    "property", "staticmethod", "classmethod", "super", "self", "max", "min",
}

# Nav bar colors per stop
STOP_COLORS = [
    "red",       # Cell
    "#ff6b35",   # Style
    "yellow",    # Span
    "green",     # Line
    "cyan",      # Block
    "blue",      # Buffer
    "magenta",   # Lens
    "#cc66ff",   # Surface
]


# ── Helpers ─────────────────────────────────────────────────────────

def styled(*parts: str | tuple[str, Style]) -> Line:
    """Create a Line from alternating text and styled segments."""
    spans = []
    for part in parts:
        if isinstance(part, str):
            spans.append(Span(part, SUBTITLE_STYLE))
        else:
            text, style = part
            spans.append(Span(text, style))
    return Line(spans=tuple(spans))


def highlight_line(text: str) -> Line:
    """Apply basic Python syntax highlighting to a line of code."""
    if not text.strip():
        return Line.plain(text, CODE_DEFAULT)

    spans: list[Span] = []
    i = 0

    while i < len(text):
        if text[i] in ' \t':
            j = i
            while j < len(text) and text[j] in ' \t':
                j += 1
            spans.append(Span(text[i:j], CODE_DEFAULT))
            i = j
            continue

        if text[i] == '#':
            spans.append(Span(text[i:], CODE_COMMENT))
            break

        if text[i] == '@':
            j = i + 1
            while j < len(text) and (text[j].isalnum() or text[j] == '_'):
                j += 1
            spans.append(Span(text[i:j], CODE_DECORATOR))
            i = j
            continue

        if text[i] in '"\'':
            quote = text[i]
            if text[i:i+3] in ('"""', "'''"):
                quote = text[i:i+3]
            j = i + len(quote)
            while j < len(text):
                if text[j] == '\\' and j + 1 < len(text):
                    j += 2
                elif text[j:j+len(quote)] == quote:
                    j += len(quote)
                    break
                else:
                    j += 1
            spans.append(Span(text[i:j], CODE_STRING))
            i = j
            continue

        if text[i].isdigit():
            j = i
            while j < len(text) and (text[j].isdigit() or text[j] == '.'):
                j += 1
            spans.append(Span(text[i:j], CODE_NUMBER))
            i = j
            continue

        if text[i].isalpha() or text[i] == '_':
            j = i
            while j < len(text) and (text[j].isalnum() or text[j] == '_'):
                j += 1
            word = text[i:j]
            if word in PY_KEYWORDS:
                spans.append(Span(word, CODE_KEYWORD))
            elif word in PY_BUILTINS:
                spans.append(Span(word, CODE_BUILTIN))
            else:
                spans.append(Span(word, CODE_DEFAULT))
            i = j
            continue

        spans.append(Span(text[i], CODE_DEFAULT))
        i += 1

    return Line(spans=tuple(spans)) if spans else Line.plain("", CODE_DEFAULT)


def render_code_block(source: str, width: int, title: str = "", center: bool = True) -> Block:
    """Render source code in a bordered box with syntax highlighting."""
    source_lines = source.strip().split('\n')
    highlighted = [highlight_line(line) for line in source_lines]
    max_w = max((line.width for line in highlighted), default=0)

    code_blocks = [line.to_block(max_w) for line in highlighted]
    content = join_vertical(*code_blocks) if code_blocks else Block.empty(1, 1)
    content = pad(content, left=1, right=1)

    bordered = border(
        content, ROUNDED, CODE_BORDER_STYLE,
        title=title if title else None,
        title_style=CODE_TITLE_STYLE,
    )

    if center:
        padding = max(0, (width - bordered.width) // 2)
        return pad(bordered, left=padding)
    return bordered


def centered_text(line: Line, width: int) -> Block:
    """Render a styled Line centered in the given width."""
    block = line.to_block(line.width)
    padding = max(0, (width - block.width) // 2)
    return pad(block, left=padding)


def centered_plain(text: str, style: Style, width: int) -> Block:
    """Render plain text centered."""
    block = Block.text(text, style)
    padding = max(0, (width - block.width) // 2)
    return pad(block, left=padding)


# ── Stop Content ────────────────────────────────────────────────────
#
# Each stop defines content at depth levels:
#   depth  0: main introduction (the default view)
#   depth  1: detail / internals (down once)
#   depth  2: more detail (down twice, if available)
#   depth -1: visual / demo / fun (up once)
#   depth -2: more visual (up twice, if available)
#
# Content functions: (width: int) -> list[Block]

def _cell_main(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled("the atomic unit: one ", ("character", KEYWORD), " + one ", ("style", KEYWORD)),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            'cell = Cell("A", Style(fg="red", bold=True))',
            w, title="cell.py",
        ),
        Block.empty(w, 1),
        centered_plain("a Cell is one character with visual attributes", HINT_STYLE, w),
    ]


def _cell_down(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled(("Cell", KEYWORD), " is a frozen dataclass — ", ("immutable", EMPH), " by design"),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''@dataclass(frozen=True)
class Cell:
    """A single cell: one character + one style."""
    char: str = " "
    style: Style = field(default_factory=Style)

    def __post_init__(self):
        if len(self.char) != 1:
            object.__setattr__(self, "char", self.char[0] if self.char else " ")

EMPTY_CELL = Cell(" ", Style())''',
            w, title="cell.py — definition",
        ),
        Block.empty(w, 1),
        centered_text(
            styled(("EMPTY_CELL", KEYWORD), " is the default for unfilled buffer positions"),
            w,
        ),
    ]


def _style_main(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(styled("colors and attributes for rendering"), w),
        Block.empty(w, 1),
        render_code_block(
            '''Style(fg="red")           # foreground color
Style(bg="blue")          # background color
Style(bold=True)          # bold text
Style(fg="#ff6b35")       # hex colors
Style(fg=196)             # 256-palette''',
            w, title="style.py",
        ),
    ]


def _style_up(w: int) -> list[Block]:
    """Color palette demo."""
    rows: list[Block] = []
    rows.append(Block.empty(w, 1))
    rows.append(centered_text(styled("color palette showcase"), w))
    rows.append(Block.empty(w, 1))

    # Named colors
    named = ["red", "green", "yellow", "blue", "magenta", "cyan", "white"]
    color_blocks = [Block.text(f" {c} ", Style(fg="black", bg=c)) for c in named]
    palette_row = join_horizontal(*color_blocks, gap=1)
    rows.append(centered_text(styled("named colors:"), w))
    rows.append(Block.empty(w, 1))
    p = max(0, (w - palette_row.width) // 2)
    rows.append(pad(palette_row, left=p))

    rows.append(Block.empty(w, 1))

    # Attributes
    attrs = [
        Block.text(" bold ", Style(bold=True)),
        Block.text(" dim ", Style(dim=True)),
        Block.text(" italic ", Style(italic=True)),
        Block.text(" underline ", Style(underline=True)),
        Block.text(" reverse ", Style(reverse=True)),
    ]
    attr_row = join_horizontal(*attrs, gap=1)
    rows.append(centered_text(styled("attributes:"), w))
    rows.append(Block.empty(w, 1))
    p2 = max(0, (w - attr_row.width) // 2)
    rows.append(pad(attr_row, left=p2))

    return rows


def _style_down(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(styled(("Style", KEYWORD), " attributes — all optional, all composable"), w),
        Block.empty(w, 1),
        render_code_block(
            '''@dataclass(frozen=True)
class Style:
    fg: str | int | None = None   # foreground
    bg: str | int | None = None   # background
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False

    def merge(self, other: "Style") -> "Style":
        """Merge styles; other wins on conflict."""''',
            w, title="full signature",
        ),
        Block.empty(w, 1),
        centered_text(
            styled(("Style.merge(other)", KEYWORD), " combines styles — other wins on conflict"),
            w,
        ),
    ]


def _span_main(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(styled("a run of text with one ", ("style", KEYWORD)), w),
        Block.empty(w, 1),
        render_code_block(
            '''span = Span("hello", Style(fg="green", bold=True))
# span.text = "hello"
# span.width = 5''',
            w, title="span.py",
        ),
    ]


def _span_down(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled(("Span", KEYWORD), " handles wide characters via ", ("wcwidth", EMPH)),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''@dataclass(frozen=True)
class Span:
    text: str
    style: Style = Style()

    @property
    def width(self) -> int:
        # accounts for CJK double-width chars
        return span_width(self.text)''',
            w, title="definition",
        ),
        Block.empty(w, 1),
        centered_text(
            styled(("span.width", KEYWORD), " is display width, not ", ("len(text)", KEYWORD)),
            w,
        ),
    ]


def _line_main(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(styled("a sequence of ", ("Spans", KEYWORD), " — styled inline text"), w),
        Block.empty(w, 1),
        render_code_block(
            '''line = Line(spans=(
    Span("error: ", Style(fg="red", bold=True)),
    Span("file not found", Style(fg="white")),
))
# line.width = 21''',
            w, title="line.py",
        ),
    ]


def _line_down(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled(("Line", KEYWORD), " is a sequence of ", ("Spans", KEYWORD)),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''@dataclass(frozen=True)
class Line:
    spans: tuple[Span, ...] = ()
    style: Style | None = None  # fallback style

    @property
    def width(self) -> int:
        return sum(s.width for s in self.spans)

    def paint(self, view: BufferView, x: int, y: int) -> int:
        for span in self.spans:
            view.put_text(x, y, span.text, span.style)
            x += span.width
        return x''',
            w, title="definition",
        ),
        Block.empty(w, 1),
        centered_text(
            styled(("Line.plain(text, style)", KEYWORD), " — convenience constructor"),
            w,
        ),
    ]


def _block_main(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled("immutable rectangle of ", ("Cells", KEYWORD), " — the composition unit"),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''block = Block.text("hello", Style(fg="cyan"))
# block.width = 5, block.height = 1

block.paint(buf, x=10, y=5)  # copy into buffer''',
            w, title="block.py",
        ),
    ]


def _block_up(w: int) -> list[Block]:
    """Composition operations — the visual payoff of understanding Block."""
    rows: list[Block] = []
    rows.append(Block.empty(w, 1))
    rows.append(centered_text(styled("composition operations on ", ("Block", KEYWORD)), w))
    rows.append(Block.empty(w, 1))

    # Demo: join_horizontal
    a = border(Block.text(" A ", Style(fg="red")), ROUNDED, Style(fg="red", dim=True))
    b = border(Block.text(" B ", Style(fg="green")), ROUNDED, Style(fg="green", dim=True))
    c = border(Block.text(" C ", Style(fg="blue")), ROUNDED, Style(fg="blue", dim=True))
    joined_h = join_horizontal(a, b, c, gap=1)

    rows.append(centered_text(styled(("join_horizontal", KEYWORD), "(a, b, c)"), w))
    rows.append(Block.empty(w, 1))
    ph = max(0, (w - joined_h.width) // 2)
    rows.append(pad(joined_h, left=ph))
    rows.append(Block.empty(w, 1))

    # Demo: join_vertical
    joined_v = join_vertical(a, b, c)
    rows.append(centered_text(styled(("join_vertical", KEYWORD), "(a, b, c)"), w))
    rows.append(Block.empty(w, 1))
    pv = max(0, (w - joined_v.width) // 2)
    rows.append(pad(joined_v, left=pv))
    rows.append(Block.empty(w, 1))

    # Demo: pad + border
    inner = Block.text(" padded + bordered ", Style(fg="yellow"))
    padded = pad(inner, left=2, right=2, top=1, bottom=1)
    bordered = border(padded, ROUNDED, Style(fg="yellow", dim=True))
    rows.append(centered_text(styled(("border", KEYWORD), "(", ("pad", KEYWORD), "(block))"), w))
    rows.append(Block.empty(w, 1))
    pb = max(0, (w - bordered.width) // 2)
    rows.append(pad(bordered, left=pb))

    return rows


def _block_down(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled(("Block", KEYWORD), " stores rows of ", ("Cells", KEYWORD), " — ", ("immutable", EMPH)),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''@dataclass(frozen=True)
class Block:
    rows: list[list[Cell]]
    width: int

    @classmethod
    def text(cls, text: str, style: Style) -> Block:
        # create block from string

    @classmethod
    def empty(cls, width: int, height: int) -> Block:
        # create blank block

    def paint(self, view: BufferView, x: int, y: int):
        # copy this block into the buffer view''',
            w, title="definition",
        ),
        Block.empty(w, 1),
        centered_text(
            styled("compose via ", ("join", KEYWORD), ", ", ("pad", KEYWORD), ", ", ("border", KEYWORD)),
            w,
        ),
    ]


def _buffer_main(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(styled("the 2D canvas — a mutable grid of ", ("Cells", KEYWORD)), w),
        Block.empty(w, 1),
        render_code_block(
            '''buf = Buffer(80, 24)
buf.put(0, 0, "A", Style(fg="red"))
buf.put_text(0, 1, "hello", Style())
buf.fill(10, 10, 5, 3, "X", Style(fg="blue"))''',
            w, title="buffer.py",
        ),
        Block.empty(w, 1),
        centered_text(
            styled(("BufferView", KEYWORD), " provides clipped, translated regions"),
            w,
        ),
    ]


def _buffer_down(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled(("BufferView", KEYWORD), " — write without bounds checking"),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''view = buf.region(10, 5, 20, 10)
# view.width = 20, view.height = 10
# writes at (0,0) in view -> (10,5) in buffer
# writes outside view bounds are silently clipped''',
            w, title="bufferview",
        ),
        Block.empty(w, 1),
        render_code_block(
            '''class Buffer:
    def __init__(self, width: int, height: int):
        self._cells = [[EMPTY_CELL] * width for _ in range(height)]

    def put(self, x: int, y: int, char: str, style: Style):
        if 0 <= x < self._width and 0 <= y < self._height:
            self._cells[y][x] = Cell(char, style)

    def region(self, x: int, y: int, w: int, h: int) -> BufferView:
        return BufferView(self, x, y, w, h)''',
            w, title="buffer.py — definition",
        ),
    ]


def _lens_main(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled("state → ", ("Block", KEYWORD), " — a rendering function"),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''def my_lens(state: MyState, width: int, height: int) -> Block:
    """Pure function: state in, Block out."""
    title = Block.text(state.name, Style(fg="cyan"))
    body = Block.text(state.value, Style())
    return join_vertical(title, body)''',
            w, title="lens.py",
        ),
        Block.empty(w, 1),
        centered_text(
            styled("the ", ("Shape", KEYWORD), " integration — fold produces state, ", ("Lens", KEYWORD), " renders it"),
            w,
        ),
    ]


def _lens_down(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled("the Shape → Lens connection"),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''# ticks owns data transformation:
#   Projection[S, E]: fold events into state
#   shape.apply(state, payload) -> state

# cells owns visual transformation:
#   Lens: render state at zoom level into Block
#   shape_lens auto-renders dicts, lists, sets

lens = shape_lens(my_shape)
block = lens.render(state, width, height)''',
            w, title="shape integration",
        ),
        Block.empty(w, 1),
        centered_text(
            styled(("shape_lens", KEYWORD), " renders any Python value: dict→table, list→list, set→tags"),
            w,
        ),
    ]


def _surface_main(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(
            styled(
                "the application loop — ",
                ("keyboard", KEYWORD), ", ",
                ("resize", KEYWORD), ", ",
                ("diff rendering", KEYWORD),
            ),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''class MyApp(Surface):
    def render(self):
        # paint into self._buf

    def on_key(self, key: str):
        if key == "q":
            self.quit()''',
            w, title="app.py",
        ),
        Block.empty(w, 1),
        centered_text(
            styled("you're inside a ", ("Surface", KEYWORD), " right now"),
            w,
        ),
    ]


def _surface_up(w: int) -> list[Block]:
    """Layer stacking and FocusRing."""
    return [
        Block.empty(w, 1),
        centered_text(styled(("Layer", KEYWORD), " — modal stacking"), w),
        Block.empty(w, 1),
        render_code_block(
            '''# Layer stack: top layer handles keys, all render bottom-to-top
Layer(
    name="confirm",
    state=ConfirmState(),
    handle=handle_confirm,  # (key, layer_state, app_state) -> (ls, as, Action)
    render=render_confirm,  # (layer_state, app_state, view) -> None
)

# Actions: Stay | Pop(result) | Push(new_layer) | Quit''',
            w, title="layer.py",
        ),
        Block.empty(w, 1),
        centered_text(
            styled(("FocusRing", KEYWORD), " — component focus management"),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''focus = Focus(id="sidebar")
focus = focus.capture()   # widget handles keys
focus = focus.release()   # nav handles keys

# Navigation: ring_next wraps, linear_next stops
ring_next(items, current)    # "c" -> "a" (wraps)
linear_next(items, current)  # "c" -> "c" (stops)''',
            w, title="focus.py",
        ),
    ]


def _surface_down(w: int) -> list[Block]:
    return [
        Block.empty(w, 1),
        centered_text(styled(("Writer", KEYWORD), " — the ANSI flush mechanism"), w),
        Block.empty(w, 1),
        render_code_block(
            '''class Surface:
    """Async main loop with diff-based rendering."""

    async def run(self):
        self._writer.enter_alt_screen()
        try:
            while not self._quit:
                for key in self._keyboard.read():
                    self.on_key(key)
                self.update()
                if self._dirty:
                    self.render()
                    self._flush()
                await asyncio.sleep(1 / self._fps_cap)
        finally:
            self._writer.exit_alt_screen()''',
            w, title="app.py — the loop",
        ),
        Block.empty(w, 1),
        centered_text(
            styled("the ", ("Emit", KEYWORD), " protocol closes the feedback loop"),
            w,
        ),
        Block.empty(w, 1),
        render_code_block(
            '''# Emit = Callable[[str, dict], None]
# Surface emits observations that become Facts upstream
#
# Three strata:
#   Raw input  (auto)   "ui.key"    {key: "j"}
#   UI action  (auto)   "ui.action" {action: "pop", layer: "confirm"}
#   Domain     (manual)  (any)   {item: "deploy-prod"}''',
            w, title="emit protocol",
        ),
    ]


# ── Stop Registry ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Stop:
    """A stop on the horizontal concept chain.

    name: display name for the nav bar
    depths: dict mapping depth level -> content function
        0 = main, positive = detail, negative = visual/fun
    """
    name: str
    depths: dict[int, Callable[[int], list[Block]]]

    @property
    def min_depth(self) -> int:
        return min(self.depths.keys())

    @property
    def max_depth(self) -> int:
        return max(self.depths.keys())


STOPS: tuple[Stop, ...] = (
    Stop("Cell",    {0: _cell_main, 1: _cell_down}),
    Stop("Style",   {-1: _style_up, 0: _style_main, 1: _style_down}),
    Stop("Span",    {0: _span_main, 1: _span_down}),
    Stop("Line",    {0: _line_main, 1: _line_down}),
    Stop("Block",   {-1: _block_up, 0: _block_main, 1: _block_down}),
    Stop("Buffer",  {0: _buffer_main, 1: _buffer_down}),
    Stop("Lens",    {0: _lens_main, 1: _lens_down}),
    Stop("Surface", {-1: _surface_up, 0: _surface_main, 1: _surface_down}),
)


# ── Nav Bar ─────────────────────────────────────────────────────────

def render_nav_bar(stop_index: int, depth: int, width: int) -> Block:
    """Render the bottom nav bar showing all 8 stops.

    Selected stop is bright with its color. Others are dim.
    Arrows (→) between stops indicate flow direction.
    """
    parts: list[Block] = []
    total_names = sum(len(s.name) + 2 for s in STOPS)  # +2 for padding
    total_arrows = len(STOPS) - 1
    total_min = total_names + total_arrows * 3  # " → " = 3 chars

    # If terminal is too narrow, abbreviate
    abbreviate = width < total_min + 4

    for i, stop in enumerate(STOPS):
        color = STOP_COLORS[i]
        name = stop.name

        if abbreviate:
            # Use first 3 chars
            name = name[:3]

        if i == stop_index:
            # Selected: bright, colored background
            block = Block.text(f" {name} ", Style(fg="black", bg=color, bold=True))
        else:
            # Unselected: dim
            block = Block.text(f" {name} ", Style(fg=color, dim=True))

        parts.append(block)

        # Arrow between stops (not after last)
        if i < len(STOPS) - 1:
            if abbreviate:
                parts.append(Block.text("→", Style(dim=True)))
            else:
                parts.append(Block.text(" → ", Style(dim=True)))

    nav_row = join_horizontal(*parts)

    # Depth indicator on the right
    stop = STOPS[stop_index]
    depth_parts: list[Block] = []

    if depth > 0:
        depth_parts.append(Block.text(f" ↓{depth}", Style(fg="cyan", dim=True)))
    elif depth < 0:
        depth_parts.append(Block.text(f" ↑{abs(depth)}", Style(fg="magenta", dim=True)))

    # Vertical nav hints
    can_up = depth > stop.min_depth
    can_down = depth < stop.max_depth
    if can_up or can_down:
        hints = []
        if can_up:
            hints.append("↑")
        if can_down:
            hints.append("↓")
        depth_parts.append(Block.text(" " + "/".join(hints), Style(dim=True)))

    if depth_parts:
        right_side = join_horizontal(*depth_parts)
    else:
        right_side = Block.empty(1, 1)

    # Help hint
    help_hint = Block.text(" ?:help q:quit ", Style(dim=True))

    # Assemble: nav centered, hints on right
    spacer_w = max(1, width - nav_row.width - right_side.width - help_hint.width - 2)
    spacer = Block.empty(spacer_w, 1)

    bar = join_horizontal(
        Block.text(" ", Style()),
        nav_row,
        spacer,
        right_side,
        help_hint,
    )

    return bar


# ── State ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TourState:
    """Application state for the tour."""
    stop_index: int = 0
    depth: int = 0
    width: int = 80
    height: int = 24
    layers: tuple[Layer, ...] = ()


# ── Layer Accessors ─────────────────────────────────────────────────

def get_layers(state: TourState) -> tuple[Layer, ...]:
    return state.layers


def set_layers(state: TourState, layers: tuple[Layer, ...]) -> TourState:
    return replace(state, layers=layers)


# ── Help Overlay ────────────────────────────────────────────────────

HELP_CONTENT = [
    ("Navigation", [
        ("← →  (left right)", "move between concept stops"),
        ("↑ ↓  (up down)", "change depth (more visual / more detail)"),
        ("?", "toggle this help"),
        ("q / esc", "quit"),
    ]),
    ("Concept Chain", [
        ("Cell → Style → Span → Line", "construction primitives"),
        ("Block → Buffer", "construction surfaces"),
        ("Lens → Surface", "orchestration"),
    ]),
    ("Depth", [
        ("↑  up", "visual / fun / demos"),
        ("↓  down", "detail / internals / source"),
    ]),
]


def render_help(width: int, height: int) -> Block:
    """Render the help overlay."""
    rows: list[Block] = []

    title = Block.text(" Keyboard Shortcuts ", Style(fg="cyan", bold=True))
    rows.append(title)
    rows.append(Block.empty(1, 1))

    for section_name, bindings in HELP_CONTENT:
        rows.append(Block.text(f" {section_name}", Style(fg="white", bold=True)))
        rows.append(Block.empty(1, 1))

        for key, desc in bindings:
            key_block = Block.text(f"  {key:24}", Style(fg="yellow"))
            desc_block = Block.text(desc, Style(dim=True))
            rows.append(join_horizontal(key_block, desc_block))

        rows.append(Block.empty(1, 1))

    rows.append(Block.text(" press ? or esc to close ", HINT_STYLE))

    content = join_vertical(*rows)
    content = pad(content, left=2, right=2, top=1, bottom=1)
    boxed = border(content, ROUNDED, Style(fg="cyan"))

    pad_left = max(0, (width - boxed.width) // 2)
    pad_top = max(0, (height - boxed.height) // 2)

    return pad(boxed, left=pad_left, top=pad_top)


def _handle_help(key: str, layer_state: None, app_state: TourState) -> tuple[None, TourState, Stay | Pop | Push | Quit]:
    return None, app_state, Pop()


def _render_help(layer_state: None, app_state: TourState, view: BufferView) -> None:
    block = render_help(app_state.width, app_state.height)
    block.paint(view, 0, 0)


def make_help_layer() -> Layer[None]:
    return Layer(name="help", state=None, handle=_handle_help, render=_render_help)


# ── Nav Layer ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class NavLayerState:
    pass


def _handle_nav(key: str, layer_state: NavLayerState, app_state: TourState) -> tuple[NavLayerState, TourState, Stay | Pop | Push | Quit]:
    if key in ("q", "escape"):
        return layer_state, app_state, Quit()

    if key == "?":
        return layer_state, app_state, Push(make_help_layer())

    stop = STOPS[app_state.stop_index]

    if key == "left":
        if app_state.stop_index > 0:
            new_state = replace(app_state, stop_index=app_state.stop_index - 1, depth=0)
            return layer_state, new_state, Stay()

    elif key == "right":
        if app_state.stop_index < len(STOPS) - 1:
            new_state = replace(app_state, stop_index=app_state.stop_index + 1, depth=0)
            return layer_state, new_state, Stay()

    elif key == "up":
        if app_state.depth > stop.min_depth:
            new_state = replace(app_state, depth=app_state.depth - 1)
            return layer_state, new_state, Stay()

    elif key == "down":
        if app_state.depth < stop.max_depth:
            new_state = replace(app_state, depth=app_state.depth + 1)
            return layer_state, new_state, Stay()

    return layer_state, app_state, Stay()


def _render_nav(layer_state: NavLayerState, app_state: TourState, view: BufferView) -> None:
    width = app_state.width
    height = app_state.height
    stop = STOPS[app_state.stop_index]

    # ── Header ──
    color = STOP_COLORS[app_state.stop_index]
    title_block = Block.text(f" {stop.name} ", Style(fg=color, bold=True))
    title_pad = max(0, (width - title_block.width) // 2)
    header = pad(title_block, left=title_pad, top=1, bottom=1)
    header.paint(view, 0, 0)

    # ── Content ──
    content_y = header.height
    content_width = width - 4  # margins

    content_fn = stop.depths.get(app_state.depth)
    if content_fn:
        blocks = content_fn(content_width)
        if blocks:
            content = join_vertical(*blocks)
            content = pad(content, left=2)
            content.paint(view, 0, content_y)

    # ── Nav Bar (bottom) ──
    nav_bar = render_nav_bar(app_state.stop_index, app_state.depth, width)
    nav_bar.paint(view, 0, height - 1)


def make_nav_layer() -> Layer[NavLayerState]:
    return Layer(
        name="nav",
        state=NavLayerState(),
        handle=_handle_nav,
        render=_render_nav,
    )


# ── App ─────────────────────────────────────────────────────────────

class TourApp(Surface):
    """Interactive tour of cells concepts."""

    def __init__(self, start_stop: int = 0, start_depth: int = 0):
        super().__init__(fps_cap=30)
        self._state = TourState(
            stop_index=start_stop,
            depth=start_depth,
            layers=(make_nav_layer(),),
        )
        self._width = 80
        self._height = 24

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._state = replace(self._state, width=width, height=height)

    def update(self) -> None:
        pass

    def render(self) -> None:
        if self._buf is None:
            return
        self._buf.fill(0, 0, self._width, self._height, " ", Style())
        render_layers(self._state, self._buf, get_layers)

    def on_key(self, key: str) -> None:
        self._state, should_quit, _result = process_key(key, self._state, get_layers, set_layers)
        if should_quit:
            self.quit()


# ── Quiet Mode ──────────────────────────────────────────────────────

def run_quiet_mode() -> None:
    """Print all stops inline and exit."""
    import sys

    for i, stop in enumerate(STOPS):
        color = STOP_COLORS[i]

        # Print at each depth level, ordered from up to down
        for depth in sorted(stop.depths.keys()):
            depth_label = ""
            if depth < 0:
                depth_label = " (visual)"
            elif depth > 0:
                depth_label = " (detail)" if depth == 1 else f" (detail {depth})"

            title = Block.text(f"=== {stop.name}{depth_label} ===", Style(fg=color, bold=True))
            print_block(title, sys.stdout)
            print()

            content_fn = stop.depths[depth]
            blocks = content_fn(78)
            if blocks:
                content = join_vertical(*blocks)
                print_block(content, sys.stdout)
            print()


# ── CLI ─────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tour: Spatial navigation through cells concepts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Navigation:
              ← →  Move between concept stops
              ↑ ↓  Change depth (visual ↑ / detail ↓)
              ?    Help overlay
              q    Quit

            Concept chain:
              Cell → Style → Span → Line → Block → Buffer → Lens → Surface
        """),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Print all stops inline and exit (no TUI)",
    )
    group.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Start deeper (-v: detail level)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    if args.quiet:
        run_quiet_mode()
        return

    start_depth = min(args.verbose, 2)
    app = TourApp(start_stop=0, start_depth=start_depth)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
