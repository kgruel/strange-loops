"""Views: view-layer primitives (data/state -> Block).

This is the single public namespace for Painted view-layer APIs.
"""

# Aesthetic
from painted.icon_set import IconSet, ASCII_ICONS, current_icons, use_icons, reset_icons  # noqa: F401
from painted.palette import (  # noqa: F401
    Palette,
    DEFAULT_PALETTE,
    NORD_PALETTE,
    MONO_PALETTE,
    current_palette,
    use_palette,
    reset_palette,
)

# Stateless views
from painted._lens import (  # noqa: F401
    NodeRenderer,
    shape_lens,
    tree_lens,
    chart_lens,
)
from painted._components.sparkline import sparkline, sparkline_with_range  # noqa: F401
from painted._components.spinner import (  # noqa: F401
    SpinnerState,
    SpinnerFrames,
    spinner,
    DOTS,
    LINE,
    BRAILLE,
)
from painted._components.progress import ProgressState, progress_bar  # noqa: F401
from painted.big_text import render_big, BigTextFormat, BIG_GLYPHS  # noqa: F401

# Stateful views
from painted._components.list_view import ListState, list_view  # noqa: F401
from painted._components.table import TableState, Column, table  # noqa: F401
from painted._components.text_input import TextInputState, text_input  # noqa: F401
from painted._components.data_explorer import (  # noqa: F401
    DataExplorerState,
    DataNode,
    data_explorer,
    flatten,
)

__all__ = [
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
    # Stateless views
    "NodeRenderer",
    "shape_lens",
    "tree_lens",
    "chart_lens",
    "sparkline",
    "sparkline_with_range",
    "SpinnerState",
    "SpinnerFrames",
    "spinner",
    "DOTS",
    "LINE",
    "BRAILLE",
    "ProgressState",
    "progress_bar",
    "render_big",
    "BigTextFormat",
    "BIG_GLYPHS",
    # Stateful views
    "ListState",
    "list_view",
    "TableState",
    "Column",
    "table",
    "TextInputState",
    "text_input",
    "DataExplorerState",
    "DataNode",
    "data_explorer",
    "flatten",
]
