"""Cell-buffer rendering system.

CLI core: styled output primitives for dressing up scripts.

For interactive TUI apps, import from submodules:
    from fidelis.tui import Surface, Layer
    from fidelis.lens import shape_lens
    from fidelis.widgets import spinner, list_view
    from fidelis.mouse import MouseEvent
    from fidelis.effects import render_big

For runtime theming:
    from fidelis.themes import current_theme, use_theme, list_themes

For CLI harness and in-place rendering:
    from fidelis.inplace import InPlaceRenderer

For component theming:
    from fidelis.component_theme import Icons, ComponentTheme, component_theme
"""

# Primitives
from .cell import Style, Cell, EMPTY_CELL
from .span import Span, Line
from .block import Block, Wrap

# Composition
from .compose import Align, join_horizontal, join_vertical, join_responsive, pad, border, truncate, vslice
from .viewport import Viewport
from .borders import BorderChars, ROUNDED, HEAVY, DOUBLE, LIGHT, ASCII

# Output
from .writer import Writer, ColorDepth, print_block

# Fidelity (CLI harness)
from .fidelity import (
    # New API
    Zoom,
    OutputMode,
    Format,
    CliContext,
    CliRunner,
    run_cli,
    add_cli_args,
    parse_zoom,
    parse_mode,
    parse_format,
    resolve_mode,
    resolve_format,
    detect_context,
)

# In-place rendering
from .inplace import InPlaceRenderer, render_inplace

# Component theming
from .component_theme import (
    Icons,
    ASCII_ICONS,
    ComponentTheme,
    DEFAULT_COMPONENT_THEME,
    ASCII_COMPONENT_THEME,
    component_theme,
    use_component_theme,
    reset_component_theme,
)

# Theme (legacy style constants)
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
    "join_responsive",
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
    # Fidelity (new API)
    "Zoom",
    "OutputMode",
    "Format",
    "CliContext",
    "CliRunner",
    "run_cli",
    "add_cli_args",
    "parse_zoom",
    "parse_mode",
    "parse_format",
    "resolve_mode",
    "resolve_format",
    "detect_context",
    # In-place rendering
    "InPlaceRenderer",
    "render_inplace",
    # Component theming
    "Icons",
    "ASCII_ICONS",
    "ComponentTheme",
    "DEFAULT_COMPONENT_THEME",
    "ASCII_COMPONENT_THEME",
    "component_theme",
    "use_component_theme",
    "reset_component_theme",
    # Theme (legacy)
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
