"""Views: view-layer primitives (data/state -> Block).

This is the single public namespace for Painted view-layer APIs.
"""

# Aesthetic
from .._components.data_explorer import (  # noqa: F401
    DataExplorerState,
    DataNode,
    data_explorer,
    flatten,
)

# Profile bridge
from .._profile import ProfileResult, parse_collapsed, profile  # noqa: F401

# Stateful views
from .._components.list_view import ListState, list_view  # noqa: F401
from .._components.progress import ProgressState, progress_bar  # noqa: F401
from .._components.sparkline import sparkline, sparkline_with_range  # noqa: F401
from .._components.spinner import (  # noqa: F401
    BRAILLE,
    DOTS,
    LINE,
    SpinnerFrames,
    SpinnerState,
    spinner,
)
from .._components.table import Column, TableState, table  # noqa: F401
from .._components.text_input import TextInputState, text_input  # noqa: F401

# Stateless views
from .._lens import (  # noqa: F401
    NodeRenderer,
    chart_lens,
    flame_lens,
    shape_lens,
    tree_lens,
)
from ..big_text import BIG_GLYPHS, BigTextFormat, render_big  # noqa: F401
from ..icon_set import (  # noqa: F401
    ASCII_ICONS,
    IconSet,
    current_icons,
    reset_icons,
    use_icons,
)
from ..palette import (  # noqa: F401
    DEFAULT_PALETTE,
    MONO_PALETTE,
    NORD_PALETTE,
    Palette,
    current_palette,
    reset_palette,
    use_palette,
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
    "flame_lens",
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
    # Profile bridge
    "ProfileResult",
    "profile",
    "parse_collapsed",
]
