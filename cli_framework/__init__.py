"""Reusable CLI framework components extracted from dashboard.py and http_logger.py.

Usage from examples/:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from cli_framework import EventStore, KeyboardInput, FilterHistory, BaseApp, Mode
"""

from .store import EventStore
from .keyboard import KeyboardInput
from .filter import FilterHistory
from .app import BaseApp, Mode

__all__ = ["EventStore", "KeyboardInput", "FilterHistory", "BaseApp", "Mode"]
