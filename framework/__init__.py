"""Reusable CLI framework components.

Usage from examples/:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from framework import EventStore, KeyboardInput, FilterHistory, BaseApp, Mode
"""

from .store import EventStore
from .keyboard import KeyboardInput
from .filter import FilterHistory
from .app import BaseApp, Mode
from .projection import Projection
from .debug import DebugPane
from .sim import BaseSimulator, SimState
from .instrument import metrics

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
]
