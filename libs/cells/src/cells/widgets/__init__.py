"""Widgets: pre-built interactive components.

State + render function pattern for common TUI elements.
"""

from ..components import (
    SpinnerState,
    SpinnerFrames,
    DOTS,
    LINE,
    BRAILLE,
    spinner,
    ProgressState,
    progress_bar,
    ListState,
    list_view,
    TextInputState,
    text_input,
    Column,
    TableState,
    table,
)

__all__ = [
    # Spinner
    "SpinnerState",
    "SpinnerFrames",
    "DOTS",
    "LINE",
    "BRAILLE",
    "spinner",
    # Progress
    "ProgressState",
    "progress_bar",
    # List
    "ListState",
    "list_view",
    # Text input
    "TextInputState",
    "text_input",
    # Table
    "Column",
    "TableState",
    "table",
]
