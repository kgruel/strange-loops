"""TUI core: interactive app primitives.

Use this when building interactive terminal applications.
"""

from ..app import Emit, LifecycleHook, Surface
from ..buffer import Buffer, BufferView, CellWrite
from ..cursor import Cursor, CursorMode
from ..focus import Focus, linear_next, linear_prev, ring_next, ring_prev
from ..keyboard import Input, KeyboardInput
from ..layer import Action, Layer, Pop, Push, Quit, Stay, process_key, render_layers
from ..region import Region
from ..search import Search, filter_contains, filter_fuzzy, filter_prefix
from .testing import CapturedFrame, TestSurface

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
    # Testing
    "TestSurface",
    "CapturedFrame",
]
