"""Streaming topology framework: event routing, projections, persistence.

Usage:
    from framework import Stream, Consumer, Tap, EventStore, Projection, FileWriter, Forward
"""

from .store import EventStore
from .stream import Stream, Tap, Consumer
from .projection import Projection
from .file_writer import FileWriter
from .forward import Forward
from .sim import BaseSimulator, SimState
from .instrument import metrics

__all__ = [
    "Stream",
    "Tap",
    "Consumer",
    "EventStore",
    "Projection",
    "FileWriter",
    "Forward",
    "BaseSimulator",
    "SimState",
    "metrics",
]
