"""Views: view-layer primitives (data/state -> Block).

This is the single public namespace for Fidelis view-layer APIs.
"""

# Aesthetic
from fidelis.icon_set import IconSet, ASCII_ICONS, current_icons, use_icons, reset_icons  # noqa: F401
from fidelis.palette import (  # noqa: F401
    Palette,
    DEFAULT_PALETTE,
    NORD_PALETTE,
    MONO_PALETTE,
    current_palette,
    use_palette,
    reset_palette,
)

# Stateless views
from fidelis._lens import (  # noqa: F401
    Lens,
    NodeRenderer,
    SHAPE_LENS,
    TREE_LENS,
    CHART_LENS,
    shape_lens,
    tree_lens,
    chart_lens,
)
from fidelis._components.sparkline import sparkline, sparkline_with_range  # noqa: F401
from fidelis._components.spinner import (  # noqa: F401
    SpinnerState,
    SpinnerFrames,
    spinner,
    DOTS,
    LINE,
    BRAILLE,
)
from fidelis._components.progress import ProgressState, progress_bar  # noqa: F401
from fidelis.big_text import render_big, BigTextFormat, BIG_GLYPHS  # noqa: F401

# Stateful views
from fidelis._components.list_view import ListState, list_view  # noqa: F401
from fidelis._components.table import TableState, Column, table  # noqa: F401
from fidelis._components.text_input import TextInputState, text_input  # noqa: F401
from fidelis._components.data_explorer import (  # noqa: F401
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
    "Lens",
    "NodeRenderer",
    "SHAPE_LENS",
    "TREE_LENS",
    "CHART_LENS",
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
