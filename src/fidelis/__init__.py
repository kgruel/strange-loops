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

# Display
import json as _json
import sys as _sys
from typing import Any as _Any, Callable as _Callable, TextIO as _TextIO


def show(
    data: _Any,
    *,
    zoom: Zoom = Zoom.SUMMARY,
    lens: _Callable[[_Any, int, int], "Block"] | None = None,
    format: Format = Format.AUTO,
    file: _TextIO = _sys.stdout,
) -> None:
    """Display data with auto-detected formatting.

    Three paths:
    - Block: print directly via print_block
    - JSON format (piped or explicit): json.dumps with default=str
    - Otherwise: render through lens (default shape_lens) then print_block

    Args:
        data: Any Python value, or a pre-built Block.
        zoom: Detail level (default SUMMARY).
        lens: Render function override (default: shape_lens).
        format: Force output format (default: auto-detect from TTY).
        file: Output stream (default: sys.stdout).
    """
    from ._lens import shape_lens
    from .fidelity import _setup_defaults

    # Block passthrough — already rendered
    if isinstance(data, Block):
        ctx = detect_context(zoom, OutputMode.AUTO, format)
        _setup_defaults(ctx)
        print_block(data, file, use_ansi=(ctx.format == Format.ANSI))
        return

    # Detect output context
    ctx = detect_context(zoom, OutputMode.AUTO, format)
    _setup_defaults(ctx)

    # JSON path — serialize directly
    if ctx.format == Format.JSON:
        file.write(_json.dumps(data, default=str))
        file.write("\n")
        file.flush()
        return

    # Scalars — no structure to inspect, just print
    if lens is None and (data is None or isinstance(data, (str, int, float, bool))):
        file.write(str(data))
        file.write("\n")
        file.flush()
        return

    # Rendered path — lens to Block, then print
    render_fn = lens or shape_lens
    block = render_fn(data, ctx.zoom, ctx.width)
    print_block(block, file, use_ansi=(ctx.format == Format.ANSI))


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
    # Display
    "show",
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
