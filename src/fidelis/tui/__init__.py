"""TUI core: interactive app primitives.

Use this when building interactive terminal applications.
"""

from ..buffer import Buffer, BufferView, CellWrite
from ..keyboard import KeyboardInput, Input
from ..app import Surface, Emit, LifecycleHook
from ..layer import Layer, Stay, Pop, Push, Quit, Action, process_key, render_layers
from ..focus import Focus, ring_next, ring_prev, linear_next, linear_prev
from ..search import Search, filter_contains, filter_prefix, filter_fuzzy
from ..cursor import Cursor, CursorMode
from ..region import Region

__all__ = [
    # Buffer
    "Buffer",
    "BufferView",
    "CellWrite",
    # Input
    "KeyboardInput",
    "Input",
    # App
    "Surface",
    "Emit",
    "LifecycleHook",
    # Layer
    "Layer",
    "Stay",
    "Pop",
    "Push",
    "Quit",
    "Action",
    "process_key",
    "render_layers",
    # Focus
    "Focus",
    "ring_next",
    "ring_prev",
    "linear_next",
    "linear_prev",
    # Search
    "Search",
    "filter_contains",
    "filter_prefix",
    "filter_fuzzy",
    # Cursor
    "Cursor",
    "CursorMode",
    # Region
    "Region",
]
