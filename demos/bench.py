#!/usr/bin/env python3
"""Teaching Bench: Interactive educational platform for cells.

A 2D navigable space where:
- ←/→ moves between topics (sibling concepts)
- ↑/↓ moves between depths (same concept, more/less detail)

Run: uv run python demos/bench.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Callable

import time

from cells import (
    RenderApp, Block, Style, Span, Line,
    join_horizontal, join_vertical, pad, border,
    ROUNDED,
    # Focus management
    Focus, ring_next, ring_prev, linear_next, linear_prev,
    # Search
    Search, filter_contains, filter_prefix, filter_fuzzy,
    # Components for interactive demos
    SpinnerState, spinner, DOTS, BRAILLE, LINE,
    ProgressState, progress_bar,
    ListState, list_view,
    TextInputState, text_input,
    Column, TableState, table,
)


# -- Data Model --

@dataclass(frozen=True)
class Navigation:
    """Links to adjacent slides in 4 directions."""
    up: str | None = None
    down: str | None = None
    left: str | None = None
    right: str | None = None

    def has_any(self) -> bool:
        return any([self.up, self.down, self.left, self.right])


@dataclass(frozen=True)
class Text:
    """A text section with optional styling.

    content can be:
    - str: plain text with the given style
    - Line: pre-styled inline text (style field ignored)
    """
    content: str | Line
    style: Style = field(default_factory=Style)
    center: bool = False


@dataclass(frozen=True)
class Code:
    """A code section (source displayed in a box)."""
    source: str
    title: str = ""
    center: bool = True  # center the code block by default


@dataclass(frozen=True)
class Spacer:
    """Vertical space."""
    lines: int = 1


@dataclass(frozen=True)
class Demo:
    """An interactive demo widget embedded in a slide.

    demo_id identifies which demo to render (e.g., "spinner", "list", "text_input").
    The BenchState holds the actual component state.
    """
    demo_id: str
    label: str = ""
    center: bool = True


# Section is any of these types
Section = Text | Code | Spacer | Demo


@dataclass(frozen=True)
class Slide:
    """A single slide in the teaching bench."""
    id: str
    title: str
    sections: tuple[Section, ...] = ()
    nav: Navigation = field(default_factory=Navigation)
    on_key: Callable[[str, "BenchState"], "BenchState"] | None = None


@dataclass(frozen=True)
class BenchState:
    """Application state for the teaching bench."""
    current_slide: str = "intro"
    focus: Focus = field(default_factory=lambda: Focus(id="demo"))  # .captured = keys go to widget
    show_help: bool = False  # True = show help overlay

    # Component states for interactive demos
    spinner_state: SpinnerState = field(default_factory=SpinnerState)
    spinner_braille: SpinnerState = field(default_factory=lambda: SpinnerState(frames=BRAILLE))
    spinner_line: SpinnerState = field(default_factory=lambda: SpinnerState(frames=LINE))
    progress_state: ProgressState = field(default_factory=lambda: ProgressState(value=0.35))
    list_state: ListState = field(default_factory=lambda: ListState(item_count=5))
    text_state: TextInputState = field(default_factory=lambda: TextInputState(text="hello", cursor=5))
    table_state: TableState = field(default_factory=lambda: TableState(row_count=4))

    # Focus demo state
    focus_demo_item: str = "a"
    focus_demo_mode: str = "ring"  # "ring" or "linear"

    # Search demo state
    search_state: Search = field(default_factory=Search)
    search_mode: str = "contains"  # "contains", "prefix", "fuzzy"


# -- Styles --

TITLE_STYLE = Style(fg="cyan", bold=True)
SUBTITLE_STYLE = Style(fg="white", dim=True)
CODE_BORDER_STYLE = Style(fg="yellow", dim=True)
CODE_TITLE_STYLE = Style(fg="yellow", bold=True)
NAV_KEY_STYLE = Style(fg="cyan", bold=True)
NAV_DIM_STYLE = Style(dim=True)
POSITION_STYLE = Style(fg="magenta", dim=True)
HINT_STYLE = Style(fg="white", dim=True, italic=True)

# Inline styling helpers
KEYWORD = Style(fg="cyan", bold=True)  # for highlighting terms in prose
EMPH = Style(fg="white", bold=True)


def styled(*parts: str | tuple[str, Style]) -> Line:
    """Create a Line from alternating text and styled segments.

    Usage:
        styled("a ", ("Cell", KEYWORD), " is one character")
    """
    spans = []
    for part in parts:
        if isinstance(part, str):
            spans.append(Span(part, SUBTITLE_STYLE))
        else:
            text, style = part
            spans.append(Span(text, style))
    return Line(spans=tuple(spans))

# Code highlighting styles
CODE_KEYWORD = Style(fg="magenta", bold=True)
CODE_BUILTIN = Style(fg="cyan")
CODE_STRING = Style(fg="green")
CODE_COMMENT = Style(fg="white", dim=True, italic=True)
CODE_NUMBER = Style(fg="yellow")
CODE_DECORATOR = Style(fg="yellow")
CODE_DEFAULT = Style(fg="white")

# Python keywords for highlighting
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


# -- Code Highlighting --

def highlight_line(text: str) -> Line:
    """Apply basic Python syntax highlighting to a line of code."""
    if not text.strip():
        return Line.plain(text, CODE_DEFAULT)

    spans: list[Span] = []
    i = 0

    while i < len(text):
        # Leading whitespace
        if text[i] in ' \t':
            j = i
            while j < len(text) and text[j] in ' \t':
                j += 1
            spans.append(Span(text[i:j], CODE_DEFAULT))
            i = j
            continue

        # Comments
        if text[i] == '#':
            spans.append(Span(text[i:], CODE_COMMENT))
            break

        # Decorators
        if text[i] == '@':
            j = i + 1
            while j < len(text) and (text[j].isalnum() or text[j] == '_'):
                j += 1
            spans.append(Span(text[i:j], CODE_DECORATOR))
            i = j
            continue

        # Strings (simple handling)
        if text[i] in '"\'':
            quote = text[i]
            # Check for triple quote
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

        # Numbers
        if text[i].isdigit():
            j = i
            while j < len(text) and (text[j].isdigit() or text[j] == '.'):
                j += 1
            spans.append(Span(text[i:j], CODE_NUMBER))
            i = j
            continue

        # Identifiers and keywords
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

        # Operators and punctuation
        spans.append(Span(text[i], CODE_DEFAULT))
        i += 1

    return Line(spans=tuple(spans)) if spans else Line.plain("", CODE_DEFAULT)


# -- Section Renderers --


def render_text(section: Text, width: int) -> Block:
    """Render a text section."""
    if isinstance(section.content, Line):
        # Pre-styled Line
        line = section.content
        block = line.to_block(line.width)
    else:
        # Plain string
        block = Block.text(section.content, section.style)

    if section.center:
        padding = max(0, (width - block.width) // 2)
        return pad(block, left=padding)
    return block


def render_code(section: Code, width: int) -> Block:
    """Render a code section in a bordered box with syntax highlighting."""
    source_lines = section.source.strip().split('\n')

    # Highlight each line
    highlighted: list[Line] = [highlight_line(line) for line in source_lines]

    # Find max width
    max_width = max(line.width for line in highlighted) if highlighted else 0

    # Convert to blocks and pad
    code_blocks = []
    for line in highlighted:
        block = line.to_block(max_width)
        code_blocks.append(block)

    content = join_vertical(*code_blocks) if code_blocks else Block.empty(1, 1)
    content = pad(content, left=1, right=1)

    bordered = border(
        content,
        ROUNDED,
        CODE_BORDER_STYLE,
        title=section.title if section.title else None,
        title_style=CODE_TITLE_STYLE,
    )

    if section.center:
        padding = max(0, (width - bordered.width) // 2)
        return pad(bordered, left=padding)
    return bordered


def render_spacer(section: Spacer, width: int) -> Block:
    """Render vertical spacing."""
    return Block.empty(width, section.lines)


# Demo items for list_view
DEMO_LIST_ITEMS = [
    Line.plain("Apples", Style(fg="red")),
    Line.plain("Bananas", Style(fg="yellow")),
    Line.plain("Cherries", Style(fg="magenta")),
    Line.plain("Dates", Style(fg="#cc8800")),
    Line.plain("Elderberries", Style(fg="blue")),
]

# Demo data for table
DEMO_TABLE_COLUMNS = [
    Column(header=Line.plain("Name", Style(fg="cyan")), width=12),
    Column(header=Line.plain("Type", Style(fg="cyan")), width=10),
    Column(header=Line.plain("Size", Style(fg="cyan")), width=8),
]

DEMO_TABLE_ROWS = [
    [Line.plain("Cell"), Line.plain("Primitive"), Line.plain("tiny")],
    [Line.plain("Span"), Line.plain("Text"), Line.plain("varies")],
    [Line.plain("Block"), Line.plain("Layout"), Line.plain("varies")],
    [Line.plain("Buffer"), Line.plain("Canvas"), Line.plain("WxH")],
]


def render_demo(section: Demo, width: int, state: BenchState) -> Block:
    """Render an interactive demo widget."""
    demo_id = section.demo_id
    focused = state.focus.captured

    # Border style changes based on focus
    def demo_border_style(base_color: str) -> Style:
        if focused:
            return Style(fg=base_color, bold=True)
        return Style(fg=base_color, dim=True)

    if demo_id == "spinner":
        # Show all three spinner types side by side
        spin1 = spinner(state.spinner_state, style=Style(fg="cyan"))
        spin2 = spinner(state.spinner_braille, style=Style(fg="magenta"))
        spin3 = spinner(state.spinner_line, style=Style(fg="yellow"))

        label1 = Block.text("dots ", Style(dim=True))
        label2 = Block.text("braille ", Style(dim=True))
        label3 = Block.text("line ", Style(dim=True))

        row = join_horizontal(
            label1, spin1,
            Block.text("   ", Style()),
            label2, spin2,
            Block.text("   ", Style()),
            label3, spin3,
        )
        content = border(pad(row, left=1, right=1), ROUNDED, demo_border_style("cyan"))

    elif demo_id == "progress":
        bar = progress_bar(
            state.progress_state,
            width=30,
            filled_style=Style(fg="green"),
            empty_style=Style(dim=True),
        )
        pct = int(state.progress_state.value * 100)
        pct_label = Block.text(f" {pct}%", Style(fg="green" if pct > 50 else "yellow"))
        row = join_horizontal(bar, pct_label)
        if focused:
            hint = Block.text("  ←/→ adjust  esc: done", Style(fg="green"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)
        content = join_vertical(row, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("green"))

    elif demo_id == "list":
        lst = list_view(
            state.list_state,
            items=DEMO_LIST_ITEMS,
            visible_height=5,
            selected_style=Style(fg="black", bg="cyan", bold=True),
            cursor_char="▸",
        )
        if focused:
            hint = Block.text("  ↑/↓ navigate  esc: done", Style(fg="magenta"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)
        content = join_vertical(lst, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("magenta"))

    elif demo_id == "text_input":
        inp = text_input(
            state.text_state,
            width=20,
            focused=focused,  # cursor only shows when focused
            style=Style(fg="white"),
            cursor_style=Style(reverse=True),
            placeholder="type here...",
        )
        if focused:
            hint = Block.text("  type to edit  esc: done", Style(fg="yellow"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)
        content = join_vertical(inp, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("yellow"))

    elif demo_id == "table":
        # Scroll into view before rendering
        table_state = state.table_state.scroll_into_view(visible_height=3)
        tbl = table(
            table_state,
            columns=DEMO_TABLE_COLUMNS,
            rows=DEMO_TABLE_ROWS,
            visible_height=3,
            header_style=Style(fg="cyan", bold=True),
            selected_style=Style(fg="black", bg="cyan", bold=True),
        )
        if focused:
            hint = Block.text("  ↑/↓ navigate  esc: done", Style(fg="cyan"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)
        content = join_vertical(tbl, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("cyan"))

    elif demo_id == "focus_nav":
        # Demo showing navigation patterns
        items = ("a", "b", "c")
        current = state.focus_demo_item
        mode = state.focus_demo_mode

        # Render items with highlight on current
        item_blocks = []
        for item in items:
            if item == current:
                item_blocks.append(Block.text(f" {item} ", Style(fg="black", bg="green", bold=True)))
            else:
                item_blocks.append(Block.text(f" {item} ", Style(dim=True)))
        items_row = join_horizontal(*item_blocks, gap=1)

        # Mode indicator
        mode_text = f"mode: {mode}"
        mode_block = Block.text(mode_text, Style(fg="cyan"))

        if focused:
            hint = Block.text("  ←/→ nav  m: mode  esc: done", Style(fg="green"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)

        content = join_vertical(items_row, mode_block, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("green"))

    elif demo_id == "search":
        # Demo showing search/filter patterns
        all_items = ("Cell", "Style", "Span", "Line", "Block", "Buffer", "Focus", "Search")
        search = state.search_state
        mode = state.search_mode

        # Filter based on mode
        if mode == "contains":
            matches = filter_contains(all_items, search.query)
        elif mode == "prefix":
            matches = filter_prefix(all_items, search.query)
        else:
            matches = filter_fuzzy(all_items, search.query)

        # Query display
        query_display = search.query if search.query else "(type to filter)"
        query_style = Style(fg="cyan") if search.query else Style(dim=True)
        query_block = Block.text(f"query: {query_display}", query_style)

        # Render matches with selection highlight
        match_blocks = []
        for i, item in enumerate(matches[:5]):  # Show max 5
            if i == search.selected:
                match_blocks.append(Block.text(f" {item} ", Style(fg="black", bg="magenta", bold=True)))
            else:
                match_blocks.append(Block.text(f" {item} ", Style(dim=True)))

        if match_blocks:
            matches_row = join_horizontal(*match_blocks, gap=0)
        else:
            matches_row = Block.text("  (no matches)", Style(dim=True))

        # Mode indicator
        mode_block = Block.text(f"mode: {mode}", Style(fg="cyan"))

        if focused:
            hint = Block.text("  type/bksp  ↑/↓ select  m: mode  esc: done", Style(fg="magenta"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)

        content = join_vertical(query_block, matches_row, mode_block, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("magenta"))

    else:
        content = Block.text(f"[unknown demo: {demo_id}]", Style(fg="red"))

    # Add label if provided
    if section.label:
        label_block = Block.text(f" {section.label} ", Style(fg="white", bold=True))
        content = join_vertical(label_block, Spacer(1), content)

    if section.center:
        padding = max(0, (width - content.width) // 2)
        return pad(content, left=padding)
    return content


def render_section(section: Section, width: int, state: BenchState | None = None) -> Block:
    """Dispatch to appropriate section renderer."""
    if isinstance(section, Text):
        return render_text(section, width)
    elif isinstance(section, Code):
        return render_code(section, width)
    elif isinstance(section, Spacer):
        return render_spacer(section, width)
    elif isinstance(section, Demo):
        if state is None:
            return Block.text("[demo requires state]", Style(fg="red"))
        return render_demo(section, width, state)
    return Block.empty(width, 1)


# -- Slide Registry --

def build_slides() -> dict[str, Slide]:
    """Build the slide graph. Placeholder content for Phase 1."""
    return {
        # Entry point
        "intro": Slide(
            id="intro",
            title="cells",
            sections=(
                Spacer(2),
                Text("a cell-buffer terminal UI framework", SUBTITLE_STYLE, center=True),
                Spacer(2),
                Text(
                    styled(
                        "use ", ("arrow keys", KEYWORD), " to navigate"
                    ),
                    center=True,
                ),
                Text(
                    styled(
                        ("←", KEYWORD), " ", ("→", KEYWORD), " for topics, ",
                        ("↑", KEYWORD), " ", ("↓", KEYWORD), " for depth"
                    ),
                    center=True,
                ),
                Spacer(2),
                Text(
                    styled("press ", ("→", KEYWORD), " to begin"),
                    center=True,
                ),
            ),
            nav=Navigation(right="cell"),
        ),

        # Cell - the atom
        "cell": Slide(
            id="cell",
            title="Cell",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        "the atomic unit: one ", ("character", KEYWORD),
                        " + one ", ("style", KEYWORD),
                    ),
                    center=True,
                ),
                Spacer(2),
                Code(
                    source='cell = Cell("A", Style(fg="red", bold=True))',
                    title="cell.py",
                ),
                Spacer(1),
                Text("↓ for more detail", HINT_STYLE, center=True),
            ),
            nav=Navigation(left="intro", right="style", down="cell/detail"),
        ),

        "cell/detail": Slide(
            id="cell/detail",
            title="Cell (detail)",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        ("Cell", KEYWORD), " is a frozen dataclass — ",
                        ("immutable", EMPH), " by design"
                    ),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''@dataclass(frozen=True)
class Cell:
    char: str
    style: Style

EMPTY_CELL = Cell(" ", Style())''',
                    title="definition",
                ),
                Spacer(1),
                Text(
                    styled(
                        ("EMPTY_CELL", KEYWORD), " is the default for unfilled buffer positions"
                    ),
                    center=True,
                ),
            ),
            nav=Navigation(up="cell"),
        ),

        # Style
        "style": Slide(
            id="style",
            title="Style",
            sections=(
                Spacer(1),
                Text(
                    styled("colors and attributes for rendering"),
                    center=True,
                ),
                Spacer(2),
                Code(
                    source='''Style(fg="red")           # foreground color
Style(bg="blue")          # background color
Style(bold=True)          # bold text
Style(fg="#ff6b35")       # hex colors
Style(fg=196)             # 256-palette''',
                    title="style.py",
                ),
            ),
            nav=Navigation(left="cell", right="span", down="style/detail"),
        ),

        "style/detail": Slide(
            id="style/detail",
            title="Style (detail)",
            sections=(
                Spacer(1),
                Text(
                    styled(("Style", KEYWORD), " attributes"),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''@dataclass(frozen=True)
class Style:
    fg: str | int | None = None   # foreground
    bg: str | int | None = None   # background
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False''',
                    title="full signature",
                ),
                Spacer(1),
                Text(
                    styled(
                        ("Style.merge(other)", KEYWORD),
                        " combines styles — other wins on conflict"
                    ),
                    center=True,
                ),
            ),
            nav=Navigation(up="style"),
        ),

        # Span
        "span": Slide(
            id="span",
            title="Span",
            sections=(
                Spacer(1),
                Text("a run of text with one style", SUBTITLE_STYLE, center=True),
                Spacer(2),
                Code(
                    source='''span = Span("hello", Style(fg="green", bold=True))
# span.text = "hello"
# span.width = 5''',
                    title="span.py",
                ),
                Spacer(1),
                Text("↓ for more detail", HINT_STYLE, center=True),
            ),
            nav=Navigation(left="style", right="line", down="span/detail"),
        ),

        "span/detail": Slide(
            id="span/detail",
            title="Span (detail)",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        ("Span", KEYWORD), " handles wide characters via ",
                        ("wcwidth", EMPH),
                    ),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''@dataclass(frozen=True)
class Span:
    text: str
    style: Style = Style()

    @property
    def width(self) -> int:
        # accounts for CJK double-width chars
        return span_width(self.text)''',
                    title="definition",
                ),
                Spacer(1),
                Text(
                    styled(
                        ("span.width", KEYWORD), " is display width, not ",
                        ("len(text)", KEYWORD),
                    ),
                    center=True,
                ),
            ),
            nav=Navigation(up="span"),
        ),

        # Line
        "line": Slide(
            id="line",
            title="Line",
            sections=(
                Spacer(1),
                Text("a sequence of Spans — styled inline text", SUBTITLE_STYLE, center=True),
                Spacer(2),
                Code(
                    source='''line = Line(spans=(
    Span("error: ", Style(fg="red", bold=True)),
    Span("file not found", Style(fg="white")),
))
# line.width = 21''',
                    title="line.py",
                ),
                Spacer(1),
                Text("↓ for more detail", HINT_STYLE, center=True),
            ),
            nav=Navigation(left="span", right="buffer", down="line/detail"),
        ),

        "line/detail": Slide(
            id="line/detail",
            title="Line (detail)",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        ("Line", KEYWORD), " is a sequence of ", ("Spans", KEYWORD),
                    ),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''@dataclass(frozen=True)
class Line:
    spans: tuple[Span, ...] = ()
    style: Style | None = None  # fallback style

    @property
    def width(self) -> int:
        return sum(s.width for s in self.spans)

    def paint(self, view: BufferView, x: int, y: int):
        for span in self.spans:
            # paint each span, advancing x''',
                    title="definition",
                ),
                Spacer(1),
                Text(
                    styled(
                        ("Line.plain(text, style)", KEYWORD),
                        " — convenience constructor"
                    ),
                    center=True,
                ),
            ),
            nav=Navigation(up="line"),
        ),

        # Buffer
        "buffer": Slide(
            id="buffer",
            title="Buffer",
            sections=(
                Spacer(1),
                Text("the 2D canvas — a grid of Cells", SUBTITLE_STYLE, center=True),
                Spacer(2),
                Code(
                    source='''buf = Buffer(80, 24)
buf.put(0, 0, "A", Style(fg="red"))
buf.put_text(0, 1, "hello", Style())
buf.fill(10, 10, 5, 3, "█", Style(fg="blue"))''',
                    title="buffer.py",
                ),
            ),
            nav=Navigation(left="line", right="block", down="buffer/view"),
        ),

        "buffer/view": Slide(
            id="buffer/view",
            title="BufferView",
            sections=(
                Spacer(1),
                Text("a clipped, translated region of a Buffer", SUBTITLE_STYLE, center=True),
                Spacer(1),
                Code(
                    source='''view = buf.region(10, 5, 20, 10)
# view.width = 20, view.height = 10
# writes at (0,0) in view → (10,5) in buffer
# writes outside view bounds are clipped''',
                    title="bufferview",
                ),
                Spacer(1),
                Text("paint into views without bounds checking", HINT_STYLE, center=True),
            ),
            nav=Navigation(up="buffer"),
        ),

        # Block
        "block": Slide(
            id="block",
            title="Block",
            sections=(
                Spacer(1),
                Text("immutable rectangle of Cells — the composition unit", SUBTITLE_STYLE, center=True),
                Spacer(2),
                Code(
                    source='''block = Block.text("hello", Style(fg="cyan"))
# block.width = 5, block.height = 1

block.paint(buf, x=10, y=5)  # copy into buffer''',
                    title="block.py",
                ),
                Spacer(1),
                Text("↓ for more detail", HINT_STYLE, center=True),
            ),
            nav=Navigation(left="buffer", right="compose", down="block/detail"),
        ),

        "block/detail": Slide(
            id="block/detail",
            title="Block (detail)",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        ("Block", KEYWORD), " stores rows of ", ("Cells", KEYWORD),
                        " — ", ("immutable", EMPH),
                    ),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''@dataclass(frozen=True)
class Block:
    rows: list[list[Cell]]
    width: int

    @classmethod
    def text(cls, text: str, style: Style) -> Block:
        # create block from string

    @classmethod
    def empty(cls, width: int, height: int) -> Block:
        # create blank block''',
                    title="definition",
                ),
                Spacer(1),
                Text(
                    styled(
                        "compose via ", ("join", KEYWORD), ", ",
                        ("pad", KEYWORD), ", ", ("border", KEYWORD),
                    ),
                    center=True,
                ),
            ),
            nav=Navigation(up="block"),
        ),

        # Compose
        "compose": Slide(
            id="compose",
            title="Compose",
            sections=(
                Spacer(1),
                Text("combine blocks spatially", SUBTITLE_STYLE, center=True),
                Spacer(1),
                Code(
                    source='''join_horizontal(a, b, gap=1)  # side by side
join_vertical(a, b)           # stacked
pad(block, left=2, top=1)     # margins
border(block, ROUNDED)        # box drawing
truncate(block, width=20)     # cut to size''',
                    title="compose.py",
                ),
            ),
            nav=Navigation(left="block", right="app"),
        ),

        # App
        "app": Slide(
            id="app",
            title="RenderApp",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        "the application loop — ",
                        ("keyboard", KEYWORD), ", ",
                        ("resize", KEYWORD), ", ",
                        ("diff rendering", KEYWORD),
                    ),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''class MyApp(RenderApp):
    def render(self):
        # paint into self._buf

    def on_key(self, key: str):
        if key == "q":
            self.quit()''',
                    title="app.py",
                ),
                Spacer(1),
                Text(
                    styled("→ for ", ("components", KEYWORD), " (interactive widgets)"),
                    center=True,
                ),
            ),
            nav=Navigation(left="compose", right="focus"),
        ),

        # Focus - two-tier keyboard handling
        "focus": Slide(
            id="focus",
            title="Focus",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        "immutable state: ", ("id", KEYWORD), " + ",
                        ("captured", KEYWORD), " flag",
                    ),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''focus = Focus(id="sidebar")
focus = focus.capture()   # widget handles keys
focus = focus.release()   # nav handles keys''',
                    title="focus.py",
                ),
                Spacer(1),
                Text(
                    styled(
                        "navigation patterns: ",
                        ("ring_next", KEYWORD), ", ",
                        ("linear_prev", KEYWORD), ", ..."
                    ),
                    center=True,
                ),
                Spacer(1),
                Text("↓ for navigation demo", HINT_STYLE, center=True),
            ),
            nav=Navigation(left="app", right="search", down="focus/nav"),
        ),

        "focus/nav": Slide(
            id="focus/nav",
            title="Navigation Patterns",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        "pure functions: ", ("items", KEYWORD), " + ",
                        ("current", KEYWORD), " → ", ("next", KEYWORD),
                    ),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''items = ("a", "b", "c")
current = "b"

ring_next(items, current)    # "c"
ring_next(items, "c")        # "a" (wraps)

linear_next(items, current)  # "c"
linear_next(items, "c")      # "c" (stops)''',
                    title="focus.py",
                ),
                Spacer(1),
                Demo(demo_id="focus_nav"),
            ),
            nav=Navigation(up="focus"),
        ),

        # Search - filtered selection primitive
        "search": Slide(
            id="search",
            title="Search",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        "filtered selection: ", ("query", KEYWORD), " + ",
                        ("selected", KEYWORD), " index",
                    ),
                    center=True,
                ),
                Spacer(1),
                Code(
                    source='''search = Search()
search = search.type("f")     # query="f"
search = search.type("o")     # query="fo"
search = search.backspace()   # query="f"''',
                    title="search.py",
                ),
                Spacer(1),
                Text(
                    styled(
                        "filter patterns: ",
                        ("contains", KEYWORD), ", ",
                        ("prefix", KEYWORD), ", ",
                        ("fuzzy", KEYWORD),
                    ),
                    center=True,
                ),
                Spacer(1),
                Text("↓ for interactive demo", HINT_STYLE, center=True),
            ),
            nav=Navigation(left="focus", right="components", down="search/demo"),
        ),

        "search/demo": Slide(
            id="search/demo",
            title="Search Demo",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        "type to filter, ", ("↑/↓", KEYWORD), " to select, ",
                        ("m", KEYWORD), " to change mode",
                    ),
                    center=True,
                ),
                Spacer(1),
                Demo(demo_id="search"),
            ),
            nav=Navigation(up="search"),
        ),

        # Components - interactive demos
        "components": Slide(
            id="components",
            title="Components",
            sections=(
                Spacer(1),
                Text(
                    styled(
                        "stateful widgets: ",
                        ("spinner", KEYWORD), ", ",
                        ("progress", KEYWORD), ", ",
                        ("list", KEYWORD), ", ",
                        ("text input", KEYWORD),
                    ),
                    center=True,
                ),
                Spacer(1),
                Demo(demo_id="spinner"),
                Spacer(1),
                Text(
                    styled(
                        "state is ", ("immutable", EMPH), " — methods return new instances"
                    ),
                    center=True,
                ),
                Spacer(1),
                Text("↓ for interactive examples", HINT_STYLE, center=True),
            ),
            nav=Navigation(left="search", down="components/progress"),
        ),

        "components/progress": Slide(
            id="components/progress",
            title="Progress Bar",
            sections=(
                Spacer(1),
                Text(
                    styled(("ProgressState", KEYWORD), " + ", ("progress_bar()", KEYWORD)),
                    center=True,
                ),
                Spacer(1),
                Demo(demo_id="progress"),
                Spacer(1),
                Code(
                    source='''state = ProgressState(value=0.5)
state = state.set(0.75)  # returns new state

bar = progress_bar(state, width=30)''',
                    title="usage",
                ),
            ),
            nav=Navigation(up="components", down="components/list"),
        ),

        "components/list": Slide(
            id="components/list",
            title="List View",
            sections=(
                Spacer(1),
                Text(
                    styled(("ListState", KEYWORD), " + ", ("list_view()", KEYWORD)),
                    center=True,
                ),
                Spacer(1),
                Demo(demo_id="list"),
                Spacer(1),
                Code(
                    source='''state = ListState(item_count=5)
state = state.move_down()  # returns new state

items = [Line.plain("Apple"), ...]
lst = list_view(state, items, visible_height=5)''',
                    title="usage",
                ),
            ),
            nav=Navigation(up="components/progress", down="components/text"),
        ),

        "components/text": Slide(
            id="components/text",
            title="Text Input",
            sections=(
                Spacer(1),
                Text(
                    styled(("TextInputState", KEYWORD), " + ", ("text_input()", KEYWORD)),
                    center=True,
                ),
                Spacer(1),
                Demo(demo_id="text_input"),
                Spacer(1),
                Code(
                    source='''state = TextInputState(text="hello")
state = state.insert("!")  # returns new state

inp = text_input(state, width=20, focused=True)''',
                    title="usage",
                ),
            ),
            nav=Navigation(up="components/list", down="components/table"),
        ),

        "components/table": Slide(
            id="components/table",
            title="Table",
            sections=(
                Spacer(1),
                Text(
                    styled(("TableState", KEYWORD), " + ", ("table()", KEYWORD)),
                    center=True,
                ),
                Spacer(1),
                Demo(demo_id="table"),
                Spacer(1),
                Code(
                    source='''columns = [Column(header=Line.plain("Name"), width=12)]
rows = [[Line.plain("Cell")], [Line.plain("Block")]]
state = TableState(row_count=len(rows))

tbl = table(state, columns, rows, visible_height=3)''',
                    title="usage",
                ),
            ),
            nav=Navigation(up="components/text", down="fin"),
        ),

        # Finale
        "fin": Slide(
            id="fin",
            title="fin",
            sections=(
                Spacer(2),
                Text(
                    Line(spans=(
                        Span("that's ", Style(fg="white", dim=True)),
                        Span("cells", Style(fg="cyan", bold=True)),
                        Span(".", Style(fg="white", dim=True)),
                    )),
                    center=True,
                ),
                Spacer(2),
                Text(
                    styled(
                        ("Cell", KEYWORD), " → ",
                        ("Style", KEYWORD), " → ",
                        ("Span", KEYWORD), " → ",
                        ("Line", KEYWORD), " → ",
                        ("Block", KEYWORD), " → ",
                        ("Buffer", KEYWORD),
                    ),
                    center=True,
                ),
                Spacer(1),
                Text(
                    styled("compose with ", ("join", KEYWORD), ", ", ("pad", KEYWORD), ", ", ("border", KEYWORD)),
                    center=True,
                ),
                Spacer(1),
                Text(
                    styled("run with ", ("RenderApp", KEYWORD)),
                    center=True,
                ),
                Spacer(2),
                Text(
                    Line(spans=(
                        Span("go build something.", Style(fg="cyan", bold=True)),
                    )),
                    center=True,
                ),
            ),
            nav=Navigation(up="components/table"),
        ),
    }


# -- Help Overlay --

HELP_CONTENT = [
    ("Navigation", [
        ("← → ↑ ↓", "move between slides"),
        ("q / esc", "quit"),
        ("?", "toggle this help"),
    ]),
    ("Demo Widgets", [
        ("tab", "focus/unfocus demo"),
        ("← →", "adjust progress (when focused)"),
        ("↑ ↓", "navigate list (when focused)"),
        ("type", "edit text input (when focused)"),
        ("esc", "unfocus demo"),
    ]),
]


def render_help(width: int, height: int) -> Block:
    """Render the help overlay."""
    rows: list[Block] = []

    # Title
    title = Block.text(" Keyboard Shortcuts ", Style(fg="cyan", bold=True))
    rows.append(title)
    rows.append(Block.empty(1, 1))

    for section_name, bindings in HELP_CONTENT:
        # Section header
        rows.append(Block.text(f" {section_name}", Style(fg="white", bold=True)))
        rows.append(Block.empty(1, 1))

        for key, desc in bindings:
            key_block = Block.text(f"  {key:12}", Style(fg="yellow"))
            desc_block = Block.text(desc, Style(dim=True))
            rows.append(join_horizontal(key_block, desc_block))

        rows.append(Block.empty(1, 1))

    # Footer
    rows.append(Block.text(" press ? or esc to close ", HINT_STYLE))

    content = join_vertical(*rows)
    content = pad(content, left=2, right=2, top=1, bottom=1)
    boxed = border(content, ROUNDED, Style(fg="cyan"))

    # Center in the available space
    pad_left = max(0, (width - boxed.width) // 2)
    pad_top = max(0, (height - boxed.height) // 2)

    return pad(boxed, left=pad_left, top=pad_top)


# -- Header & Footer --

def render_header(slide: Slide, width: int) -> Block:
    """Render the slide title header."""
    title_block = Block.text(f" {slide.title} ", TITLE_STYLE)
    # Center the title
    padding = max(0, (width - title_block.width) // 2)
    return pad(title_block, left=padding, top=1, bottom=1)


def render_footer(slide: Slide, nav: Navigation, width: int, slides: dict[str, Slide], state: BenchState) -> Block:
    """Render the navigation footer."""
    parts: list[Block] = []

    # Focus indicator
    if state.focus.captured:
        parts.append(Block.text(" FOCUS ", Style(fg="black", bg="cyan", bold=True)))
        parts.append(Block.text(" ", Style()))

    # Navigation hints (dimmed when focused)
    nav_style = Style(dim=True) if state.focus.captured else NAV_DIM_STYLE
    key_style = Style(fg="cyan", dim=True) if state.focus.captured else NAV_KEY_STYLE

    nav_hints = []
    if nav.left:
        nav_hints.append(("←", slides[nav.left].title if nav.left in slides else nav.left))
    if nav.right:
        nav_hints.append(("→", slides[nav.right].title if nav.right in slides else nav.right))
    if nav.up:
        nav_hints.append(("↑", "less"))
    if nav.down:
        nav_hints.append(("↓", "more"))

    for key, label in nav_hints:
        parts.append(Block.text(key, key_style))
        parts.append(Block.text(f" {label}  ", nav_style))

    if not nav_hints and not state.focus.captured:
        parts.append(Block.text("q to quit", NAV_DIM_STYLE))

    nav_row = join_horizontal(*parts) if parts else Block.empty(1, 1)

    # Right side: help hint + position
    help_hint = Block.text(" ?:help ", Style(dim=True))
    position = Block.text(f" {slide.id} ", POSITION_STYLE)
    right_side = join_horizontal(help_hint, position)

    # Build footer: nav on left, position on right
    spacer_width = max(1, width - nav_row.width - right_side.width - 2)
    spacer = Block.empty(spacer_width, 1)

    footer_content = join_horizontal(
        Block.text(" ", Style()),
        nav_row,
        spacer,
        right_side,
        Block.text(" ", Style()),
    )

    return footer_content


# -- Main App --

class BenchApp(RenderApp):
    """Interactive teaching bench application."""

    def __init__(self, slides: dict[str, Slide] | None = None):
        super().__init__(fps_cap=30)
        self._slides = slides or build_slides()
        self._state = BenchState()
        self._width = 80
        self._height = 24
        self._last_tick = time.monotonic()

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def update(self) -> None:
        """Advance animations (spinners)."""
        now = time.monotonic()
        # Tick spinners every 100ms
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

        # Clear
        self._buf.fill(0, 0, self._width, self._height, " ", Style())

        # Get current slide
        slide = self._slides.get(self._state.current_slide)
        if not slide:
            self._buf.put_text(0, 0, f"Unknown slide: {self._state.current_slide}", Style(fg="red"))
            return

        # Header
        header = render_header(slide, self._width)
        header.paint(self._buf, 0, 0)

        # Content area
        content_y = header.height
        content_height = self._height - header.height - 2  # leave room for footer

        content_blocks = []
        for section in slide.sections:
            block = render_section(section, self._width - 4, self._state)  # pass state for demos
            content_blocks.append(block)

        if content_blocks:
            content = join_vertical(*content_blocks)
            content = pad(content, left=2)
            content.paint(self._buf, 0, content_y)

        # Footer
        footer = render_footer(slide, slide.nav, self._width, self._slides, self._state)
        footer.paint(self._buf, 0, self._height - 1)

        # Help overlay (on top of everything)
        if self._state.show_help:
            help_overlay = render_help(self._width, self._height)
            help_overlay.paint(self._buf, 0, 0)

    def _has_demo(self, slide: Slide, demo_id: str | None = None) -> bool:
        """Check if a slide contains a demo (optionally of a specific type)."""
        for section in slide.sections:
            if isinstance(section, Demo):
                if demo_id is None or section.demo_id == demo_id:
                    return True
        return False

    def _get_demo_id(self, slide: Slide) -> str | None:
        """Get the first interactive demo ID on a slide (not spinner)."""
        for section in slide.sections:
            if isinstance(section, Demo) and section.demo_id != "spinner":
                return section.demo_id
        return None

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return

        # Help toggle
        if key == "?":
            self._state = replace(self._state, show_help=not self._state.show_help)
            return

        # When help is showing, any key closes it
        if self._state.show_help:
            self._state = replace(self._state, show_help=False)
            return

        slide = self._slides.get(self._state.current_slide)
        if not slide:
            return

        demo_id = self._get_demo_id(slide)
        focused = self._state.focus.captured

        # Escape: release focus or quit
        if key == "escape":
            if focused:
                self._state = replace(self._state, focus=self._state.focus.release())
            else:
                self.quit()
            return

        # Tab: toggle focus capture (only if slide has interactive demo)
        if key == "tab" and demo_id:
            self._state = replace(self._state, focus=self._state.focus.toggle_capture())
            return

        # When focused, keys go to demo widget
        if focused and demo_id:
            handled = False

            if demo_id == "progress":
                if key == "left":
                    self._state = replace(
                        self._state,
                        progress_state=self._state.progress_state.set(
                            max(0.0, self._state.progress_state.value - 0.05)
                        )
                    )
                    handled = True
                elif key == "right":
                    self._state = replace(
                        self._state,
                        progress_state=self._state.progress_state.set(
                            min(1.0, self._state.progress_state.value + 0.05)
                        )
                    )
                    handled = True

            elif demo_id == "list":
                if key == "up":
                    self._state = replace(
                        self._state,
                        list_state=self._state.list_state.move_up()
                    )
                    handled = True
                elif key == "down":
                    self._state = replace(
                        self._state,
                        list_state=self._state.list_state.move_down()
                    )
                    handled = True

            elif demo_id == "text_input":
                if key == "backspace":
                    self._state = replace(
                        self._state,
                        text_state=self._state.text_state.delete_back()
                    )
                    handled = True
                elif key == "delete":
                    self._state = replace(
                        self._state,
                        text_state=self._state.text_state.delete_forward()
                    )
                    handled = True
                elif len(key) == 1 and key.isprintable():
                    self._state = replace(
                        self._state,
                        text_state=self._state.text_state.insert(key)
                    )
                    handled = True

            elif demo_id == "table":
                if key == "up":
                    self._state = replace(
                        self._state,
                        table_state=self._state.table_state.move_up()
                    )
                    handled = True
                elif key == "down":
                    self._state = replace(
                        self._state,
                        table_state=self._state.table_state.move_down()
                    )
                    handled = True

            elif demo_id == "focus_nav":
                items = ("a", "b", "c")
                current = self._state.focus_demo_item
                mode = self._state.focus_demo_mode

                if key == "right":
                    if mode == "ring":
                        new_item = ring_next(items, current)
                    else:
                        new_item = linear_next(items, current)
                    self._state = replace(self._state, focus_demo_item=new_item)
                    handled = True
                elif key == "left":
                    if mode == "ring":
                        new_item = ring_prev(items, current)
                    else:
                        new_item = linear_prev(items, current)
                    self._state = replace(self._state, focus_demo_item=new_item)
                    handled = True
                elif key == "m":
                    new_mode = "linear" if mode == "ring" else "ring"
                    self._state = replace(self._state, focus_demo_mode=new_mode)
                    handled = True

            elif demo_id == "search":
                all_items = ("Cell", "Style", "Span", "Line", "Block", "Buffer", "Focus", "Search")
                search = self._state.search_state
                mode = self._state.search_mode

                # Get current matches for navigation
                if mode == "contains":
                    matches = filter_contains(all_items, search.query)
                elif mode == "prefix":
                    matches = filter_prefix(all_items, search.query)
                else:
                    matches = filter_fuzzy(all_items, search.query)

                if key == "backspace":
                    self._state = replace(self._state, search_state=search.backspace())
                    handled = True
                elif key == "up":
                    self._state = replace(self._state, search_state=search.select_prev(len(matches)))
                    handled = True
                elif key == "down":
                    self._state = replace(self._state, search_state=search.select_next(len(matches)))
                    handled = True
                elif key == "m":
                    modes = ["contains", "prefix", "fuzzy"]
                    idx = modes.index(mode)
                    new_mode = modes[(idx + 1) % len(modes)]
                    self._state = replace(self._state, search_mode=new_mode)
                    handled = True
                elif len(key) == 1 and key.isprintable():
                    self._state = replace(self._state, search_state=search.type(key))
                    handled = True

            if handled:
                return

        # Navigation (only when not focused on demo)
        if not focused:
            nav = slide.nav
            new_slide = None

            if key == "left" and nav.left:
                new_slide = nav.left
            elif key == "right" and nav.right:
                new_slide = nav.right
            elif key == "up" and nav.up:
                new_slide = nav.up
            elif key == "down" and nav.down:
                new_slide = nav.down

            if new_slide and new_slide in self._slides:
                # Reset focus when changing slides
                self._state = replace(self._state, current_slide=new_slide, focus=self._state.focus.release())
                return

        # Delegate to slide-specific handler
        if slide.on_key:
            self._state = slide.on_key(key, self._state)


async def main():
    app = BenchApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
