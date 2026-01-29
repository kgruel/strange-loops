"""Cell-buffer rendering system.

CLI core: styled output primitives for dressing up scripts.

For interactive TUI apps, import from submodules:
    from cells.tui import Surface, Layer
    from cells.lens import shape_lens
    from cells.widgets import spinner, list_view
    from cells.mouse import MouseEvent
    from cells.effects import render_big
"""

# Primitives
from .cell import Style, Cell, EMPTY_CELL
from .span import Span, Line
from .block import Block, Wrap

# Composition
from .compose import Align, join_horizontal, join_vertical, pad, border, truncate, vslice
from .viewport import Viewport
from .borders import BorderChars, ROUNDED, HEAVY, DOUBLE, LIGHT, ASCII

# Output
from .writer import Writer, ColorDepth, print_block

# Theme
from .theme import (
    HEADER_BG,
    SELECTION_BG,
    DEBUG_BG,
    HEADER_BASE,
    HEADER_BOLD,
    HEADER_DIM,
    HEADER_CONNECTED,
    HEADER_ERROR,
    HEADER_SPINNER,
    HEADER_LEVEL_FILTER,
    FOOTER_KEY,
    FOOTER_DIM,
    FOOTER_ACTIVE_FILTER,
    FILTER_PROMPT,
    FILTER_CURSOR,
    LEVEL_STYLES,
    SELECTION_CURSOR,
    SELECTION_HIGHLIGHT,
    SOURCE_DIM,
    DEBUG_OVERLAY,
)

__all__ = [
    # Primitives
    "Style",
    "Cell",
    "EMPTY_CELL",
    "Span",
    "Line",
    "Block",
    "Wrap",
    # Composition
    "Align",
    "join_horizontal",
    "join_vertical",
    "pad",
    "border",
    "truncate",
    "vslice",
    "Viewport",
    "BorderChars",
    "ROUNDED",
    "HEAVY",
    "DOUBLE",
    "LIGHT",
    "ASCII",
    # Output
    "Writer",
    "ColorDepth",
    "print_block",
    # Theme
    "HEADER_BG",
    "SELECTION_BG",
    "DEBUG_BG",
    "HEADER_BASE",
    "HEADER_BOLD",
    "HEADER_DIM",
    "HEADER_CONNECTED",
    "HEADER_ERROR",
    "HEADER_SPINNER",
    "HEADER_LEVEL_FILTER",
    "FOOTER_KEY",
    "FOOTER_DIM",
    "FOOTER_ACTIVE_FILTER",
    "FILTER_PROMPT",
    "FILTER_CURSOR",
    "LEVEL_STYLES",
    "SELECTION_CURSOR",
    "SELECTION_HIGHLIGHT",
    "SOURCE_DIM",
    "DEBUG_OVERLAY",
]
