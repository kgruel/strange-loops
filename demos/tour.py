#!/usr/bin/env python3
"""Tour: Interactive educational platform for fidelis.

A 2D navigable space where:
- left/right moves between topics (sibling concepts)
- up/down moves between zoom levels (same concept, more/less detail)

Run: uv run python demos/tour.py

Zoom levels (per slide via max_zoom):
- Zoom 0: summary (intro text + minimal code)
- Zoom 1: detail (full definition)
- Zoom 2: source (from actual file)

Slides with max_zoom > 0 support in-slide zooming via up/down keys.
Some topics are still separate slides (style/detail, etc.) during migration.

Fidelity = starting zoom level:
- -q, --quiet: Print slides inline with rendered demos, then exit
- default:     Start at intro, zoom 0
- -v:          Start at cell, zoom 1 (detail level)
- -vv:         Start at cell, zoom 2 (source level)

User can always navigate up/down between zoom levels with arrow keys.
"""

from __future__ import annotations

import argparse
import asyncio
import textwrap
from dataclasses import dataclass, field, replace
from pathlib import Path

import time

from fidelis import (
    Block, Style, Span, Line,
    Cursor,
    join_horizontal, join_vertical, pad, border,
    ROUNDED,
    print_block,
)
from fidelis.tui import (
    Surface, BufferView,
    # Focus management
    Focus, ring_next, ring_prev, linear_next, linear_prev,
    # Search
    Search, filter_contains, filter_prefix, filter_fuzzy,
    # Layer
    Layer, Stay, Pop, Push, Quit, process_key, render_layers,
)
from fidelis.views import (
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
    """A single slide in the teaching bench.

    common: sections shown at all zoom levels.
    zooms: dict mapping zoom level -> sections shown only at that level.
    max_zoom: highest zoom level (0 = no zoom support).
    """
    id: str
    title: str
    group: str = ""
    common: tuple[Section, ...] = ()
    zooms: dict[int, tuple[Section, ...]] = field(default_factory=dict)
    max_zoom: int = 0
    nav: Navigation = field(default_factory=Navigation)


@dataclass(frozen=True)
class BenchState:
    """Application state for the teaching bench."""
    current_slide: str = "intro"
    zoom: int = 0  # current zoom level (0=summary, 1=detail, 2=source)
    show_minimap: bool = False  # whether to show minimap sidebar
    focus: Focus = field(default_factory=lambda: Focus(id="demo"))  # .captured = keys go to widget

    # Layer stack (base layer + modal overlays)
    layers: tuple[Layer, ...] = ()  # Initialized in BenchApp.__init__

    # Component states for interactive demos
    spinner_state: SpinnerState = field(default_factory=SpinnerState)
    spinner_braille: SpinnerState = field(default_factory=lambda: SpinnerState(frames=BRAILLE))
    spinner_line: SpinnerState = field(default_factory=lambda: SpinnerState(frames=LINE))
    progress_state: ProgressState = field(default_factory=lambda: ProgressState(value=0.35))
    list_state: ListState = field(default_factory=lambda: ListState(cursor=Cursor(count=5)))
    text_state: TextInputState = field(default_factory=lambda: TextInputState(text="hello", cursor=5))
    table_state: TableState = field(default_factory=lambda: TableState(cursor=Cursor(count=4)))

    # Focus demo state
    focus_demo_item: str = "a"
    focus_demo_mode: str = "ring"  # "ring" or "linear"

    # Search demo state
    search_state: Search = field(default_factory=Search)
    search_mode: str = "contains"  # "contains", "prefix", "fuzzy"

    # Terminal dimensions (for layers to access)
    width: int = 80
    height: int = 24


@dataclass(frozen=True)
class LensContext:
    """Rendering context for all section lenses.

    Provides uniform context to all section renderers:
    - width: available rendering width
    - zoom: detail level (0=summary, 1=detail, 2=source)
    - focus: current focus state
    - perspective: rendering mode ("content", "minimap")

    Component states are passed through for Demo sections.
    """
    width: int
    zoom: int = 0
    focus: Focus = field(default_factory=lambda: Focus(id="demo"))
    perspective: str = "content"  # "content", "minimap"

    # Component states for Demo sections
    spinner_state: SpinnerState = field(default_factory=SpinnerState)
    spinner_braille: SpinnerState = field(default_factory=lambda: SpinnerState(frames=BRAILLE))
    spinner_line: SpinnerState = field(default_factory=lambda: SpinnerState(frames=LINE))
    progress_state: ProgressState = field(default_factory=lambda: ProgressState(value=0.35))
    list_state: ListState = field(default_factory=lambda: ListState(cursor=Cursor(count=5)))
    text_state: TextInputState = field(default_factory=lambda: TextInputState(text="hello", cursor=5))
    table_state: TableState = field(default_factory=lambda: TableState(cursor=Cursor(count=4)))

    # Focus demo state
    focus_demo_item: str = "a"
    focus_demo_mode: str = "ring"

    # Search demo state
    search_state: Search = field(default_factory=Search)
    search_mode: str = "contains"

    @classmethod
    def from_state(cls, state: BenchState, width: int, zoom: int | None = None) -> "LensContext":
        """Create LensContext from BenchState.

        This factory extracts all relevant state from BenchState and packages it
        for rendering. The width parameter is the available content width.
        If zoom is None, uses state.zoom.
        """
        return cls(
            width=width,
            zoom=zoom if zoom is not None else state.zoom,
            focus=state.focus,
            perspective="content",
            spinner_state=state.spinner_state,
            spinner_braille=state.spinner_braille,
            spinner_line=state.spinner_line,
            progress_state=state.progress_state,
            list_state=state.list_state,
            text_state=state.text_state,
            table_state=state.table_state,
            focus_demo_item=state.focus_demo_item,
            focus_demo_mode=state.focus_demo_mode,
            search_state=state.search_state,
            search_mode=state.search_mode,
        )


# -- Styles --

TITLE_STYLE = Style(fg="cyan", bold=True)
SUBTITLE_STYLE = Style(fg="white", dim=True)
CODE_BORDER_STYLE = Style(fg="yellow", dim=True)
CODE_TITLE_STYLE = Style(fg="yellow", bold=True)
NAV_KEY_STYLE = Style(fg="cyan", bold=True)
NAV_DIM_STYLE = Style(dim=True)
POSITION_STYLE = Style(fg="magenta", dim=True)
HINT_STYLE = Style(fg="white", dim=True, italic=True)

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


# -- Layer Accessors --

def get_layers(state: BenchState) -> tuple[Layer, ...]:
    """Extract layers from state."""
    return state.layers


def set_layers(state: BenchState, layers: tuple[Layer, ...]) -> BenchState:
    """Return state with new layers."""
    return replace(state, layers=layers)


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
            hint = Block.text("  left/right adjust  esc: done", Style(fg="green"))
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
            cursor_char="*",
        )
        if focused:
            hint = Block.text("  up/down navigate  esc: done", Style(fg="magenta"))
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
            hint = Block.text("  up/down navigate  esc: done", Style(fg="cyan"))
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
            hint = Block.text("  left/right nav  m: mode  esc: done", Style(fg="green"))
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
            hint = Block.text("  type/bksp  up/down select  m: mode  esc: done", Style(fg="magenta"))
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


