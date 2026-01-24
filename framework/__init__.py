"""Reusable CLI framework components.

Usage from examples/:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from framework import EventStore, FilterHistory, BaseApp, Mode
    from framework.ui import app_layout, focus_panel, event_table, metrics_panel, help_bar, status_parts
"""

from .store import EventStore
from .stream import Stream, Tap, Consumer
from .filter import FilterHistory
from .app import BaseApp, Mode
from .projection import Projection
from .file_writer import FileWriter
from .forward import Forward
from .selection import SelectionTracker
from .debug import DebugPane
from .sim import BaseSimulator, SimState
from .instrument import metrics
from .ui import (
    ColumnSpec,
    ScrollInfo,
    app_layout,
    focus_panel,
    event_table,
    metrics_panel,
    help_bar,
    status_parts,
)

__all__ = [
    "Stream",
    "Tap",
    "Consumer",
    "EventStore",
    "FilterHistory",
    "BaseApp",
    "Mode",
    "Projection",
    "FileWriter",
    "Forward",
    "SelectionTracker",
    "DebugPane",
    "BaseSimulator",
    "SimState",
    "metrics",
    # UI render helpers
    "ColumnSpec",
    "ScrollInfo",
    "app_layout",
    "focus_panel",
    "event_table",
    "metrics_panel",
    "help_bar",
    "status_parts",
]
