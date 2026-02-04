"""Lens: data structure rendering.

Transform Python data structures into Blocks at various zoom levels.
Useful at both CLI and TUI levels.
"""

from .._lens import (
    Lens,
    NodeRenderer,
    shape_lens,
    SHAPE_LENS,
    tree_lens,
    TREE_LENS,
    chart_lens,
    CHART_LENS,
)

__all__ = [
    "Lens",
    "NodeRenderer",
    "shape_lens",
    "SHAPE_LENS",
    "tree_lens",
    "TREE_LENS",
    "chart_lens",
    "CHART_LENS",
]