# -- Section Lenses (context-first API) --


def text_lens(section: Text, ctx: LensContext) -> Block:
    """Render a text section via LensContext.

    Currently a passthrough to render_text; future: zoom-aware rendering.
    """
    return render_text(section, ctx.width)


def code_lens(section: Code, ctx: LensContext) -> Block:
    """Render a code section via LensContext.

    Currently a passthrough to render_code; future: zoom-aware rendering.
    """
    return render_code(section, ctx.width)


def spacer_lens(section: Spacer, ctx: LensContext) -> Block:
    """Render vertical spacing via LensContext."""
    return render_spacer(section, ctx.width)


def demo_lens(section: Demo, ctx: LensContext) -> Block:
    """Render an interactive demo widget via LensContext.

    Extracts all needed state from the context.
    """
    demo_id = section.demo_id
    focused = ctx.focus.captured

    # Border style changes based on focus
    def demo_border_style(base_color: str) -> Style:
        if focused:
            return Style(fg=base_color, bold=True)
        return Style(fg=base_color, dim=True)

    if demo_id == "spinner":
        # Show all three spinner types side by side
        spin1 = spinner(ctx.spinner_state, style=Style(fg="cyan"))
        spin2 = spinner(ctx.spinner_braille, style=Style(fg="magenta"))
        spin3 = spinner(ctx.spinner_line, style=Style(fg="yellow"))

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
            ctx.progress_state,
            width=30,
            filled_style=Style(fg="green"),
            empty_style=Style(dim=True),
        )
        pct = int(ctx.progress_state.value * 100)
        pct_label = Block.text(f" {pct}%", Style(fg="green" if pct > 50 else "yellow"))
        row = join_horizontal(bar, pct_label)
        if focused:
            hint = Block.text("  left/right adjust  esc: done", Style(fg="green"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)
        content = join_vertical(row, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("green"))

    elif demo_id == "list":
        lst = list_view(
            ctx.list_state,
            items=DEMO_LIST_ITEMS,
            visible_height=5,
            selected_style=Style(fg="black", bg="cyan", bold=True),
            cursor_char="*",
        )
        if focused:
            hint = Block.text("  up/down navigate  esc: done", Style(fg="magenta"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)
        content = join_vertical(lst, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("magenta"))

    elif demo_id == "text_input":
        inp = text_input(
            ctx.text_state,
            width=20,
            focused=focused,
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
        table_state = ctx.table_state.scroll_into_view(visible_height=3)
        tbl = table(
            table_state,
            columns=DEMO_TABLE_COLUMNS,
            rows=DEMO_TABLE_ROWS,
            visible_height=3,
            header_style=Style(fg="cyan", bold=True),
            selected_style=Style(fg="black", bg="cyan", bold=True),
        )
        if focused:
            hint = Block.text("  up/down navigate  esc: done", Style(fg="cyan"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)
        content = join_vertical(tbl, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("cyan"))

    elif demo_id == "focus_nav":
        # Demo showing navigation patterns
        items = ("a", "b", "c")
        current = ctx.focus_demo_item
        mode = ctx.focus_demo_mode

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
            hint = Block.text("  left/right nav  m: mode  esc: done", Style(fg="green"))
        else:
            hint = Block.text("  tab: focus", HINT_STYLE)

        content = join_vertical(items_row, mode_block, hint)
        content = border(pad(content, left=1, right=1), ROUNDED, demo_border_style("green"))

    elif demo_id == "search":
        # Demo showing search/filter patterns
        all_items = ("Cell", "Style", "Span", "Line", "Block", "Buffer", "Focus", "Search")
        search = ctx.search_state
        mode = ctx.search_mode

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
            hint = Block.text("  type/bksp  up/down select  m: mode  esc: done", Style(fg="magenta"))
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
        padding = max(0, (ctx.width - content.width) // 2)
        return pad(content, left=padding)
    return content



def section_lens(section: Section, ctx: LensContext) -> Block:
    """Dispatch to appropriate section lens.

    This is the primary entry point for rendering sections with LensContext.
    """
    match section:
        case Text():
            return text_lens(section, ctx)
        case Code():
            return code_lens(section, ctx)
        case Spacer():
            return spacer_lens(section, ctx)
        case Demo():
            return demo_lens(section, ctx)
        case _:
            return Block.empty(ctx.width, 1)


# -- Minimap Lens --


def minimap_lens(slides: dict[str, Slide], current: str, current_zoom: int, height: int, nav_sequence: list[str] | None = None) -> Block:
    """Render slide graph as a minimap sidebar.

    Shows all slide titles with the current slide highlighted.
    Includes zoom indicator for slides with zoom support.
    Uses group headers as visual separators.
    """
    sequence = nav_sequence or list(slides.keys())

    nodes: list[Block] = []

    # Title
    title_block = Block.text(" Minimap ", Style(fg="cyan", bold=True))
    nodes.append(title_block)
    nodes.append(Block.empty(1, 1))

    last_group = None
    for slide_id in sequence:
        if slide_id not in slides:
            continue
        slide = slides[slide_id]

        # Group header when group changes
        if slide.group and slide.group != last_group:
            if last_group is not None:
                nodes.append(Block.empty(1, 1))
            nodes.append(Block.text(f" {slide.group}", Style(fg="yellow", dim=True)))
            last_group = slide.group

        is_current = slide_id == current

        if is_current:
            # Current slide: highlighted with zoom indicator
            style = Style(fg="black", bg="cyan", bold=True)
            zoom_str = f"+{current_zoom}" if current_zoom > 0 else ""
            text = f" > {slide.title}{zoom_str} "
        else:
            # Other slides: dimmed
            style = Style(dim=True)
            text = f"   {slide.title} "

        # Truncate if too wide
        max_width = 20
        if len(text) > max_width:
            text = text[:max_width-1] + "\u2026"

        nodes.append(Block.text(text, style))

    # Limit to available height (minus title and spacing)
    available = height - 3
    if len(nodes) > available:
        nodes = nodes[:available]
        nodes.append(Block.text("   ...", Style(dim=True)))

    # Add footer hint
    nodes.append(Block.empty(1, 1))
    nodes.append(Block.text(" m: close ", Style(dim=True)))

    result = join_vertical(*nodes)

    # Add right border
    bordered = border(result, ROUNDED, Style(fg="cyan", dim=True))

    return bordered


# -- Slide Loading --

def _build_slides_dir() -> Path:
    """Return path to the slides directory."""
    return Path(__file__).parent / "slides"


def _convert_sections(section_dicts: list[dict]) -> tuple[Section, ...]:
    """Convert parsed section dicts to tour Section types."""
    from slide_loader import parse_styled_text

    sections: list[Section] = []
    for sec in section_dicts:
        if sec['type'] == 'spacer':
            sections.append(Spacer(sec.get('lines', 1)))
        elif sec['type'] == 'text':
            line = parse_styled_text(sec['content'])
            content = sec['content']
            # Hint text (↓/→ prefixed) gets italic dim style
            is_hint = content.startswith('↓') or content.startswith('→')
            style = HINT_STYLE if is_hint else SUBTITLE_STYLE
            sections.append(Text(line, style, center=sec.get('center', False)))
        elif sec['type'] == 'code':
            sections.append(Code(source=sec['source'], title=sec.get('lang', '')))
        elif sec['type'] == 'demo':
            sections.append(Demo(demo_id=sec['demo_id']))
    return tuple(sections)


def _to_tour_slide(parsed, nav_data: dict[str, str | None] | None = None) -> Slide:
    """Convert a ParsedSlide to a tour Slide."""
    common = _convert_sections(parsed.common_sections)
    zooms = {}
    for level, section_dicts in parsed.zoom_sections.items():
        zooms[level] = _convert_sections(section_dicts)

    n = nav_data or {}
    return Slide(
        id=parsed.id,
        title=parsed.title,
        group=parsed.group,
        common=common,
        zooms=zooms,
        max_zoom=parsed.max_zoom,
        nav=Navigation(
            left=n.get('left'),
            right=n.get('right'),
            up=n.get('up'),
            down=n.get('down'),
        ),
    )


def build_slides() -> tuple[dict[str, Slide], list[str]]:
    """Load slides from markdown files.

    Returns (slides_dict, navigation_sequence).
    """
    import sys
    demos_dir = str(Path(__file__).parent)
    if demos_dir not in sys.path:
        sys.path.insert(0, demos_dir)
    from slide_loader import load_slides_dir, validate_slides, build_navigation, get_navigation_sequence

    slides_dir = _build_slides_dir()
    parsed = load_slides_dir(slides_dir)
    validate_slides(parsed)
    nav = build_navigation(parsed)
    nav_sequence = get_navigation_sequence(parsed)

    slides = {}
    for sid, p in parsed.items():
        slides[sid] = _to_tour_slide(p, nav.get(sid))

    return slides, nav_sequence


# -- Help Overlay --

HELP_CONTENT = [
    ("Navigation", [
        ("left right", "move between topics"),
        ("up down", "zoom in/out (detail levels)"),
        ("/", "search/jump to slide"),
        ("m", "toggle minimap sidebar"),
        ("q / esc", "quit"),
        ("?", "toggle this help"),
    ]),
    ("Demo Widgets", [
        ("tab", "focus/unfocus demo"),
        ("left right", "adjust progress (when focused)"),
        ("up down", "navigate list (when focused)"),
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
            key_block = Block.text(f"  {key:20}", Style(fg="yellow"))
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


def render_search_overlay(
    width: int,
    height: int,
    search: Search,
    slide_titles: list[tuple[str, str]],
) -> Block:
    """Render the slide search overlay.

    Args:
        width: Terminal width
        height: Terminal height
        search: Current search state
        slide_titles: List of (slide_id, title) tuples
    """
    rows: list[Block] = []

    # Title
    title = Block.text(" Jump to Slide ", Style(fg="magenta", bold=True))
    rows.append(title)
    rows.append(Block.empty(1, 1))

    # Query input
    query_display = search.query if search.query else ""
    query_block = Block.text(f" > {query_display}_", Style(fg="cyan"))
    rows.append(query_block)
    rows.append(Block.empty(1, 1))

    # Filter slide titles
    titles_only = [title for _, title in slide_titles]
    matches = filter_fuzzy(titles_only, search.query)

    # Build a mapping from title back to slide_id
    title_to_id = {title: sid for sid, title in slide_titles}

    # Show matches (max 10)
    visible_matches = matches[:10]
    if visible_matches:
        for i, match_title in enumerate(visible_matches):
            if i == search.selected:
                # Selected item
                row = Block.text(f" > {match_title}", Style(fg="black", bg="magenta", bold=True))
            else:
                row = Block.text(f"   {match_title}", Style(dim=True))
            rows.append(row)
    else:
        rows.append(Block.text("   (no matches)", Style(dim=True)))

    rows.append(Block.empty(1, 1))

    # Footer hints
    rows.append(Block.text(" enter: jump  esc: cancel  up/down: select ", HINT_STYLE))

    content = join_vertical(*rows)
    content = pad(content, left=2, right=2, top=1, bottom=1)
    boxed = border(content, ROUNDED, Style(fg="magenta"))

    # Center in the available space
    pad_left = max(0, (width - boxed.width) // 2)
    pad_top = max(0, (height - boxed.height) // 2)

    return pad(boxed, left=pad_left, top=pad_top)


# -- Layer Handlers --

# Help Layer - no state needed
def _handle_help(key: str, layer_state: None, app_state: BenchState) -> tuple[None, BenchState, Stay | Pop | Push | Quit]:
    """Help layer: any key dismisses."""
    return None, app_state, Pop()


def _render_help(layer_state: None, app_state: BenchState, view: BufferView) -> None:
    """Render help overlay."""
    block = render_help(app_state.width, app_state.height)
    block.paint(view, 0, 0)


def make_help_layer() -> Layer[None]:
    """Create the help overlay layer."""
    return Layer(name="help", state=None, handle=_handle_help, render=_render_help)


# Search Layer - state is the Search primitive
@dataclass(frozen=True)
class SearchLayerState:
    """State for the search layer."""
    search: Search = field(default_factory=Search)
    slides: dict[str, Slide] = field(default_factory=dict)


def _handle_search(key: str, layer_state: SearchLayerState, app_state: BenchState) -> tuple[SearchLayerState, BenchState, Stay | Pop | Push | Quit]:
    """Search layer: handles query input and selection."""
    search = layer_state.search
    slides = layer_state.slides

    if key == "escape":
        # Close search without jumping
        return layer_state, app_state, Pop()

    if key == "enter":
        # Jump to selected slide and close search
        slide_titles = [(sid, s.title) for sid, s in slides.items()]
        titles_only = [title for _, title in slide_titles]
        matches = filter_fuzzy(titles_only, search.query)
        title_to_id = {title: sid for sid, title in slide_titles}

        if matches and search.selected < len(matches):
            selected_title = matches[search.selected]
            target_slide = title_to_id.get(selected_title)
            if target_slide:
                new_app_state = replace(
                    app_state,
                    current_slide=target_slide,
                    focus=app_state.focus.release(),
                )
                return layer_state, new_app_state, Pop(result=target_slide)
        # No matches, just close
        return layer_state, app_state, Pop()

    if key == "up":
        slide_titles = [(sid, s.title) for sid, s in slides.items()]
        titles_only = [title for _, title in slide_titles]
        matches = filter_fuzzy(titles_only, search.query)
        new_layer_state = replace(layer_state, search=search.select_prev(len(matches)))
        return new_layer_state, app_state, Stay()

    if key == "down":
        slide_titles = [(sid, s.title) for sid, s in slides.items()]
        titles_only = [title for _, title in slide_titles]
        matches = filter_fuzzy(titles_only, search.query)
        new_layer_state = replace(layer_state, search=search.select_next(len(matches)))
        return new_layer_state, app_state, Stay()

    if key == "backspace":
        new_layer_state = replace(layer_state, search=search.backspace())
        return new_layer_state, app_state, Stay()

    if len(key) == 1 and key.isprintable():
        new_layer_state = replace(layer_state, search=search.type(key))
        return new_layer_state, app_state, Stay()

    # Ignore other keys
    return layer_state, app_state, Stay()


def _render_search(layer_state: SearchLayerState, app_state: BenchState, view: BufferView) -> None:
    """Render search overlay."""
    slide_titles = [(sid, s.title) for sid, s in layer_state.slides.items()]
    block = render_search_overlay(app_state.width, app_state.height, layer_state.search, slide_titles)
    block.paint(view, 0, 0)


def make_search_layer(slides: dict[str, Slide]) -> Layer[SearchLayerState]:
    """Create the search overlay layer."""
    return Layer(
        name="search",
        state=SearchLayerState(search=Search(), slides=slides),
        handle=_handle_search,
        render=_render_search,
    )


# Demo Layer - state tracks which demo is focused
@dataclass(frozen=True)
class DemoLayerState:
    """State for the demo focus layer."""
    slides: dict[str, Slide] = field(default_factory=dict)


def _get_demo_id(slide: Slide, zoom: int = 0) -> str | None:
    """Get the first interactive demo ID on a slide (not spinner).

    Searches both common sections and the current zoom level's sections.
    """
    zoom_sections = slide.zooms.get(zoom, slide.zooms.get(0, ()))
    for section in slide.common + zoom_sections:
        if isinstance(section, Demo) and section.demo_id != "spinner":
            return section.demo_id
    return None


def _handle_demo_input(key: str, state: BenchState, demo_id: str) -> tuple[BenchState, bool]:
    """Handle key for demo widget. Returns (new_state, handled)."""
    handled = False

    if demo_id == "progress":
        if key == "left":
            state = replace(
                state,
                progress_state=state.progress_state.set(
                    max(0.0, state.progress_state.value - 0.05)
                )
            )
            handled = True
        elif key == "right":
            state = replace(
                state,
                progress_state=state.progress_state.set(
                    min(1.0, state.progress_state.value + 0.05)
                )
            )
            handled = True

    elif demo_id == "list":
        if key == "up":
            state = replace(state, list_state=state.list_state.move_up())
            handled = True
        elif key == "down":
            state = replace(state, list_state=state.list_state.move_down())
            handled = True

    elif demo_id == "text_input":
        if key == "backspace":
            state = replace(state, text_state=state.text_state.delete_back())
            handled = True
        elif key == "delete":
            state = replace(state, text_state=state.text_state.delete_forward())
            handled = True
        elif len(key) == 1 and key.isprintable():
            state = replace(state, text_state=state.text_state.insert(key))
            handled = True

    elif demo_id == "table":
        if key == "up":
            state = replace(state, table_state=state.table_state.move_up())
            handled = True
        elif key == "down":
            state = replace(state, table_state=state.table_state.move_down())
            handled = True

    elif demo_id == "focus_nav":
        items = ("a", "b", "c")
        current = state.focus_demo_item
        mode = state.focus_demo_mode

        if key == "right":
            if mode == "ring":
                new_item = ring_next(items, current)
            else:
                new_item = linear_next(items, current)
            state = replace(state, focus_demo_item=new_item)
            handled = True
        elif key == "left":
            if mode == "ring":
                new_item = ring_prev(items, current)
            else:
                new_item = linear_prev(items, current)
            state = replace(state, focus_demo_item=new_item)
            handled = True
        elif key == "m":
            new_mode = "linear" if mode == "ring" else "ring"
            state = replace(state, focus_demo_mode=new_mode)
            handled = True

    elif demo_id == "search":
        all_items = ("Cell", "Style", "Span", "Line", "Block", "Buffer", "Focus", "Search")
        search = state.search_state
        mode = state.search_mode

        # Get current matches for navigation
        if mode == "contains":
            matches = filter_contains(all_items, search.query)
        elif mode == "prefix":
            matches = filter_prefix(all_items, search.query)
        else:
            matches = filter_fuzzy(all_items, search.query)

        if key == "backspace":
            state = replace(state, search_state=search.backspace())
            handled = True
        elif key == "up":
            state = replace(state, search_state=search.select_prev(len(matches)))
            handled = True
        elif key == "down":
            state = replace(state, search_state=search.select_next(len(matches)))
            handled = True
        elif key == "m":
            modes = ["contains", "prefix", "fuzzy"]
            idx = modes.index(mode)
            new_mode = modes[(idx + 1) % len(modes)]
            state = replace(state, search_mode=new_mode)
            handled = True
        elif len(key) == 1 and key.isprintable():
            state = replace(state, search_state=search.type(key))
            handled = True

    return state, handled


def _handle_demo(key: str, layer_state: DemoLayerState, app_state: BenchState) -> tuple[DemoLayerState, BenchState, Stay | Pop | Push | Quit]:
    """Demo focus layer: captures input for widget interaction."""
    if key == "escape":
        # Release focus and pop demo layer
        return layer_state, replace(app_state, focus=app_state.focus.release()), Pop()

    slide = layer_state.slides.get(app_state.current_slide)
    if not slide:
        return layer_state, app_state, Stay()

    demo_id = _get_demo_id(slide, app_state.zoom)
    if demo_id:
        new_app_state, handled = _handle_demo_input(key, app_state, demo_id)
        if handled:
            return layer_state, new_app_state, Stay()

    return layer_state, app_state, Stay()


def _render_demo(layer_state: DemoLayerState, app_state: BenchState, view: BufferView) -> None:
    """Demo layer has no extra rendering - slide content shows focus state."""
    pass


def make_demo_layer(slides: dict[str, Slide]) -> Layer[DemoLayerState]:
    """Create the demo focus layer."""
    return Layer(
        name="demo",
        state=DemoLayerState(slides=slides),
        handle=_handle_demo,
        render=_render_demo,
    )


# Nav Layer - state holds slides reference
@dataclass(frozen=True)
class NavLayerState:
    """State for the navigation layer."""
    slides: dict[str, Slide] = field(default_factory=dict)
    nav_sequence: list[str] = field(default_factory=list)


def _handle_nav(key: str, layer_state: NavLayerState, app_state: BenchState) -> tuple[NavLayerState, BenchState, Stay | Pop | Push | Quit]:
    """Base navigation layer: handles slide navigation and pushes overlays."""
    slides = layer_state.slides

    if key == "q":
        return layer_state, app_state, Quit()

    if key == "?":
        return layer_state, app_state, Push(make_help_layer())

    if key == "/" and not app_state.focus.captured:
        return layer_state, app_state, Push(make_search_layer(slides))

    # Minimap toggle
    if key == "m" and not app_state.focus.captured:
        return layer_state, replace(app_state, show_minimap=not app_state.show_minimap), Stay()

    slide = slides.get(app_state.current_slide)
    if not slide:
        return layer_state, app_state, Stay()

    demo_id = _get_demo_id(slide, app_state.zoom)

    # Escape: go back (reduce zoom, or go to parent slide)
    if key == "escape":
        if app_state.zoom > 0:
            return layer_state, replace(app_state, zoom=app_state.zoom - 1), Stay()
        elif slide.nav.up:
            target = slides.get(slide.nav.up)
            new_zoom = target.max_zoom if target else 0
            return layer_state, replace(app_state, current_slide=slide.nav.up, zoom=new_zoom), Stay()
        return layer_state, app_state, Stay()

    # Tab: toggle focus capture (only if slide has interactive demo)
    if key == "tab" and demo_id:
        new_focus = app_state.focus.toggle_capture()
        if new_focus.captured:
            # Push demo layer when capturing focus
            return layer_state, replace(app_state, focus=new_focus), Push(make_demo_layer(slides))
        return layer_state, replace(app_state, focus=new_focus), Stay()

    # Navigation (only when not focused on demo)
    nav = slide.nav
    new_slide = None
    new_zoom = app_state.zoom

    if key == "left" and nav.left:
        new_slide = nav.left
        new_zoom = 0  # Reset zoom when changing slides
    elif key == "right" and nav.right:
        new_slide = nav.right
        new_zoom = 0  # Reset zoom when changing slides
    elif key == "up":
        # First try decreasing zoom, then navigate to nav.up
        if app_state.zoom > 0:
            new_zoom = app_state.zoom - 1
        elif nav.up:
            new_slide = nav.up
            # When navigating up, start at max zoom of target slide
            target_slide = slides.get(nav.up)
            new_zoom = target_slide.max_zoom if target_slide else 0
    elif key == "down":
        # First try increasing zoom, then navigate to nav.down
        if app_state.zoom < slide.max_zoom:
            new_zoom = app_state.zoom + 1
        elif nav.down:
            new_slide = nav.down
            new_zoom = 0  # Start at zoom 0 when going deeper

    if new_slide and new_slide in slides:
        # Reset focus when changing slides
        return layer_state, replace(app_state, current_slide=new_slide, zoom=new_zoom, focus=app_state.focus.release()), Stay()
    elif new_zoom != app_state.zoom:
        # Just change zoom level
        return layer_state, replace(app_state, zoom=new_zoom), Stay()

    return layer_state, app_state, Stay()


def _render_nav(layer_state: NavLayerState, app_state: BenchState, view: BufferView) -> None:
    """Render the main slide content, with optional minimap sidebar."""
    slides = layer_state.slides
    slide = slides.get(app_state.current_slide)
    if not slide:
        view.put_text(0, 0, f"Unknown slide: {app_state.current_slide}", Style(fg="red"))
        return

    width = app_state.width
    height = app_state.height

    # Calculate minimap width if shown
    minimap_width = 0
    if app_state.show_minimap:
        minimap_block = minimap_lens(slides, app_state.current_slide, app_state.zoom, height - 2, layer_state.nav_sequence)
        minimap_width = minimap_block.width + 1  # +1 for gap

        # Render minimap on the left
        minimap_block.paint(view, 0, 1)

    # Content area starts after minimap
    content_x = minimap_width
    content_width = width - minimap_width

    # Header (in content area)
    header = render_header(slide, content_width)
    header.paint(view, content_x, 0)

    # Content area
    content_y = header.height

    # Create LensContext for section rendering (narrower when minimap shown)
    ctx = LensContext.from_state(app_state, content_width - 4)

    # Gather sections: common + zoom-specific
    zoom_sections = slide.zooms.get(app_state.zoom, slide.zooms.get(0, ()))
    sections = slide.common + zoom_sections

    content_blocks = []
    for section in sections:
        block = section_lens(section, ctx)
        content_blocks.append(block)

    if content_blocks:
        content = join_vertical(*content_blocks)
        content = pad(content, left=2)
        content.paint(view, content_x, content_y)

    # Footer (full width, at bottom)
    footer = render_footer(slide, slide.nav, width, slides, app_state)
    footer.paint(view, 0, height - 1)


def make_nav_layer(slides: dict[str, Slide], nav_sequence: list[str] | None = None) -> Layer[NavLayerState]:
    """Create the base navigation layer."""
    return Layer(
        name="nav",
        state=NavLayerState(slides=slides, nav_sequence=nav_sequence or []),
        handle=_handle_nav,
        render=_render_nav,
    )


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
        nav_hints.append(("left", slides[nav.left].title if nav.left in slides else nav.left))
    if nav.right:
        nav_hints.append(("right", slides[nav.right].title if nav.right in slides else nav.right))

    # Up: show if zoom > 0 or nav.up exists
    can_zoom_up = state.zoom > 0
    can_nav_up = nav.up is not None
    if can_zoom_up:
        nav_hints.append(("up", "less"))
    elif can_nav_up:
        nav_hints.append(("up", "less"))

    # Down: show if zoom < max_zoom or nav.down exists
    can_zoom_down = state.zoom < slide.max_zoom
    can_nav_down = nav.down is not None
    if can_zoom_down:
        nav_hints.append(("down", "more"))
    elif can_nav_down:
        nav_hints.append(("down", "more"))

    for key, label in nav_hints:
        parts.append(Block.text(key, key_style))
        parts.append(Block.text(f" {label}  ", nav_style))

    if not nav_hints and not state.focus.captured:
        parts.append(Block.text("q to quit", NAV_DIM_STYLE))

    nav_row = join_horizontal(*parts) if parts else Block.empty(1, 1)

    # Right side: help hint + position (include zoom level if > 0)
    help_hint = Block.text(" ?:help ", Style(dim=True))
    zoom_indicator = f"+{state.zoom}" if state.zoom > 0 else ""
    position = Block.text(f" {slide.id}{zoom_indicator} ", POSITION_STYLE)
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

class BenchApp(Surface):
    """Interactive teaching bench application."""

    def __init__(self, slides: dict[str, Slide] | None = None, nav_sequence: list[str] | None = None, start_slide: str = "intro", start_zoom: int = 0):
        super().__init__(fps_cap=30)
        if slides is None:
            slides, nav_sequence = build_slides()
        self._slides = slides
        self._nav_sequence = nav_sequence or []
        # Initialize state with base navigation layer (slides passed via layer state)
        self._state = BenchState(
            current_slide=start_slide,
            zoom=start_zoom,
            layers=(make_nav_layer(self._slides, self._nav_sequence),),
        )
        self._width = 80
        self._height = 24
        self._last_tick = time.monotonic()

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        # Update state dimensions for layers to access
        self._state = replace(self._state, width=width, height=height)

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

        # Render all layers bottom-to-top
        render_layers(self._state, self._buf, get_layers)

    def on_key(self, key: str) -> None:
        # Process key through layer stack
        self._state, should_quit, _result = process_key(key, self._state, get_layers, set_layers)

        # Check for quit signal
        if should_quit:
            self.quit()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Tour: Interactive educational platform for fidelis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Fidelity = starting zoom level:
              default   : Start at intro, zoom 0
              -q        : Quiet - print all slides (with zoom levels) and exit
              -v        : Start at cell, zoom 1 (detail level)
              -vv       : Start at cell, zoom 2 (source level)

            User can navigate up/down between zoom levels with arrow keys.
            Slides with max_zoom > 0 support in-slide zooming.
        """),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Print slides inline and exit (no TUI)",
    )
    group.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Start deeper (-v: detail level, -vv: source level)",
    )
    return parser.parse_args()


def get_navigation_order(slides: dict[str, Slide]) -> list[str]:
    """Return slide IDs in navigation order.

    Walks left/right links starting from the slide with no left neighbor.
    """
    # Find starting slide (no left)
    start = None
    for sid, slide in slides.items():
        if slide.nav.left is None:
            start = sid
            break
    if start is None:
        return list(slides.keys())

    order = []
    current = start
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        order.append(current)
        slide = slides.get(current)
        current = slide.nav.right if slide else None

    # Add any unreachable slides
    for sid in slides:
        if sid not in visited:
            order.append(sid)

    return order


def run_quiet_mode(slides: dict[str, Slide], nav_sequence: list[str] | None = None) -> None:
    """Print all slides inline and exit (quiet mode).

    For slides with max_zoom > 0, prints each zoom level.
    Demos are rendered in their default/initial state (not interactive).
    """
    import sys

    order = nav_sequence or get_navigation_order(slides)
    state = BenchState()  # Demo components rendered in default state

    for slide_id in order:
        slide = slides[slide_id]

        # For slides with zoom support, render each zoom level
        zoom_levels = range(slide.max_zoom + 1) if slide.max_zoom > 0 else [0]

        for zoom in zoom_levels:
            ctx = LensContext.from_state(state, 78, zoom=zoom)

            # Build slide content as a Block
            content_blocks: list[Block] = []

            # Title (include zoom indicator for slides with zoom support)
            if slide.max_zoom > 0 and zoom > 0:
                zoom_suffix = " (detail)" if zoom == 1 else " (source)"
                title_block = Block.text(f"=== {slide.title}{zoom_suffix} ===", TITLE_STYLE)
            else:
                title_block = Block.text(f"=== {slide.title} ===", TITLE_STYLE)
            content_blocks.append(title_block)
            content_blocks.append(Block.empty(1, 1))

            # Gather sections: common + zoom-specific
            zoom_sections = slide.zooms.get(zoom, slide.zooms.get(0, ()))
            sections = slide.common + zoom_sections

            for section in sections:
                block = section_lens(section, ctx)
                content_blocks.append(block)

            content_blocks.append(Block.empty(1, 1))

            # Combine and print
            if content_blocks:
                content = join_vertical(*content_blocks)
                print_block(content, sys.stdout)


def get_start_slide(fidelity: int) -> tuple[str, int]:
    """Get the starting slide and zoom based on fidelity level.

    Returns (slide_id, zoom) tuple.

    - default (0): Start at intro, zoom 0
    - -v (1): Start at cell, zoom 1 (detail level)
    - -vv (2): Start at cell, zoom 2 (source level)
    """
    if fidelity >= 2:
        return ("cell", 2)
    elif fidelity >= 1:
        return ("cell", 1)
    else:
        return ("intro", 0)


async def main():
    args = parse_args()
    slides, nav_sequence = build_slides()

    if args.quiet:
        # Quiet mode: print slides inline and exit
        run_quiet_mode(slides, nav_sequence)
        return

    # Fidelity determines starting slide and zoom level
    start_slide, start_zoom = get_start_slide(args.verbose)
    app = BenchApp(slides=slides, nav_sequence=nav_sequence, start_slide=start_slide, start_zoom=start_zoom)

    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
