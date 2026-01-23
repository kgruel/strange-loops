"""Reusable CLI framework components.

Usage from examples/:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from framework import EventStore, KeyboardInput, FilterHistory, BaseApp, Mode
    from framework.ui import app_layout, focus_panel, event_table, metrics_panel, help_bar, status_parts
"""

from .store import EventStore
from .keyboard import KeyboardInput
from .filter import FilterHistory
from .app import BaseApp, Mode
from .projection import Projection
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
    "EventStore",
    "KeyboardInput",
    "FilterHistory",
    "BaseApp",
    "Mode",
    "Projection",
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
