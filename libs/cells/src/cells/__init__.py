"""Cell-buffer rendering system."""

from .cell import Style, Cell, EMPTY_CELL
from .buffer import Buffer, BufferView, CellWrite
from .writer import Writer, ColorDepth, print_block
from .block import Block, Wrap
from .compose import Align, join_horizontal, join_vertical, pad, border, truncate, vslice
from .big_text import render_big, BIG_GLYPHS, BigTextFormat
from .borders import BorderChars, ROUNDED, HEAVY, DOUBLE, LIGHT, ASCII
from .region import Region
from .focus import Focus, FocusRing, ring_next, ring_prev, linear_next, linear_prev
from .search import Search, filter_contains, filter_prefix, filter_fuzzy
from .layer import Layer, Stay, Pop, Push, Quit, Action, process_key, render_layers
from .lens import Lens, shape_lens, SHAPE_LENS
from .span import Span, Line
from .keyboard import KeyboardInput, Input
from .mouse import MouseEvent, MouseButton, MouseAction
from .app import Surface, Emit, LifecycleHook
from .components import (
    SpinnerState, SpinnerFrames, DOTS, LINE, BRAILLE, spinner,
    ProgressState, progress_bar,
    ListState, list_view,
    TextInputState, text_input,
    Column, TableState, table,
)

__all__ = [
    "Style",
    "Cell",
    "EMPTY_CELL",
    "Buffer",
    "BufferView",
    "CellWrite",
    "Writer",
    "ColorDepth",
    "print_block",
    "Block",
    "Wrap",
    "Align",
    "join_horizontal",
    "join_vertical",
    "pad",
    "border",
    "truncate",
    "vslice",
    "render_big",
    "BIG_GLYPHS",
    "BigTextFormat",
    "BorderChars",
    "ROUNDED",
    "HEAVY",
    "DOUBLE",
    "LIGHT",
    "ASCII",
    "Region",
    "Focus",
    "FocusRing",
    "ring_next",
    "ring_prev",
    "linear_next",
    "linear_prev",
    "Search",
    "filter_contains",
    "filter_prefix",
    "filter_fuzzy",
    "Layer",
    "Stay",
    "Pop",
    "Push",
    "Quit",
    "Action",
    "process_key",
    "render_layers",
    "Lens",
    "shape_lens",
    "SHAPE_LENS",
    "Span",
    "Line",
    "KeyboardInput",
    "Input",
    "MouseEvent",
    "MouseButton",
    "MouseAction",
    "Surface",
    "Emit",
    "LifecycleHook",
    "SpinnerState",
    "SpinnerFrames",
    "DOTS",
    "LINE",
    "BRAILLE",
    "spinner",
    "ProgressState",
    "progress_bar",
    "ListState",
    "list_view",
    "TextInputState",
    "text_input",
    "Column",
    "TableState",
    "table",
]
