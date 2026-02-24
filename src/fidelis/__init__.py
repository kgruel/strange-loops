"""Cell-buffer rendering system.

CLI core: styled output primitives for dressing up scripts.

For interactive TUI apps, import from submodules:
    from fidelis.tui import Surface, Layer
    from fidelis.views import shape_lens
    from fidelis.views import spinner, list_view
    from fidelis.mouse import MouseEvent
    from fidelis.views import render_big

For aesthetic customization:
    from fidelis import current_palette, use_palette, MONO_PALETTE
    from fidelis import current_icons, use_icons, ASCII_ICONS

For CLI harness and in-place rendering:
    from fidelis.inplace import InPlaceRenderer
"""

# Primitives
from .cell import Style, Cell, EMPTY_CELL
from .span import Span, Line
from .block import Block, Wrap

# Composition
from .compose import Align, join_horizontal, join_vertical, join_responsive, pad, border, truncate, vslice
from .cursor import Cursor, CursorMode
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
from .inplace import InPlaceRenderer

# Aesthetic
from .palette import (
    Palette,
    DEFAULT_PALETTE,
    NORD_PALETTE,
    MONO_PALETTE,
    current_palette,
    use_palette,
    reset_palette,
)
from .icon_set import (
    IconSet,
    ASCII_ICONS,
    current_icons,
    use_icons,
    reset_icons,
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
    "Cursor",
    "CursorMode",
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
    # Aesthetic
    "Palette",
    "DEFAULT_PALETTE",
    "NORD_PALETTE",
    "MONO_PALETTE",
    "current_palette",
    "use_palette",
    "reset_palette",
    "IconSet",
    "ASCII_ICONS",
    "current_icons",
    "use_icons",
    "reset_icons",
]
