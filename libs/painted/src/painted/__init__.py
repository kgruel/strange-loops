"""Cell-buffer rendering system.

CLI core: styled output primitives for dressing up scripts.

For interactive TUI apps, import from submodules:
    from painted.tui import Surface, Layer
    from painted.views import shape_lens
    from painted.views import spinner, list_view
    from painted.mouse import MouseEvent
    from painted.views import render_big

For aesthetic customization:
    from painted import current_palette, use_palette, MONO_PALETTE
    from painted import current_icons, use_icons, ASCII_ICONS

For CLI harness and in-place rendering:
    from painted.inplace import InPlaceRenderer
"""

# Primitives
# Display
import json as _json
import sys as _sys
from collections.abc import Callable as _Callable
from typing import Any as _Any
from typing import TextIO as _TextIO

from .block import Block, Wrap
from .borders import ASCII, DOUBLE, HEAVY, LIGHT, ROUNDED, BorderChars
from .cell import EMPTY_CELL, Cell, Style

# Composition
from .compose import (
    Align,
    border,
    join_horizontal,
    join_responsive,
    join_vertical,
    pad,
    truncate,
    vslice,
)
from .cursor import Cursor, CursorMode

# Fidelity (CLI harness)
from .fidelity import (
    CliContext,
    CliRunner,
    Format,
    HelpArg,
    HelpData,
    HelpFlag,
    HelpGroup,
    OutputMode,
    Zoom,
    add_cli_args,
    detect_context,
    parse_format,
    parse_mode,
    parse_zoom,
    resolve_mode,
    run_cli,
)

# App runner (multi-command routing)
from .app_runner import AppCommand, AppRunner, run_app
from .icon_set import (
    ASCII_ICONS,
    IconSet,
    current_icons,
    reset_icons,
    use_icons,
)

# In-place rendering
from .inplace import InPlaceRenderer

# Aesthetic
from .palette import (
    DEFAULT_PALETTE,
    MONO_PALETTE,
    NORD_PALETTE,
    Palette,
    current_palette,
    reset_palette,
    use_palette,
)
from .span import Line, Span
from .viewport import Viewport

# Output
from .writer import ColorDepth, Writer, print_block
from .html import render_html

_MISSING = object()


def show(
    data: _Any = _MISSING,
    *,
    zoom: Zoom = Zoom.DETAILED,
    lens: _Callable[[_Any, int, int], "Block"] | None = None,
    format: Format = Format.AUTO,
    file: _TextIO = _sys.stdout,
) -> None:
    """Display data with auto-detected formatting.

    Four paths:
    - No args: blank line (like print())
    - Block: print directly via print_block
    - JSON format (piped or explicit): json.dumps with default=str
    - Otherwise: render through lens (default shape_lens) then print_block

    Args:
        data: Any Python value, or a pre-built Block. Omit for blank line.
        zoom: Detail level (default SUMMARY).
        lens: Render function override (default: shape_lens).
        format: Force output format (default: auto-detect from TTY).
        file: Output stream (default: sys.stdout).
    """
    # No args — blank line
    if data is _MISSING:
        file.write("\n")
        file.flush()
        return

    from ._lens import shape_lens
    from .fidelity import setup_defaults

    # Resolve format to bools — JSON short-circuits, plain suppresses ANSI
    is_json = format == Format.JSON
    force_plain = format == Format.PLAIN

    # Block passthrough — already rendered
    if isinstance(data, Block):
        if is_json:
            # Can't JSON-serialize a Block, fall through to ANSI/plain
            pass
        ctx = detect_context(zoom, OutputMode.AUTO, force_plain=force_plain)
        setup_defaults(ctx)
        print_block(data, file, use_ansi=ctx.use_ansi)
        return

    # JSON path — serialize directly, bypasses render pipeline
    if is_json:
        file.write(_json.dumps(data, default=str))
        file.write("\n")
        file.flush()
        return

    # Detect output context
    ctx = detect_context(zoom, OutputMode.AUTO, force_plain=force_plain)
    setup_defaults(ctx)

    # Scalars — no structure to inspect, just print
    if lens is None and (data is None or isinstance(data, (str, int, float, bool))):
        file.write(str(data))
        file.write("\n")
        file.flush()
        return

    # Rendered path — lens to Block, then print
    render_fn = lens or shape_lens
    block = render_fn(data, ctx.zoom, ctx.width)
    print_block(block, file, use_ansi=ctx.use_ansi)


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
    "render_html",
    # Display
    "show",
    # Fidelity (new API)
    "Zoom",
    "OutputMode",
    "Format",
    "CliContext",
    "CliRunner",
    "HelpArg",
    "run_cli",
    "AppCommand",
    "AppRunner",
    "run_app",
    "add_cli_args",
    "parse_zoom",
    "parse_mode",
    "parse_format",
    "resolve_mode",
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
